#!/usr/bin/env python3
"""
answer_debate_questions.py  -- READ-ONLY analysis + completeness checker.

Answers the six project questions and reports what has NOT finished yet.

SAFETY GUARANTEES
-----------------
* This script NEVER writes to, renames, or deletes any *_results*.json file.
* It only READS the result files and writes TWO fresh outputs with new names:
      debate_qa_report.md
      debate_qa_report.json
  (If those exist, they are timestamp-suffixed instead of overwritten.)
* Python 3.6 compatible: no f-string-free requirement, but no PEP 604 unions,
  no `from __future__ import annotations`, no external deps (pure stdlib).

Usage:
    python3 answer_debate_questions.py [directory]     # default: $DEBATE_DIR or CWD
"""

import os
import sys
import json
import math
import time
from collections import defaultdict

SCAN_DIR = None  # set in main()

# --------------------------------------------------------------------------- #
# Dataset registry (9 datasets). 'debater_framing' = whether A/B logprobs exist
# (include_debater=True in the generator). Baseline has NO A/B framing.
# --------------------------------------------------------------------------- #
DATASETS = [
    ("baseline_withmanual",   "baseline_withmanual_results_full.json",          "single", "logprob", False, 3000, "0.8B"),
    ("baseline_nomanual",     "baseline_nomanual_results_full.json",            "single", "logprob", False, 3000, "0.8B"),
    ("statement",             "statement_results_full.json",                    "single", "logprob", True,  3000, "0.8B"),
    ("statement_rejudge2B",   "statement_results_full_rejudge2B.json",          "single", "logprob", True,  3000, "2B"),
    ("interactive",           "interactive_results_full.json",                  "dual",   "logprob", True,  3000, "0.8B"),
    ("interactive_rejudge2B", "interactive_results_full_rejudge2B.json",        "dual",   "logprob", True,  3000, "2B"),
    ("pydantic_baseline",     "pydantic_baseline_results_full.json",            "single", "pydantic", False, 3000, "0.8B"),
    ("pydantic_statement",    "pydantic_statement_results_full.json",           "single", "pydantic", True,  3000, "0.8B"),
    ("pydantic_interactive",  "pydantic_interactive_results_full.json",         "dual",   "pydantic", True,  3000, "0.8B"),
]

STAGE_TRUE_LABEL = {
    "Round 1: True Tag":      "Yes",
    "Round 2: Unrelated Tag": "No",
    "Round 3: Similar Tag":   "No",
}
STAGES = list(STAGE_TRUE_LABEL)
VALID = {"Yes", "No"}

PRED_KEYS   = ["prediction", "verdict", "judge_verdict", "answer", "final_verdict", "model_prediction"]
STAGE_KEYS  = ["stage", "round", "stage_name"]
PMID_KEYS   = ["pmid", "pmID", "pm_id", "id"]
FB_KEYS     = ["needed_fallback", "used_fallback", "fallback"]
CORRECT_KEYS = ["is_correct", "correct"]


# --------------------------------------------------------------------------- #
# small helpers
# --------------------------------------------------------------------------- #
def first_key(d, keys, default=None):
    if not isinstance(d, dict):
        return default
    for k in keys:
        if k in d and d[k] is not None:
            return d[k]
    return default


def norm_pred(raw):
    if raw is None:
        return None
    s = str(raw).strip().lower()
    if s in ("yes", "y", "true", "belongs", "1"):
        return "Yes"
    if s in ("no", "n", "false", "not", "does not belong", "0"):
        return "No"
    return None


def norm_stage(raw):
    if raw is None:
        return "UNKNOWN_STAGE"
    s = str(raw).lower()
    for canon in STAGE_TRUE_LABEL:
        if canon.lower() in s:
            return canon
    if "true" in s or "round 1" in s or "round1" in s:
        return "Round 1: True Tag"
    if "unrelated" in s or "round 2" in s or "round2" in s:
        return "Round 2: Unrelated Tag"
    if "similar" in s or "round 3" in s or "round3" in s:
        return "Round 3: Similar Tag"
    return str(raw)


def mean(xs):
    xs = [x for x in xs if isinstance(x, (int, float))]
    return sum(xs) / len(xs) if xs else None


