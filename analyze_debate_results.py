#!/usr/bin/env python3
"""
AI-Debate XMLC - results analyzer (v2, read-only).

Changes vs v1 (requested):
  1) PARSED-ONLY: every metric is computed only on records whose judge output
     could be parsed into a valid verdict {Yes, No}. Un-parsable / "Unknown" /
     null / fallback-with-no-verdict records are DROPPED, and the number of
     dropped records is printed per dataset (and per stage).
  2) CONFIDENCE ANOMALY: auto-detects the with-manual boolean-framing inversion
     (verdict vs boolean log-prob anti-correlation) and reports an
     orientation-corrected agreement next to the raw one. Root cause + real fix
     are in the README; this only makes the reported numbers honest.
  3) YES-BIAS: per dataset and per stage, reports predicted-Yes rate vs true-Yes
     rate, the bias delta, and the directional error split (false-Yes / false-No).

This script never writes to the dataset files. It only reads *_full*.json and
writes a fresh report (debate_analysis_report_v2.{md,json}).
"""

import json
import math
import os
import sys
from collections import defaultdict

# --------------------------------------------------------------------------- #
# CONFIG
# --------------------------------------------------------------------------- #
SCAN_DIR = os.environ.get("DEBATE_DIR", "/home/s27erahn/NLP_LabSS26")

# logical dataset name -> filename
DATASETS = {
    "baseline_withmanual":    "baseline_withmanual_results_full.json",
    "baseline_nomanual":      "baseline_nomanual_results_full.json",
    "statement":              "statement_results_full.json",
    "statement_rejudge2B":    "statement_results_full_rejudge2B.json",
    "interactive":            "interactive_results_full.json",
    "interactive_rejudge2B":  "interactive_results_full_rejudge2B.json",
    "pydantic_interactive":   "pydantic_interactive_results_full.json",
}

# Ground-truth answer per stage: Round 1 (a real, withheld tag) -> Yes belongs.
# Rounds 2/3 (unrelated / similar-but-wrong tag) -> No, does not belong.
STAGE_TRUE_LABEL = {
    "Round 1: True Tag":      "Yes",
    "Round 2: Unrelated Tag": "No",
    "Round 3: Similar Tag":   "No",
}

VALID_VERDICTS = {"Yes", "No"}

# Candidate key names (schemas drifted across scripts, so we search a few).
PRED_KEYS   = ["prediction", "verdict", "judge_verdict", "answer", "final_verdict"]
CORRECT_KEYS = ["is_correct", "correct"]
STAGE_KEYS  = ["stage", "round", "stage_name"]
PMID_KEYS   = ["pmid", "pmID", "pm_id", "id"]
FALLBACK_KEYS = ["needed_fallback", "used_fallback", "fallback"]

CONF_ALIASES = {
    "verdict_prob_belongs": ["verdict_prob_belongs", "prob_belongs", "verdict_prob_yes", "p_belongs"],
    "boolean_prob_true":    ["boolean_prob_true", "prob_true", "p_true"],
    "debater_prob_A_right": ["debater_prob_A_right", "prob_A_right", "p_A_right"],
    "logprob_yes":          ["verdict_logprob_yes", "logprob_yes", "lp_yes"],
    "logprob_no":           ["verdict_logprob_no", "logprob_no", "lp_no"],
}

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


def get_conf(container, logical_name):
    """Look for a confidence value in the record itself or a nested 'confidence' dict."""
    aliases = CONF_ALIASES[logical_name]
    for scope in (container, (container or {}).get("confidence", {})):
        v = first_key(scope, aliases, None)
        if isinstance(v, (int, float)):
            return float(v)
    return None


def norm_pred(raw):
    """Normalize a raw prediction into 'Yes' / 'No' / None (None = unparsable)."""
    if raw is None:
        return None
    s = str(raw).strip().lower()
    if s in ("yes", "y", "true", "belongs", "1"):
        return "Yes"
    if s in ("no", "n", "false", "not", "does not belong", "0"):
        return "No"
    return None  # 'unknown', '', garbage, etc.


