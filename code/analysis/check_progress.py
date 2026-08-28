#!/usr/bin/env python3
"""
check_progress.py

READ-ONLY progress checker for the AI-Debate XMLC evaluations.

It NEVER launches or re-runs anything. It only inspects the output files
produced by the SLURM jobs (the *_chunk<N>.json files) and reports, per
evaluation, how far along each chunk is and whether it must be (re-)run.

For every evaluation that is INCOMPLETE it now also prints the exact
sbatch command needed to resume it. Because every debate_*.py script is
resumable (U.load_checkpoint fast-forwards finished (stage, pmid) records
and U.save_results_atomically writes atomically), simply re-submitting the
job continues where it stopped -- no finished work is repeated.

Usage:
    python3 check_progress.py [directory]     # default: current dir
"""

import os
import re
import sys
import json
import glob
from collections import defaultdict

# --------------------------------------------------------------------------- #
# CONFIG -- adjust here if you rename things
# --------------------------------------------------------------------------- #

# The three rounds defined in debate_utils.STAGES (order matters: R1, R2, R3).
STAGE_NAMES = [
    "Round 1: True Tag",
    "Round 2: Unrelated Tag",
    "Round 3: Similar Tag",
]

# Map an evaluation base name -> (submit script, number of array chunks).
# These are YOUR five pipelines. Anything not in here (e.g. the pydantic_*
# files, which come from a different script set) gets no auto-command.
SUBMIT_MAP = {
    "baseline_withmanual_results": ("submit_baseline.sh", 4),
    "baseline_nomanual_results":   ("submit_baseline_nomanual.sh", 4),
    "interactive_results":         ("submit_interactive.sh", 4),
    "statement_results":           ("submit_statement.sh", 4),
}

# Rejudge (2B) stage: reads *_full.json produced by merging the chunks.
REJUDGE_SUBMIT = "submit_rejudge.sh"
REJUDGE_TASKS = {          # array task id -> (mode, source base name)
    0: "interactive_results",
    1: "statement_results",
}
MERGE_HELPER = "merge_chunks.py"

CHUNK_RE = re.compile(r"^(.*)_chunk(\d+)\.json$")


# --------------------------------------------------------------------------- #
# Loading / counting
# --------------------------------------------------------------------------- #
def discover_chunks(directory):
    """Return {base_name: {chunk_id: filepath}}."""
    groups = defaultdict(dict)
    for path in glob.glob(os.path.join(directory, "*_chunk*.json")):
        name = os.path.basename(path)
        m = CHUNK_RE.match(name)
        if not m:
            continue
        base, cid = m.group(1), int(m.group(2))
        groups[base][cid] = path
    return groups


