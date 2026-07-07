#!/usr/bin/env python3
"""
check_progress.py -- Progress checker for the AI-Debate XMLC evaluations.

READ-ONLY. This script NEVER launches, re-runs, merges, or modifies anything.
It ONLY inspects the result files produced by the SLURM .sh jobs
(*_chunk*.json, *_full.json, *_rejudge2B.json) and reports, per evaluation:

  * which chunks exist / are missing            -> gap detection
  * records per chunk, broken down by STAGE      -> progress
  * whether a chunk looks COMPLETE or was cut off -> "needs rerun?"
  * whether chunks overlap (same pmid in >1 chunk)-> overlap check
  * whether a file is corrupt / half-written      -> crash check
  * status of the rejudge stage + its _full.json dependency

How "complete" is decided from OUTPUT FILES ALONE
------------------------------------------------
The workers loop stage-OUTER, article-INNER over 3 STAGES:
    Round 1: True Tag / Round 2: Unrelated Tag / Round 3: Similar Tag
Every article with mesh_tags yields exactly ONE record per stage, and articles
without mesh_tags are skipped identically in all stages. Therefore a FINISHED
chunk has all 3 stages present with EQUAL counts. An interrupted chunk shows
fewer than 3 stages, or unequal stage counts. In addition, every non-last chunk
should be as large as the biggest chunk (ceiling-division slicing); a short
non-last chunk was cut off. These are the only reliable signals available
without the dataset, so results are reported as heuristics.

Usage:
    python check_progress.py [DIR]        # DIR defaults to the current directory
    python check_progress.py . --chunks 4 # force expected chunk count
"""

import os
import re
import sys
import json
import argparse
from collections import defaultdict, Counter

# Stages defined in debate_utils.STAGES
EXPECTED_STAGES = [
    "Round 1: True Tag",
    "Round 2: Unrelated Tag",
    "Round 3: Similar Tag",
]
N_STAGES = len(EXPECTED_STAGES)

CHUNK_RE = re.compile(r"^(?P<base>.+?)_chunk(?P<idx>\d+)\.json$")
FULL_RE = re.compile(r"^(?P<base>.+?)_full\.json$")
REJUDGE_RE = re.compile(r"^(?P<stem>.+?)_rejudge2B\.json$")