def norm_stage(raw):
    if raw is None:
        return "UNKNOWN_STAGE"
    s = str(raw)
    for canon in STAGE_TRUE_LABEL:
        if canon.lower() in s.lower():
            return canon
    low = s.lower()
    if "true" in low or "round 1" in low or "round1" in low:
        return "Round 1: True Tag"
    if "unrelated" in low or "round 2" in low or "round2" in low:
        return "Round 2: Unrelated Tag"
    if "similar" in low or "round 3" in low or "round3" in low:
        return "Round 3: Similar Tag"
    return s


def pearson(xs, ys):
    n = len(xs)
    if n < 3:
        return None
    mx = sum(xs) / n
    my = sum(ys) / n
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    dx = math.sqrt(sum((x - mx) ** 2 for x in xs))
    dy = math.sqrt(sum((y - my) ** 2 for y in ys))
    if dx == 0 or dy == 0:
        return None
    return num / (dx * dy)


def pct(a, b):
    return (100.0 * a / b) if b else 0.0


# --------------------------------------------------------------------------- #
# view extraction: flatten each record into 0+ "views" that each carry one
# verdict. Interactive rejudge2B records carry judge_ABA / judge_BAB; those
# become two views. Everything else is a single view.
# --------------------------------------------------------------------------- #
def record_to_views(rec):
    stage = norm_stage(first_key(rec, STAGE_KEYS))
    pmid = first_key(rec, PMID_KEYS)
    fallback = bool(first_key(rec, FALLBACK_KEYS, False))

    views = []
    has_sub = any(k in rec for k in ("judge_ABA", "judge_BAB"))
    if has_sub:
        for order, subkey in (("ABA", "judge_ABA"), ("BAB", "judge_BAB")):
            sub = rec.get(subkey)
            if not isinstance(sub, dict):
                continue
            views.append({
                "stage": stage, "pmid": pmid, "order": order, "fallback": fallback,
                "pred": norm_pred(first_key(sub, PRED_KEYS, first_key(rec, PRED_KEYS))),
                "container": sub,
            })
    else:
        views.append({
            "stage": stage, "pmid": pmid, "order": None, "fallback": fallback,
            "pred": norm_pred(first_key(rec, PRED_KEYS)),
            "container": rec,
        })
    return views


def true_label_for(stage):
    return STAGE_TRUE_LABEL.get(stage)


def is_correct_view(v):
    tl = true_label_for(v["stage"])
    if tl is not None and v["pred"] is not None:
        return v["pred"] == tl
    # fall back to a recorded is_correct flag if we can't derive ground truth
    flag = first_key(v["container"], CORRECT_KEYS)
    return bool(flag) if flag is not None else None