def load_chunk(path):
    """Return (records_list, corrupt_bool). Corrupt = interrupted mid-write."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data.get("results", []), False
    except (json.JSONDecodeError, OSError):
        return [], True


def stage_counts(records):
    """Count records per stage -> [R1, R2, R3]."""
    counts = {s: 0 for s in STAGE_NAMES}
    for r in records:
        s = r.get("stage")
        if s in counts:
            counts[s] += 1
    return [counts[s] for s in STAGE_NAMES]


def record_keys(records):
    """Set of (stage, pmid) for overlap detection."""
    return {(r.get("stage"), r.get("pmid")) for r in records}


# --------------------------------------------------------------------------- #
# Per-evaluation analysis
# --------------------------------------------------------------------------- #
def analyse_group(base, chunkmap):
    """Return a dict describing one evaluation."""
    chunks = {}
    all_keys_per_chunk = {}
    for cid, path in sorted(chunkmap.items()):
        records, corrupt = load_chunk(path)
        counts = stage_counts(records)
        chunks[cid] = {
            "records": len(records),
            "counts": counts,
            "corrupt": corrupt,
        }
        all_keys_per_chunk[cid] = record_keys(records)

    # Expected full-chunk stage size = max R1 seen across chunks.
    full_stage = max((c["counts"][0] for c in chunks.values()), default=0)

    # Complete = all three stages equal & > 0 (and not corrupt).
    for cid, c in chunks.items():
        r1, r2, r3 = c["counts"]
        c["complete"] = (not c["corrupt"]) and r1 > 0 and r1 == r2 == r3
        c["stages_present"] = sum(1 for x in c["counts"] if x > 0)

    # Overlap detection: same (stage, pmid) in two different chunks.
    overlaps = []
    cids = sorted(chunks)
    for a in range(len(cids)):
        for b in range(a + 1, len(cids)):
            inter = all_keys_per_chunk[cids[a]] & all_keys_per_chunk[cids[b]]
            if inter:
                overlaps.append((cids[a], cids[b], len(inter)))

    # Gaps: expected chunk ids from the submit map (0..total-1).
    expected_total = SUBMIT_MAP.get(base, (None, None))[1]
    missing = []
    if expected_total:
        missing = [i for i in range(expected_total) if i not in chunks]

    return {
        "base": base,
        "chunks": chunks,
        "full_stage": full_stage,
        "overlaps": overlaps,
        "missing": missing,
        "expected_total": expected_total,
    }


def rerun_command(base, info):
    """Build the resumable sbatch command for a failed evaluation, or None."""
    if base not in SUBMIT_MAP:
        return None
    submit, total = SUBMIT_MAP[base]
    failed = sorted(
        cid for cid, c in info["chunks"].items() if not c["complete"]
    )
    failed = sorted(set(failed) | set(info["missing"]))
    if not failed:
        return None
    if len(failed) == total and failed == list(range(total)):
        return "sbatch %s" % submit
    ids = ",".join(str(i) for i in failed)
    return "sbatch --array=%s %s" % (ids, submit)


# --------------------------------------------------------------------------- #
# Reporting
# --------------------------------------------------------------------------- #
def print_group(info):
    base = info["base"]
    chunks = info["chunks"]
    print("\n" + "=" * 72)
    print("EVALUATION: %s" % base)
    print("-" * 72)
    print("%-6s%-9s%-7s%-7s%-7s%-10s"
          % ("chunk", "records", "R1", "R2", "R3", "status"))
    complete = 0
    for cid in sorted(chunks):
        c = chunks[cid]
        if c["corrupt"]:
            status = "CORRUPT"
        elif c["complete"]:
            status = "COMPLETE"
            complete += 1
        else:
            status = "PARTIAL"
        r1, r2, r3 = c["counts"]
        print("%-6s%-9s%-7s%-7s%-7s%-10s"
              % (cid, c["records"], r1, r2, r3, status))
    print("-" * 72)
    total = info["expected_total"] or len(chunks)
    print("  chunks complete: %d/%d   (full-chunk stage size ~= %d)"
          % (complete, total, info["full_stage"]))

    problems = False

    # Missing chunk files
    if info["missing"]:
        problems = True
        print("  ACTION NEEDED:")
        print("    - missing chunk file(s): %s"
              % ", ".join("chunk%d" % i for i in info["missing"]))

    # Overlaps
    if info["overlaps"]:
        problems = True
        if not info["missing"]:
            print("  ACTION NEEDED:")
        for a, b, n in info["overlaps"]:
            print("    - OVERLAP: chunk%d and chunk%d share %d (stage,pmid) keys"
                  % (a, b, n))

    # Incomplete / corrupt chunks
    incomplete = [(cid, c) for cid, c in sorted(chunks.items())
                  if not c["complete"]]
    if incomplete:
        if not (info["missing"] or info["overlaps"]):
            print("  ACTION NEEDED:")
        problems = True
        for cid, c in incomplete:
            reason = "CORRUPT -> file truncated mid-write" if c["corrupt"] \
                else "interrupted, RERUN"
            print("    - chunk%d: stages present=%d/3, counts=%s -> %s"
                  % (cid, c["stages_present"], c["counts"], reason))

    if problems:
        cmd = rerun_command(base, info)
        if cmd:
            print("    >> RERUN (resumable, finished records are skipped):")
            print("       %s" % cmd)
        else:
            print("    >> No submit script mapped for '%s'." % base)
            print("       (Not one of your five pipelines -- e.g. pydantic_* "
                  "comes from a different script set.)")
    else:
        print("  OK: no gaps, no overlaps, all chunks complete. "
              "No rerun needed.")

    return not problems


def print_rejudge(directory, groups):
    print("\n" + "=" * 72)
    print("REJUDGE (2B) STAGE")
    print("-" * 72)
    for task_id, base in REJUDGE_TASKS.items():
        mode = "interactive" if base.startswith("interactive") else "statement"
        full_path = os.path.join(directory, "%s_full.json" % base)
        rejudge_out = os.path.join(directory, "%s_full_rejudge2B.json" % base)

        # Are the source chunks even complete?
        src_complete = False
        if base in groups:
            info = analyse_group(base, groups[base])
            src_complete = (not info["missing"]
                            and all(c["complete"]
                                    for c in info["chunks"].values()))

        if os.path.exists(rejudge_out):
            print("  %-11s: rejudge output already exists (%s)."
                  % (mode, os.path.basename(rejudge_out)))
            continue

        if os.path.exists(full_path):
            print("  %-11s: source ready. Run 2B rejudge:" % mode)
            print("               sbatch --array=%d %s"
                  % (task_id, REJUDGE_SUBMIT))
            continue

        # No _full.json yet -> blocked; needs merge (and maybe finish first).
        print("  %-11s: BLOCKED - %s_full.json missing." % (mode, base))
        if not src_complete:
            print("               chunks INCOMPLETE -> first finish them, then merge.")
            print("               1) sbatch %s"
                  % SUBMIT_MAP.get(base, ("<submit>.sh", 0))[0])
            print("               2) python3 %s %s" % (MERGE_HELPER, base))
            print("               3) sbatch --array=%d %s"
                  % (task_id, REJUDGE_SUBMIT))
        else:
            print("               chunks complete -> just merge, then rejudge:")
            print("               1) python3 %s %s" % (MERGE_HELPER, base))
            print("               2) sbatch --array=%d %s"
                  % (task_id, REJUDGE_SUBMIT))


def print_command_block(directory, groups, results):
    """Consolidated, copy-paste command list in dependency order."""
    lines = []

    # Stage 1: resume any incomplete chunked pipeline.
    for base in SUBMIT_MAP:
        if base not in groups:
            continue
        info = analyse_group(base, groups[base])
        cmd = rerun_command(base, info)
        if cmd:
            lines.append(cmd)

    if not lines:
        # nothing to resume; maybe only rejudge/merge pending
        needs_rejudge = []
        for task_id, base in REJUDGE_TASKS.items():
            full_path = os.path.join(directory, "%s_full.json" % base)
            rejudge_out = os.path.join(directory,
                                       "%s_full_rejudge2B.json" % base)
            if not os.path.exists(rejudge_out):
                needs_rejudge.append((task_id, base,
                                      os.path.exists(full_path)))
        if not needs_rejudge:
            return

    print("\n" + "=" * 72)
    print("COMMANDS TO RUN (dependency order)")
    print("-" * 72)

    if lines:
        print("# 1) Resume/complete the chunked pipelines (safe & resumable):")
        for c in lines:
            print("   %s" % c)

    # Stage 2/3: merge + rejudge, only for the two rejudge sources.
    merge_needed = []
    rejudge_needed = []
    for task_id, base in REJUDGE_TASKS.items():
        full_path = os.path.join(directory, "%s_full.json" % base)
        rejudge_out = os.path.join(directory, "%s_full_rejudge2B.json" % base)
        if os.path.exists(rejudge_out):
            continue
        if not os.path.exists(full_path):
            merge_needed.append(base)
        rejudge_needed.append(task_id)

    if merge_needed:
        print("# 2) AFTER those finish, merge chunks into *_full.json:")
        for base in merge_needed:
            print("   python3 %s %s" % (MERGE_HELPER, base))
    if rejudge_needed:
        print("# 3) Then run the 2B rejudge:")
        ids = ",".join(str(i) for i in sorted(rejudge_needed))
        print("   sbatch --array=%s %s" % (ids, REJUDGE_SUBMIT))


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #
def main():
    directory = sys.argv[1] if len(sys.argv) > 1 else os.getcwd()
    directory = os.path.abspath(directory)
    print("Scanning: %s" % directory)

    groups = discover_chunks(directory)
    if not groups:
        print("No *_chunk*.json files found.")
        return

    results = {}
    for base in sorted(groups):
        info = analyse_group(base, groups[base])
        ok = print_group(info)
        results[base] = ok

    print_rejudge(directory, groups)
    print_command_block(directory, groups, results)

    print("\n" + "=" * 72)
    if all(results.values()):
        print("SUMMARY: all discovered evaluations complete. "
              "Only the merge + rejudge steps (if any) remain.")
    else:
        print("SUMMARY: some evaluations need a rerun/merge - see "
              "'ACTION NEEDED', 'REJUDGE' and 'COMMANDS TO RUN' above.")


if __name__ == "__main__":
    main()