def median(xs):
    xs = sorted(x for x in xs if isinstance(x, (int, float)))
    n = len(xs)
    if n == 0:
        return None
    if n % 2:
        return xs[n // 2]
    return (xs[n // 2 - 1] + xs[n // 2]) / 2.0


def pearson(xs, ys):
    pairs = [(x, y) for x, y in zip(xs, ys)
             if isinstance(x, (int, float)) and isinstance(y, (int, float))]
    n = len(pairs)
    if n < 3:
        return None
    mx = sum(p[0] for p in pairs) / n
    my = sum(p[1] for p in pairs) / n
    num = sum((p[0] - mx) * (p[1] - my) for p in pairs)
    dx = math.sqrt(sum((p[0] - mx) ** 2 for p in pairs))
    dy = math.sqrt(sum((p[1] - my) ** 2 for p in pairs))
    if dx == 0 or dy == 0:
        return None
    return num / (dx * dy)


def pct(a, b):
    return (100.0 * a / b) if b else 0.0


def fmt(x, nd=3):
    return ("%." + str(nd) + "f") % x if isinstance(x, (int, float)) else "n/a"


# --------------------------------------------------------------------------- #
# confidence accessors (schema-locked, tolerant of missing/null)
# --------------------------------------------------------------------------- #
def conf_dict(container):
    if not isinstance(container, dict):
        return {}
    c = container.get("confidence")
    return c if isinstance(c, dict) else {}


def margin(lp, a, b):
    if isinstance(lp, dict) and a in lp and b in lp:
        try:
            return float(lp[a]) - float(lp[b])
        except Exception:
            return None
    return None


def conf_features(container):
    c = conf_dict(container)
    return {
        "p_belongs": c.get("verdict_prob_belongs"),
        "p_true":    c.get("boolean_prob_true"),
        "p_a_right": c.get("debater_prob_A_right"),
        "verdict_margin": margin(c.get("verdict_logprob"), "Yes", "No"),
        "boolean_margin": margin(c.get("boolean_logprob"), "true", "false"),
        "debater_margin": margin(c.get("debater_logprob"), "A", "B"),
        "has_conf": bool(c),
    }


# --------------------------------------------------------------------------- #
# record -> views
# --------------------------------------------------------------------------- #
def record_to_views(rec):
    stage = norm_stage(first_key(rec, STAGE_KEYS))
    pmid = first_key(rec, PMID_KEYS)
    fb = bool(first_key(rec, FB_KEYS, False))
    views = []
    if any(k in rec for k in ("judge_ABA", "judge_BAB")):
        for order, subkey in (("ABA", "judge_ABA"), ("BAB", "judge_BAB")):
            sub = rec.get(subkey)
            if not isinstance(sub, dict):
                continue
            views.append({
                "stage": stage, "pmid": pmid, "order": order,
                "fallback": bool(first_key(sub, FB_KEYS, fb)),
                "pred": norm_pred(first_key(sub, PRED_KEYS, first_key(rec, PRED_KEYS))),
                "raw_pred": first_key(sub, PRED_KEYS, first_key(rec, PRED_KEYS)),
                "container": sub,
            })
    else:
        views.append({
            "stage": stage, "pmid": pmid, "order": None, "fallback": fb,
            "pred": norm_pred(first_key(rec, PRED_KEYS)),
            "raw_pred": first_key(rec, PRED_KEYS),
            "container": rec,
        })
    return views


def view_correct(v):
    tl = STAGE_TRUE_LABEL.get(v["stage"])
    if tl is not None and v["pred"] in VALID:
        return v["pred"] == tl
    return None


# --------------------------------------------------------------------------- #
# loading
# --------------------------------------------------------------------------- #
def load_records(path):
    with open(path, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    if isinstance(data, dict):
        for k in ("results", "records", "data", "items"):
            if isinstance(data.get(k), list):
                return data.get(k), data.get("metadata", {})
        # fall back to longest list value
        lists = [v for v in data.values() if isinstance(v, list)]
        if lists:
            return max(lists, key=len), data.get("metadata", {})
        return [], data.get("metadata", {})
    if isinstance(data, list):
        return data, {}
    return [], {}


# --------------------------------------------------------------------------- #
# per-dataset core analysis
# --------------------------------------------------------------------------- #
def analyze(name, records, meta, spec):
    dtype, backend, has_ab, expected, judge = spec
    views = []
    for r in records:
        views.extend(record_to_views(r))

    # ---- completeness / stage balance -------------------------------- #
    rec_stage = defaultdict(int)
    for r in records:
        rec_stage[norm_stage(first_key(r, STAGE_KEYS))] += 1
    stage_counts = {s: rec_stage.get(s, 0) for s in STAGES}
    n_records = len(records)
    balanced = len(set(stage_counts.values())) == 1 and min(stage_counts.values() or [0]) > 0
    complete = (n_records >= expected) and balanced

    # ---- parse filter ------------------------------------------------ #
    parsed = [v for v in views if v["pred"] in VALID]
    dropped = [v for v in views if v["pred"] not in VALID]
    unknown_examples = [str(v["raw_pred"]) for v in dropped][:5]
    fb_used = sum(1 for v in views if v["fallback"])

    # ---- accuracy + yes-bias ---------------------------------------- #
    acc = {"ALL": [0, 0]}
    pred_yes = defaultdict(int)
    n_by_stage = defaultdict(int)
    false_yes = false_no = 0
    for v in parsed:
        st = v["stage"]
        acc.setdefault(st, [0, 0])
        c = view_correct(v)
        n_by_stage[st] += 1
        if v["pred"] == "Yes":
            pred_yes[st] += 1
            if STAGE_TRUE_LABEL.get(st) == "No":
                false_yes += 1
        elif v["pred"] == "No" and STAGE_TRUE_LABEL.get(st) == "Yes":
            false_no += 1
        if c is not None:
            acc["ALL"][1] += 1
            acc[st][1] += 1
            if c:
                acc["ALL"][0] += 1
                acc[st][0] += 1

    n_all = len(parsed)
    true_yes_all = sum(1 for v in parsed if STAGE_TRUE_LABEL.get(v["stage"]) == "Yes")
    pred_yes_all = sum(pred_yes.values())
    yes_bias = pct(pred_yes_all, n_all) - pct(true_yes_all, n_all)

    # ---- is_correct cross-check ------------------------------------- #
    mism = 0
    for v in parsed:
        stored = first_key(v["container"], CORRECT_KEYS)
        c = view_correct(v)
        if stored is not None and c is not None and bool(stored) != c:
            mism += 1

    # ---- confidence features (Q1) ----------------------------------- #
    feats = [conf_features(v["container"]) for v in parsed]
    def col(k):
        return [f[k] for f in feats if f[k] is not None]
    vm, bm, dm = col("verdict_margin"), col("boolean_margin"), col("debater_margin")
    pb, pt, pa = col("p_belongs"), col("p_true"), col("p_a_right")
    n_conf = sum(1 for f in feats if f["has_conf"])

    # calibration: verdict margin when correct vs incorrect
    vm_correct = [conf_features(v["container"])["verdict_margin"] for v in parsed
                  if view_correct(v) is True]
    vm_wrong   = [conf_features(v["container"])["verdict_margin"] for v in parsed
                  if view_correct(v) is False]
    vm_correct = [x for x in vm_correct if x is not None]
    vm_wrong   = [x for x in vm_wrong if x is not None]

    corr_vb = pearson(pb, pt)
    boolean_inverted = (corr_vb is not None and corr_vb < -0.15)

    return {
        "name": name, "type": dtype, "backend": backend, "judge": judge,
        "expected": expected, "n_records": n_records, "n_views": len(views),
        "stage_counts": stage_counts, "balanced": balanced, "complete": complete,
        "parsed": len(parsed), "dropped": len(dropped),
        "unknown_examples": unknown_examples, "fallback_used": fb_used,
        "acc_all": acc["ALL"], "acc_stage": {s: acc.get(s, [0, 0]) for s in STAGES},
        "pred_yes_pct": pct(pred_yes_all, n_all), "true_yes_pct": pct(true_yes_all, n_all),
        "yes_bias": yes_bias, "false_yes": false_yes, "false_no": false_no,
        "is_correct_mismatches": mism,
        "n_conf": n_conf,
        "verdict_margin_mean": mean(vm), "verdict_margin_med": median(vm),
        "boolean_margin_mean": mean(bm),
        "debater_margin_mean": mean(dm),
        "p_belongs_mean": mean(pb), "p_true_mean": mean(pt), "p_a_right_mean": mean(pa),
        "corr_verdict_boolean": corr_vb, "boolean_inverted": boolean_inverted,
        "vm_correct_mean": mean(vm_correct), "vm_wrong_mean": mean(vm_wrong),
        "has_ab_framing": has_ab,
        "_records": records,  # kept for cross-dataset (Q2/Q4); stripped before JSON dump
    }


# --------------------------------------------------------------------------- #
# Q2 : ABA vs BAB (interactive datasets)
# --------------------------------------------------------------------------- #
def q2_order_effect(records):
    n = 0
    aba_c = bab_c = 0
    flips = 0
    flip_yes_to_no = flip_no_to_yes = 0
    pa_aba, pa_bab = [], []
    for r in records:
        a = r.get("judge_ABA"); b = r.get("judge_BAB")
        if not isinstance(a, dict) or not isinstance(b, dict):
            continue
        st = norm_stage(first_key(r, STAGE_KEYS))
        tl = STAGE_TRUE_LABEL.get(st)
        pa = norm_pred(first_key(a, PRED_KEYS)); pbv = norm_pred(first_key(b, PRED_KEYS))
        if pa not in VALID or pbv not in VALID:
            continue
        n += 1
        if tl is not None:
            aba_c += (pa == tl); bab_c += (pbv == tl)
        if pa != pbv:
            flips += 1
            if pa == "Yes" and pbv == "No":
                flip_yes_to_no += 1
            elif pa == "No" and pbv == "Yes":
                flip_no_to_yes += 1
        fa = conf_features(a)["p_a_right"]; fb = conf_features(b)["p_a_right"]
        if fa is not None: pa_aba.append(fa)
        if fb is not None: pa_bab.append(fb)
    return {
        "n": n,
        "acc_ABA": pct(aba_c, n), "acc_BAB": pct(bab_c, n),
        "flip_pct": pct(flips, n),
        "flip_Yes->No": flip_yes_to_no, "flip_No->Yes": flip_no_to_yes,
        "mean_P_A_right_ABA": mean(pa_aba), "mean_P_A_right_BAB": mean(pa_bab),
    }


# --------------------------------------------------------------------------- #
# Q4 : 2B vs 0.8B on the SHARED (stage,pmid) subset only
# --------------------------------------------------------------------------- #
def correctness_map_single(records):
    out = {}
    for r in records:
        key = (norm_stage(first_key(r, STAGE_KEYS)), first_key(r, PMID_KEYS))
        pred = norm_pred(first_key(r, PRED_KEYS))
        tl = STAGE_TRUE_LABEL.get(key[0])
        if pred in VALID and tl is not None:
            out[key] = (pred == tl)
    return out


def correctness_map_dual(records):
    out = {}
    for r in records:
        key = (norm_stage(first_key(r, STAGE_KEYS)), first_key(r, PMID_KEYS))
        tl = STAGE_TRUE_LABEL.get(key[0])
        vals = []
        for sk in ("judge_ABA", "judge_BAB"):
            sub = r.get(sk)
            if isinstance(sub, dict):
                p = norm_pred(first_key(sub, PRED_KEYS))
                if p in VALID and tl is not None:
                    vals.append(p == tl)
        if vals:
            out[key] = sum(vals) / len(vals)  # avg correctness over ABA+BAB
    return out


def q4_subset_compare(full_map, rej_map):
    keys = set(full_map) & set(rej_map)
    if not keys:
        return None
    base = sum(full_map[k] for k in keys) / len(keys) * 100
    large = sum(rej_map[k] for k in keys) / len(keys) * 100
    return {"shared_keys": len(keys), "acc_0.8B": base, "acc_2B": large,
            "delta_pp": large - base}


# --------------------------------------------------------------------------- #
# reporting
# --------------------------------------------------------------------------- #
def build_report(res, q2, q4):
    L = []
    w = L.append
    w("# AI-Debate XMLC -- Question-driven analysis (read-only)\n")
    w("Directory scanned: `%s`\n" % SCAN_DIR)

    # ---- completeness ------------------------------------------------ #
    w("## 0. File presence & completeness (has anything not gone through?)\n")
    w("| dataset | backend | judge | records | expected | R1 | R2 | R3 | balanced | STATUS |")
    w("|---|---|---|---|---|---|---|---|---|---|")
    for r in res:
        sc = r["stage_counts"]
        status = "COMPLETE" if r["complete"] else ("PARTIAL/INCOMPLETE" if r["n_records"] else "EMPTY")
        w("| %s | %s | %s | %d | %d | %d | %d | %d | %s | %s |" % (
            r["name"], r["backend"], r["judge"], r["n_records"], r["expected"],
            sc[STAGES[0]], sc[STAGES[1]], sc[STAGES[2]],
            "yes" if r["balanced"] else "NO", status))
    w("")
    w("Missing expected files:")
    names = set(x["name"] for x in res)
    for spec in DATASETS:
        if spec[0] not in names:
            w("- **%s** (`%s`) not found" % (spec[0], spec[1]))
    w("")

    # ---- Q3 unknowns ------------------------------------------------- #
    w("## Q3. Unforced / Unknown verdicts (unparsable predictions)\n")
    w("| dataset | backend | views | parsed | DROPPED (unknown) | fallback used | examples |")
    w("|---|---|---|---|---|---|---|")
    for r in res:
        w("| %s | %s | %d | %d | %d | %d | %s |" % (
            r["name"], r["backend"], r["n_views"], r["parsed"], r["dropped"],
            r["fallback_used"], "; ".join(r["unknown_examples"]) or "-"))
    w("\nLogprob runs should show 0 dropped (guaranteed argmax fallback). "
      "Any drops in **pydantic_*** are the real 'Unknown' cases (no logprob fallback).\n")

    # ---- Q6 manual vs no-manual + Q5 input ladder -------------------- #
    w("## Q5/Q6. Accuracy, Yes-bias & confidence across formats\n")
    w("| dataset | judge | acc % | R1 | R2 | R3 | pred-Yes % | true-Yes % | Yes-bias pp | verdict margin (mean) | corr(verdict,boolean) | boolean inverted |")
    w("|---|---|---|---|---|---|---|---|---|---|---|---|")
    for r in res:
        c, nn = r["acc_all"]
        def sa(s):
            cc, n2 = r["acc_stage"][s]
            return fmt(pct(cc, n2), 1)
        w("| %s | %s | %s | %s | %s | %s | %s | %s | %s | %s | %s | %s |" % (
            r["name"], r["judge"], fmt(pct(c, nn), 1),
            sa(STAGES[0]), sa(STAGES[1]), sa(STAGES[2]),
            fmt(r["pred_yes_pct"], 1), fmt(r["true_yes_pct"], 1), fmt(r["yes_bias"], 1),
            fmt(r["verdict_margin_mean"]), fmt(r["corr_verdict_boolean"]),
            "YES" if r["boolean_inverted"] else "no"))
    w("")

    # ---- Q1 framing detail ------------------------------------------ #
    w("## Q1. Judge decision log-probs across framings\n")
    w("verdict margin = logprob(Yes)-logprob(No); boolean margin = logprob(true)-logprob(false); "
      "debater margin = logprob(A)-logprob(B). P(A right) present only for statement/interactive.\n")
    w("| dataset | n_conf | P(belongs) | P(true) | P(A right) | verdict margin | boolean margin | debater margin | margin when CORRECT | margin when WRONG |")
    w("|---|---|---|---|---|---|---|---|---|---|")
    for r in res:
        w("| %s | %d | %s | %s | %s | %s | %s | %s | %s | %s |" % (
            r["name"], r["n_conf"], fmt(r["p_belongs_mean"]), fmt(r["p_true_mean"]),
            fmt(r["p_a_right_mean"]), fmt(r["verdict_margin_mean"]),
            fmt(r["boolean_margin_mean"]), fmt(r["debater_margin_mean"]),
            fmt(r["vm_correct_mean"]), fmt(r["vm_wrong_mean"])))
    w("\nP(A right) > 0.5 across the board => positional bias toward debater A (first speaker).\n")

    # ---- Q2 order effect -------------------------------------------- #
    w("## Q2. ABA vs BAB (interactive order effect)\n")
    if q2:
        w("| dataset | n | acc ABA % | acc BAB % | order-flip % | flips Yes->No | flips No->Yes | mean P(A right) ABA | mean P(A right) BAB |")
        w("|---|---|---|---|---|---|---|---|---|")
        for name, d in q2.items():
            w("| %s | %d | %s | %s | %s | %d | %d | %s | %s |" % (
                name, d["n"], fmt(d["acc_ABA"], 1), fmt(d["acc_BAB"], 1),
                fmt(d["flip_pct"], 1), d["flip_Yes->No"], d["flip_No->Yes"],
                fmt(d["mean_P_A_right_ABA"]), fmt(d["mean_P_A_right_BAB"])))
    else:
        w("No interactive datasets found.")
    w("")

    # ---- Q4 2B vs 0.8B ---------------------------------------------- #
    w("## Q4. Larger 2B judge vs 0.8B judge (SHARED subset only)\n")
    if q4:
        w("| comparison | shared (stage,pmid) | acc 0.8B % | acc 2B % | delta pp |")
        w("|---|---|---|---|---|")
        for label, d in q4.items():
            if d:
                w("| %s | %d | %s | %s | %s |" % (
                    label, d["shared_keys"], fmt(d["acc_0.8B"], 2),
                    fmt(d["acc_2B"], 2), fmt(d["delta_pp"], 2)))
            else:
                w("| %s | 0 | - | - | no overlap |" % label)
        w("\nComparison is restricted to records the 2B rejudge actually covered, "
          "so it is apples-to-apples despite the rejudge files being partial.\n")
    else:
        w("No rejudge2B datasets found.")
    w("")

    # ---- integrity -------------------------------------------------- #
    w("## is_correct cross-check (data integrity)\n")
    w("| dataset | recomputed-vs-stored mismatches |")
    w("|---|---|")
    for r in res:
        w("| %s | %d |" % (r["name"], r["is_correct_mismatches"]))
    w("")
    return "\n".join(L)


def strip_records(res):
    out = []
    for r in res:
        d = dict(r)
        d.pop("_records", None)
        out.append(d)
    return out


def safe_out_path(base):
    p = os.path.join(SCAN_DIR, base)
    if os.path.exists(p):
        stamp = time.strftime("%Y%m%d_%H%M%S")
        root, ext = os.path.splitext(base)
        p = os.path.join(SCAN_DIR, "%s_%s%s" % (root, stamp, ext))
    return p


def main():
    global SCAN_DIR
    SCAN_DIR = os.path.abspath(
        sys.argv[1] if len(sys.argv) > 1
        else os.environ.get("DEBATE_DIR", os.getcwd()))
    print("Scanning (read-only): %s\n" % SCAN_DIR)

    res = []
    by_name = {}
    for name, fname, dtype, backend, has_ab, expected, judge in DATASETS:
        path = os.path.join(SCAN_DIR, fname)
        if not os.path.isfile(path):
            print("[skip] %-22s %s not found" % (name, fname))
            continue
        try:
            records, meta = load_records(path)
        except Exception as e:
            print("[warn] %-22s could not read (%s)" % (name, e))
            continue
        r = analyze(name, records, meta, (dtype, backend, has_ab, expected, judge))
        res.append(r)
        by_name[name] = r
        print("[ok] %-22s records=%d parsed=%d dropped=%d %s" % (
            name, r["n_records"], r["parsed"], r["dropped"],
            "COMPLETE" if r["complete"] else "** PARTIAL **"))

    if not res:
        print("No datasets found.")
        sys.exit(1)

    # Q2
    q2 = {}
    for name in ("interactive", "interactive_rejudge2B", "pydantic_interactive"):
        if name in by_name:
            q2[name] = q2_order_effect(by_name[name]["_records"])

    # Q4
    q4 = {}
    if "statement" in by_name and "statement_rejudge2B" in by_name:
        q4["statement: 0.8B vs 2B"] = q4_subset_compare(
            correctness_map_single(by_name["statement"]["_records"]),
            correctness_map_single(by_name["statement_rejudge2B"]["_records"]))
    if "interactive" in by_name and "interactive_rejudge2B" in by_name:
        q4["interactive: 0.8B vs 2B"] = q4_subset_compare(
            correctness_map_dual(by_name["interactive"]["_records"]),
            correctness_map_dual(by_name["interactive_rejudge2B"]["_records"]))

    md = build_report(res, q2, q4)
    md_path = safe_out_path("debate_qa_report.md")
    json_path = safe_out_path("debate_qa_report.json")
    with open(md_path, "w", encoding="utf-8") as fh:
        fh.write(md)
    with open(json_path, "w", encoding="utf-8") as fh:
        json.dump({"datasets": strip_records(res), "q2": q2, "q4": q4},
                  fh, indent=2, default=str)

    print("\nWrote:\n  %s\n  %s" % (md_path, json_path))
    print("\n(No result files were modified.)")


if __name__ == "__main__":
    main()