# --------------------------------------------------------------------------- #
# analysis
# --------------------------------------------------------------------------- #
def analyze_dataset(name, records):
    all_views = []
    for rec in records:
        all_views.extend(record_to_views(rec))

    total_views = len(all_views)

    # (1) drop unparsable views
    dropped = [v for v in all_views if v["pred"] not in VALID_VERDICTS]
    parsed = [v for v in all_views if v["pred"] in VALID_VERDICTS]

    dropped_by_stage = defaultdict(int)
    for v in dropped:
        dropped_by_stage[v["stage"]] += 1

    # accuracy (parsed only), overall + per stage
    acc = {"ALL": [0, 0]}  # stage -> [correct, n]
    verdict_counts = defaultdict(int)
    for v in parsed:
        c = is_correct_view(v)
        st = v["stage"]
        acc.setdefault(st, [0, 0])
        if c is not None:
            acc["ALL"][1] += 1
            acc[st][1] += 1
            if c:
                acc["ALL"][0] += 1
                acc[st][0] += 1
        verdict_counts[v["pred"]] += 1

    # (3) yes-bias, overall + per stage
    bias = {}
    for st in ["ALL"] + list(STAGE_TRUE_LABEL):
        sub = parsed if st == "ALL" else [v for v in parsed if v["stage"] == st]
        n = len(sub)
        if n == 0:
            continue
        pred_yes = sum(1 for v in sub if v["pred"] == "Yes")
        if st == "ALL":
            # weighted true-yes rate across stages present
            true_yes = sum(1 for v in sub if true_label_for(v["stage"]) == "Yes")
        else:
            true_yes = sum(1 for v in sub if true_label_for(st) == "Yes")
        # directional errors
        false_yes = sum(1 for v in sub
                        if v["pred"] == "Yes" and true_label_for(v["stage"]) == "No")
        false_no = sum(1 for v in sub
                       if v["pred"] == "No" and true_label_for(v["stage"]) == "Yes")
        bias[st] = {
            "n": n,
            "pred_yes_rate": pct(pred_yes, n),
            "true_yes_rate": pct(true_yes, n),
            "yes_bias_delta": pct(pred_yes, n) - pct(true_yes, n),
            "false_yes_rate": pct(false_yes, n),
            "false_no_rate": pct(false_no, n),
        }

    # (2) confidence framings + inversion detection (parsed only)
    vb, bt = [], []
    for v in parsed:
        a = get_conf(v["container"], "verdict_prob_belongs")
        b = get_conf(v["container"], "boolean_prob_true")
        if a is not None and b is not None:
            vb.append(a)
            bt.append(b)
    corr = pearson(vb, bt) if vb else None
    inverted = (corr is not None and corr < -0.15)

    def agree_rate(correct_orientation):
        if not vb:
            return None
        agree = 0
        for a, b in zip(vb, bt):
            bb = (1.0 - b) if correct_orientation and inverted else b
            if (a >= 0.5) == (bb >= 0.5):
                agree += 1
        return pct(agree, len(vb))

    conf = {
        "n_conf": len(vb),
        "mean_P_belongs": (sum(vb) / len(vb)) if vb else None,
        "mean_P_true_raw": (sum(bt) / len(bt)) if bt else None,
        "verdict_boolean_corr": corr,
        "inverted_flag": inverted,
        "agree_raw_pct": agree_rate(False),
        "agree_corrected_pct": agree_rate(True) if inverted else agree_rate(False),
    }

    return {
        "total_views": total_views,
        "dropped": len(dropped),
        "dropped_by_stage": dict(dropped_by_stage),
        "parsed": len(parsed),
        "acc": acc,
        "verdict_counts": dict(verdict_counts),
        "bias": bias,
        "conf": conf,
    }