def load_json_safe(path):
    """Return (data, error). error is None on success."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f), None
    except json.JSONDecodeError as e:
        return None, f"CORRUPT JSON ({e})"
    except OSError as e:
        return None, f"UNREADABLE ({e})"


def summarize_records(records):
    """Return (per_stage_counts, pmid_set, dup_stage_pmid_count)."""
    per_stage = Counter()
    pmids = set()
    seen = set()
    dups = 0
    for r in records:
        stage = r.get("stage")
        pmid = r.get("pmid")
        per_stage[stage] += 1
        pmids.add(pmid)
        key = (stage, pmid)
        if key in seen:
            dups += 1
        seen.add(key)
    return per_stage, pmids, dups


def scan(directory):
    files = sorted(os.listdir(directory))
    chunked = defaultdict(dict)   # base -> {idx: filename}
    full = {}                     # base -> filename
    rejudge = {}                  # stem -> filename
    for fn in files:
        m = CHUNK_RE.match(fn)
        if m:
            chunked[m.group("base")][int(m.group("idx"))] = fn
            continue
        m = REJUDGE_RE.match(fn)
        if m:
            rejudge[m.group("stem")] = fn
            continue
        m = FULL_RE.match(fn)
        if m:
            full[m.group("base")] = fn
    return chunked, full, rejudge


def analyze_chunked(directory, base, idx_to_file, forced_chunks):
    indices = sorted(idx_to_file)
    max_idx = max(indices)
    expected_n = forced_chunks - 1 if forced_chunks else max_idx
    expected = list(range(expected_n + 1))
    missing = [i for i in expected if i not in idx_to_file]

    per_chunk = {}          # idx -> dict
    all_pmids = {}          # idx -> set
    problems = []

    for i in indices:
        path = os.path.join(directory, idx_to_file[i])
        data, err = load_json_safe(path)
        if err:
            per_chunk[i] = {"error": err}
            problems.append(f"chunk{i}: {err} -> RERUN")
            continue
        records = data.get("results", []) if isinstance(data, dict) else []
        stages, pmids, dups = summarize_records(records)
        all_pmids[i] = pmids
        per_chunk[i] = {
            "records": len(records),
            "stages": stages,
            "n_stages": len([s for s in stages if s in EXPECTED_STAGES]),
            "dups": dups,
            "meta": data.get("metadata", {}) if isinstance(data, dict) else {},
        }
        if dups:
            problems.append(f"chunk{i}: {dups} duplicate (stage,pmid) records")

    # biggest per-stage count = size of a full chunk
    full_stage_n = 0
    for i, info in per_chunk.items():
        if "error" in info:
            continue
        if info["stages"]:
            full_stage_n = max(full_stage_n, max(info["stages"].values()))

    # completeness per chunk
    for i in indices:
        info = per_chunk[i]
        if "error" in info:
            info["status"] = "CORRUPT"
            continue
        counts = [info["stages"].get(s, 0) for s in EXPECTED_STAGES]
        present = info["n_stages"]
        is_last = (i == max_idx)
        balanced = present == N_STAGES and len(set(counts)) == 1 and counts[0] > 0
        full_size = is_last or (counts and max(counts) >= full_stage_n)
        if balanced and full_size:
            info["status"] = "COMPLETE"
        elif balanced and not full_size:
            info["status"] = "SHORT?"   # balanced but smaller than siblings
            problems.append(
                f"chunk{i}: balanced but only {counts[0]}/{full_stage_n} "
                f"per stage -> likely cut off, RERUN")
        else:
            info["status"] = "PARTIAL"
            problems.append(
                f"chunk{i}: stages present={present}/{N_STAGES}, "
                f"counts={counts} -> interrupted, RERUN")

    for i in missing:
        problems.append(f"chunk{i}: MISSING -> RERUN")

    # overlap check across chunks
    idxs = sorted(all_pmids)
    for a in range(len(idxs)):
        for b in range(a + 1, len(idxs)):
            ia, ib = idxs[a], idxs[b]
            common = all_pmids[ia] & all_pmids[ib]
            if common:
                sample = list(common)[:5]
                problems.append(
                    f"OVERLAP chunk{ia} & chunk{ib}: {len(common)} shared "
                    f"pmids e.g. {sample}")

    return {
        "expected": expected,
        "missing": missing,
        "per_chunk": per_chunk,
        "full_stage_n": full_stage_n,
        "problems": problems,
    }


def print_eval(base, res):
    print("=" * 72)
    print(f"EVALUATION: {base}")
    print("-" * 72)
    header = f"{'chunk':<6}{'records':<9}{'R1':<7}{'R2':<7}{'R3':<7}{'status':<10}"
    print(header)
    for i in res["expected"]:
        info = res["per_chunk"].get(i)
        if info is None:
            print(f"{i:<6}{'-':<9}{'-':<7}{'-':<7}{'-':<7}{'MISSING':<10}")
            continue
        if "error" in info:
            print(f"{i:<6}{'-':<9}{'-':<7}{'-':<7}{'-':<7}{'CORRUPT':<10}")
            continue
        s = info["stages"]
        print(f"{i:<6}{info['records']:<9}"
              f"{s.get(EXPECTED_STAGES[0],0):<7}"
              f"{s.get(EXPECTED_STAGES[1],0):<7}"
              f"{s.get(EXPECTED_STAGES[2],0):<7}"
              f"{info['status']:<10}")

    done = sum(1 for i in res["expected"]
               if res["per_chunk"].get(i, {}).get("status") == "COMPLETE")
    total = len(res["expected"])
    print("-" * 72)
    print(f"  chunks complete: {done}/{total}"
          f"   (full-chunk stage size ~= {res['full_stage_n']})")
    if res["problems"]:
        print("  ACTION NEEDED:")
        for p in res["problems"]:
            print(f"    - {p}")
    else:
        print("  OK: no gaps, no overlaps, all chunks complete. No rerun needed.")
    print()
    return done == total and not res["problems"]


def main():
    ap = argparse.ArgumentParser(description="Read-only progress checker.")
    ap.add_argument("directory", nargs="?", default=".",
                    help="Directory with the result JSON files (default: .)")
    ap.add_argument("--chunks", type=int, default=None,
                    help="Force expected total chunks per eval (e.g. 4).")
    args = ap.parse_args()

    directory = args.directory
    if not os.path.isdir(directory):
        sys.exit(f"Not a directory: {directory}")

    chunked, full, rejudge = scan(directory)

    if not chunked and not full and not rejudge:
        print("No result files (*_chunk*.json / *_full.json / *_rejudge2B.json) found.")
        return

    print(f"Scanning: {os.path.abspath(directory)}\n")

    all_ok = True
    finished_bases = set()
    for base in sorted(chunked):
        res = analyze_chunked(directory, base, chunked[base], args.chunks)
        ok = print_eval(base, res)
        all_ok = all_ok and ok
        if ok:
            finished_bases.add(base)

    # ---- Rejudge stage (depends on *_full.json produced by merging chunks) ----
    print("=" * 72)
    print("REJUDGE (2B) STAGE")
    print("-" * 72)
    for mode, base in (("interactive", "interactive_results"),
                       ("statement", "statement_results")):
        full_name = f"{base}_full.json"
        out_name = f"{base}_full_rejudge2B.json"
        has_full = os.path.exists(os.path.join(directory, full_name))
        out_stem = f"{base}_full"
        has_out = out_stem in rejudge

        if has_out:
            path = os.path.join(directory, rejudge[out_stem])
            data, err = load_json_safe(path)
            if err:
                print(f"  {mode:<12}: output {rejudge[out_stem]} {err} -> RERUN")
            else:
                n = len(data.get("results", []))
                src_n = None
                if has_full:
                    sd, _ = load_json_safe(os.path.join(directory, full_name))
                    if isinstance(sd, dict):
                        src_n = len(sd.get("results", []))
                if src_n is not None:
                    status = "COMPLETE" if n >= src_n else "PARTIAL -> RERUN"
                    print(f"  {mode:<12}: {n}/{src_n} records  {status}")
                else:
                    print(f"  {mode:<12}: {n} records (source _full.json absent, "
                          f"cannot verify completeness)")
        elif has_full:
            print(f"  {mode:<12}: source {full_name} present, but rejudge NOT "
                  f"started -> run submit_rejudge.sh")
        else:
            merged = "READY" if base in finished_bases else "chunks INCOMPLETE"
            print(f"  {mode:<12}: BLOCKED - {full_name} missing.")
            print(f"               chunks are {merged}; you must MERGE the 4 "
                  f"{base}_chunk*.json into {full_name} first,")
            print(f"               otherwise submit_rejudge.sh crashes "
                  f"(FileNotFoundError).")
            all_ok = False
    print()

    print("=" * 72)
    if all_ok:
        print("SUMMARY: all chunked evaluations complete, no overlaps/corruption. "
              "Only the rejudge stage may still need attention (see above).")
    else:
        print("SUMMARY: some evaluations need a rerun/merge - see 'ACTION NEEDED' "
              "and 'REJUDGE' sections above.")


if __name__ == "__main__":
    main()