# --------------------------------------------------------------------------- #
# reporting
# --------------------------------------------------------------------------- #
def build_report(results):
    L = []
    w = L.append
    w("# AI-Debate XMLC - analysis report (v2)\n")
    w(f"Directory scanned: `{SCAN_DIR}`\n")

    # ---- Section: parsed vs dropped -------------------------------------- #
    w("## Parse filter (un-parsable / Unknown judge outputs DROPPED)\n")
    w("| dataset | total views | parsed (kept) | dropped | dropped % |")
    w("|---|---|---|---|---|")
    for name, r in results.items():
        w(f"| {name} | {r['total_views']} | {r['parsed']} | "
          f"{r['dropped']} | {pct(r['dropped'], r['total_views']):.2f} |")
    w("")
    w("Dropped-by-stage detail:\n")
    for name, r in results.items():
        if r["dropped"]:
            detail = ", ".join(f"{k}: {v}" for k, v in sorted(r["dropped_by_stage"].items()))
            w(f"- **{name}**: {r['dropped']} dropped ({detail})")
    w("")

    # ---- Section: accuracy (parsed only) --------------------------------- #
    w("## Accuracy on PARSED-ONLY views (overall + per stage)\n")
    for name, r in results.items():
        w(f"### {name}\n")
        w("| scope | n | correct | accuracy % |")
        w("|---|---|---|---|")
        for st in ["ALL"] + list(STAGE_TRUE_LABEL):
            if st in r["acc"]:
                c, n = r["acc"][st]
                w(f"| {st} | {n} | {c} | {pct(c, n):.2f} |")
        w(f"\nVerdict counts (parsed): {json.dumps(r['verdict_counts'])}\n")

    # ---- Section: Yes-bias ----------------------------------------------- #
    w("## Yes-bias (predicted-Yes rate vs true-Yes rate)\n")
    w("Positive `yes_bias_delta` = judge says 'belongs' more often than truth warrants.\n")
    for name, r in results.items():
        w(f"### {name}\n")
        w("| scope | n | pred Yes % | true Yes % | bias delta | false-Yes % | false-No % |")
        w("|---|---|---|---|---|---|---|")
        for st in ["ALL"] + list(STAGE_TRUE_LABEL):
            if st in r["bias"]:
                b = r["bias"][st]
                w(f"| {st} | {b['n']} | {b['pred_yes_rate']:.2f} | {b['true_yes_rate']:.2f} | "
                  f"{b['yes_bias_delta']:+.2f} | {b['false_yes_rate']:.2f} | {b['false_no_rate']:.2f} |")
        w("")

    # ---- Section: confidence anomaly ------------------------------------- #
    w("## Confidence framing consistency + inversion check\n")
    w("`corr` = Pearson(verdict_prob_belongs, boolean_prob_true). Strongly negative "
      "=> boolean framing is INVERTED (log-prob extraction bug; see README). "
      "`agree_corrected` re-orients the boolean framing so you can read the true agreement now.\n")
    w("| dataset | n conf | mean P(belongs) | mean P(true) raw | corr | inverted? | agree raw % | agree corrected % |")
    w("|---|---|---|---|---|---|---|---|")
    for name, r in results.items():
        c = r["conf"]
        def f(x, nd=3):
            return f"{x:.{nd}f}" if isinstance(x, float) else "-"
        w(f"| {name} | {c['n_conf']} | {f(c['mean_P_belongs'])} | {f(c['mean_P_true_raw'])} | "
          f"{f(c['verdict_boolean_corr'])} | {'YES' if c['inverted_flag'] else 'no'} | "
          f"{f(c['agree_raw_pct'],2)} | {f(c['agree_corrected_pct'],2)} |")
    w("")
    return "\n".join(L)


def main():
    results = {}
    print(f"Scanning: {SCAN_DIR}\n")
    for name, fname in DATASETS.items():
        path = os.path.join(SCAN_DIR, fname)
        if not os.path.isfile(path):
            print(f"[skip] {name}: {fname} not found")
            continue
        try:
            with open(path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
        except Exception as e:
            print(f"[warn] {name}: could not read ({e})")
            continue
        if isinstance(data, dict):
            data = data.get("results", data.get("records", list(data.values())))
        if not isinstance(data, list):
            print(f"[warn] {name}: unexpected structure, skipping")
            continue
        r = analyze_dataset(name, data)
        results[name] = r
        print(f"[ok] {name}: {r['parsed']} parsed / {r['total_views']} views "
              f"({r['dropped']} DROPPED as unparsable)")

    if not results:
        print("No datasets analyzed.")
        sys.exit(1)

    md = build_report(results)
    with open(os.path.join(SCAN_DIR, "debate_analysis_report_v2.md"), "w", encoding="utf-8") as fh:
        fh.write(md)
    with open(os.path.join(SCAN_DIR, "debate_analysis_report_v2.json"), "w", encoding="utf-8") as fh:
        json.dump(results, fh, indent=2)

    print("\nWrote debate_analysis_report_v2.md and .json")
    print("\n--- DROP SUMMARY ---")
    for name, r in results.items():
        print(f"{name:24s} dropped {r['dropped']:5d} / {r['total_views']:5d} "
              f"({pct(r['dropped'], r['total_views']):.2f}%)")


if __name__ == "__main__":
    main()
