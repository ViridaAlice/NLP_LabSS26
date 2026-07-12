#!/usr/bin/env python3
"""
analyze_debate_results.py  --  STRICTLY READ-ONLY analysis of the AI-Debate XMLC results.

It NEVER runs a model, NEVER launches SLURM, and NEVER overwrites any result
file. It only *reads* the merged *_full*.json files and writes two brand-new
outputs:

    debate_analysis_report.md    (human-readable)
    debate_analysis_report.json  (machine-readable, same numbers)

If either output already exists it is written with a numeric suffix instead of
being clobbered, so nothing you produced is ever at risk.

Questions answered (see README.md for the mapping):
    Q1  log-prob framings (Yes/No, true/false, A/B) - is the judge informative?
    Q2  ABA vs BAB verdicts in the interactive round (order effects)
    Q3  any 'Unknown'/unforced outputs left anywhere
    Q4  does the larger 2B judge beat the 0.8B judge (matched pairs)
    Q5  input-richness ladder: baseline -> statement -> interactive
    Q6  baseline WITH manual vs WITHOUT manual (matched pairs)

Usage:
    python3 analyze_debate_results.py [directory]     # default: current dir
"""

import os
import sys
import json
import math
from collections import defaultdict


# --------------------------------------------------------------------------- #
# File registry. Each logical dataset can have several candidate filenames
# (naming drifted between _rejudge and _rejudge2B) - the first that exists wins.
# --------------------------------------------------------------------------- #
FILE_CANDIDATES = {
    "baseline_withmanual":    ["baseline_withmanual_results_full.json"],
    "baseline_nomanual":      ["baseline_nomanual_results_full.json"],
    "statement":              ["statement_results_full.json"],
    "statement_rejudge2B":    ["statement_results_full_rejudge2B.json",
                               "statement_results_full_rejudge.json"],
    "interactive":            ["interactive_results_full.json"],
    "interactive_rejudge2B":  ["interactive_results_full_rejudge2B.json"],
    "pydantic_interactive":   ["pydantic_interactive_results_full.json"],
}

STAGES = ["Round 1: True Tag", "Round 2: Unrelated Tag", "Round 3: Similar Tag"]
VALID_VERDICTS = {"Yes", "No"}


# --------------------------------------------------------------------------- #
# Safe loading / output naming
# --------------------------------------------------------------------------- #
def find_file(directory, key):
    for name in FILE_CANDIDATES[key]:
        p = os.path.join(directory, name)
        if os.path.exists(p):
            return p
    return None


def load_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f), None
    except (json.JSONDecodeError, OSError) as e:
        return None, str(e)


def safe_out_path(directory, filename):
    """Never overwrite: append _1, _2 ... if the target already exists."""
    base, ext = os.path.splitext(filename)
    cand = os.path.join(directory, filename)
    i = 1
    while os.path.exists(cand):
        cand = os.path.join(directory, "%s_%d%s" % (base, i, ext))
        i += 1
    return cand


# --------------------------------------------------------------------------- #
# View extraction: normalise every record into 0..2 comparable 'views'.
# A view = one judge decision with optional confidence.
# --------------------------------------------------------------------------- #
def verdict_is_correct(pred, gt, rec_correct):
    if isinstance(rec_correct, bool):
        return rec_correct
    if pred is None or gt is None:
        return None
    return pred == gt


def iter_views(records):
    """Yield dicts: {order, stage, pmid, gt, pred, correct, conf, fallback}."""
    for r in records:
        stage = r.get("stage")
        pmid = str(r.get("pmid"))
        gt = r.get("ground_truth")

        if "judge_ABA" in r or "judge_BAB" in r:            # interactive-style
            for order in ("ABA", "BAB"):
                j = r.get("judge_%s" % order)
                if not j:
                    continue
                pred = j.get("prediction")
                yield {
                    "order": order, "stage": stage, "pmid": pmid, "gt": gt,
                    "pred": pred,
                    "correct": verdict_is_correct(pred, gt, j.get("is_correct")),
                    "conf": j.get("confidence") or {},
                    "fallback": bool(j.get("needed_fallback")),
                }
        elif "model_prediction" in r:                       # pydantic prior
            pred = r.get("model_prediction")
            yield {
                "order": "single", "stage": stage, "pmid": pmid, "gt": gt,
                "pred": pred,
                "correct": verdict_is_correct(pred, gt, r.get("is_correct")),
                "conf": r.get("confidence") or {},
                "fallback": bool(r.get("needed_fallback")),
            }
        else:                                               # baseline / statement
            pred = r.get("prediction")
            yield {
                "order": "single", "stage": stage, "pmid": pmid, "gt": gt,
                "pred": pred,
                "correct": verdict_is_correct(pred, gt, r.get("is_correct")),
                "conf": r.get("confidence") or {},
                "fallback": bool(r.get("needed_fallback")),
            }


def mean(xs):
    xs = [x for x in xs if x is not None]
    return sum(xs) / len(xs) if xs else None


def pct(n, d):
    return 100.0 * n / d if d else None


# --------------------------------------------------------------------------- #
# Aggregations
# --------------------------------------------------------------------------- #
def accuracy_by_stage(views):
    """Return {stage_or_ALL: (n, n_correct, acc)} for views with a known label."""
    tot = defaultdict(int)
    cor = defaultdict(int)
    for v in views:
        if v["correct"] is None:
            continue
        tot["ALL"] += 1
        cor["ALL"] += 1 if v["correct"] else 0
        tot[v["stage"]] += 1
        cor[v["stage"]] += 1 if v["correct"] else 0
    out = {}
    for k in ["ALL"] + STAGES:
        if tot[k]:
            out[k] = (tot[k], cor[k], pct(cor[k], tot[k]))
    return out


def verdict_bias(views):
    """How often does the judge say Yes vs No overall?"""
    c = defaultdict(int)
    for v in views:
        c[v["pred"]] += 1
    return dict(c)


def confidence_summary(views):
    """Aggregate the three log-prob framings and their agreement (Q1)."""
    yes_no_margin, prob_belongs, prob_true, prob_A = [], [], [], []
    has_debater = 0
    agree_verdict_bool = 0
    agree_denom = 0
    for v in views:
        c = v["conf"]
        vl = c.get("verdict_logprob")
        if isinstance(vl, dict) and "Yes" in vl and "No" in vl:
            yes_no_margin.append(vl["Yes"] - vl["No"])
        pb = c.get("verdict_prob_belongs")
        pt = c.get("boolean_prob_true")
        if pb is not None:
            prob_belongs.append(pb)
        if pt is not None:
            prob_true.append(pt)
        if pb is not None and pt is not None:
            agree_denom += 1
            if (pb >= 0.5) == (pt >= 0.5):
                agree_verdict_bool += 1
        pa = c.get("debater_prob_A_right")
        if pa is not None:
            prob_A.append(pa)
            has_debater += 1
    return {
        "n_with_confidence": sum(1 for v in views if v["conf"]),
        "mean_verdict_logprob_margin_Yes_minus_No": mean(yes_no_margin),
        "mean_prob_belongs(Yes)": mean(prob_belongs),
        "mean_boolean_prob_true": mean(prob_true),
        "mean_debater_prob_A_right": mean(prob_A),
        "n_with_debater_framing": has_debater,
        "verdict_vs_boolean_agreement_pct": pct(agree_verdict_bool, agree_denom),
    }


def unknown_scan(views):
    """Q3: any prediction outside {Yes,No}, plus fallback usage."""
    bad = defaultdict(int)
    fb = 0
    n = 0
    for v in views:
        n += 1
        if v["pred"] not in VALID_VERDICTS:
            bad[repr(v["pred"])] += 1
        if v["fallback"]:
            fb += 1
    return {"n_views": n, "n_fallback": fb,
            "invalid_predictions": dict(bad)}


def matched_pairs(views_a, views_b):
    """Match on (order, stage, pmid); return McNemar-style table."""
    da = {(v["order"], v["stage"], v["pmid"]): v for v in views_a}
    db = {(v["order"], v["stage"], v["pmid"]): v for v in views_b}
    keys = set(da) & set(db)
    both_ok = a_ok = b_ok = both_bad = 0
    flips = 0
    for k in keys:
        ca, cb = da[k]["correct"], db[k]["correct"]
        if ca is None or cb is None:
            continue
        if da[k]["pred"] != db[k]["pred"]:
            flips += 1
        if ca and cb:
            both_ok += 1
        elif ca and not cb:
            a_ok += 1
        elif cb and not ca:
            b_ok += 1
        else:
            both_bad += 1
    n = both_ok + a_ok + b_ok + both_bad
    return {
        "n_matched": len(keys), "n_scored": n,
        "both_correct": both_ok,
        "only_A_correct": a_ok, "only_B_correct": b_ok,
        "both_wrong": both_bad,
        "acc_A_pct": pct(both_ok + a_ok, n),
        "acc_B_pct": pct(both_ok + b_ok, n),
        "prediction_flip_pct": pct(flips, n),
    }


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #
def main():
    directory = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else os.getcwd())
    md = []
    R = {}   # machine-readable report

    def line(s=""):
        md.append(s)

    line("# AI-Debate XMLC - analysis report")
    line("")
    line("Directory scanned: `%s`" % directory)
    line("")

    # ---- Load everything we can, purely read-only ----
    loaded = {}
    present, missing = [], []
    for key in FILE_CANDIDATES:
        path = find_file(directory, key)
        if path is None:
            missing.append(key)
            continue
        data, err = load_json(path)
        if err:
            line("> WARNING: %s could not be parsed (%s) - skipped." %
                 (os.path.basename(path), err))
            missing.append(key)
            continue
        recs = data.get("results", [])
        loaded[key] = {"path": path, "meta": data.get("metadata", {}),
                       "records": recs, "views": list(iter_views(recs))}
        present.append(key)

    # ---- Inventory / current state ----
    line("## Current state / inventory")
    line("")
    line("| dataset | file | records | metadata acc |")
    line("|---|---|---|---|")
    for key in FILE_CANDIDATES:
        if key in loaded:
            m = loaded[key]["meta"]
            acc = m.get("overall_accuracy", m.get("accuracy_ABA", "-"))
            line("| %s | `%s` | %d | %s |" %
                 (key, os.path.basename(loaded[key]["path"]),
                  len(loaded[key]["records"]), acc))
        else:
            line("| %s | MISSING | - | - |" % key)
    line("")
    R["inventory"] = {"present": present, "missing": missing}

    # ---- Per-dataset core stats (accuracy by stage, verdict bias) ----
    line("## Per-dataset accuracy (overall + per stage) and Yes/No bias")
    line("")
    R["per_dataset"] = {}
    for key in present:
        views = loaded[key]["views"]
        acc = accuracy_by_stage(views)
        bias = verdict_bias(views)
        R["per_dataset"][key] = {"accuracy": acc, "verdict_bias": bias}
        line("### %s" % key)
        line("")
        line("| scope | n | correct | accuracy % |")
        line("|---|---|---|---|")
        for scope, (n, cor, a) in acc.items():
            line("| %s | %d | %d | %.2f |" % (scope, n, cor, a))
        line("")
        line("Verdict counts: %s" % json.dumps(bias))
        line("")

    # ---- Q1: log-prob framings ----
    line("## Q1 - Log-probability framings (Yes/No, true/false, A/B)")
    line("")
    line("| dataset | n conf | mean margin (logP Yes-No) | mean P(belongs) | "
         "mean P(true) | mean P(A right) | verdict/boolean agree % |")
    line("|---|---|---|---|---|---|---|")
    R["Q1_confidence"] = {}
    for key in present:
        cs = confidence_summary(loaded[key]["views"])
        R["Q1_confidence"][key] = cs
        def f(x):
            return "%.3f" % x if isinstance(x, float) else ("-" if x is None else str(x))
        line("| %s | %d | %s | %s | %s | %s | %s |" % (
            key, cs["n_with_confidence"],
            f(cs["mean_verdict_logprob_margin_Yes_minus_No"]),
            f(cs["mean_prob_belongs(Yes)"]),
            f(cs["mean_boolean_prob_true"]),
            f(cs["mean_debater_prob_A_right"]),
            f(cs["verdict_vs_boolean_agreement_pct"])))
    line("")
    line("*Interpretation hints:* a mean |margin| near 0 and P(belongs)~0.5 means "
         "the judge is barely distinguishing Yes from No (log-probs uninformative). "
         "A `mean P(A right)` far from 0.5 that is stable across ABA/BAB indicates "
         "a position/letter bias rather than genuine argument evaluation.")
    line("")

    # ---- Q2: ABA vs BAB ----
    line("## Q2 - Interactive round: ABA vs BAB")
    line("")
    R["Q2_order"] = {}
    for key in ("interactive", "interactive_rejudge2B"):
        if key not in loaded:
            continue
        views = loaded[key]["views"]
        aba = [v for v in views if v["order"] == "ABA"]
        bab = [v for v in views if v["order"] == "BAB"]
        # pair ABA vs BAB by (stage,pmid)
        aba_k = {(v["stage"], v["pmid"]): v for v in aba}
        bab_k = {(v["stage"], v["pmid"]): v for v in bab}
        keys = set(aba_k) & set(bab_k)
        flip = both_ok = only_aba = only_bab = both_bad = 0
        for k in keys:
            a, b = aba_k[k], bab_k[k]
            if a["pred"] != b["pred"]:
                flip += 1
            ca, cb = a["correct"], b["correct"]
            if ca and cb: both_ok += 1
            elif ca and not cb: only_aba += 1
            elif cb and not ca: only_bab += 1
            elif ca is not None and cb is not None: both_bad += 1
        n = both_ok + only_aba + only_bab + both_bad
        rec = {
            "acc_ABA_pct": accuracy_by_stage(aba).get("ALL", (0, 0, None))[2],
            "acc_BAB_pct": accuracy_by_stage(bab).get("ALL", (0, 0, None))[2],
            "order_flip_pct": pct(flip, len(keys)),
            "both_correct": both_ok, "only_ABA_correct": only_aba,
            "only_BAB_correct": only_bab, "both_wrong": both_bad,
            "metadata_order_flip_rate": loaded[key]["meta"].get("order_flip_rate"),
        }
        R["Q2_order"][key] = rec
        line("### %s" % key)
        line("")
        line("| metric | value |")
        line("|---|---|")
        for kk, vv in rec.items():
            line("| %s | %s |" % (kk, ("%.2f" % vv) if isinstance(vv, float) else vv))
        line("")

    # ---- Q3: unknown / unforced ----
    line("## Q3 - Unknown / unforced outputs and fallback usage")
    line("")
    line("| dataset | views | fallback used | invalid predictions |")
    line("|---|---|---|---|")
    R["Q3_unknown"] = {}
    for key in present:
        u = unknown_scan(loaded[key]["views"])
        R["Q3_unknown"][key] = u
        line("| %s | %d | %d | %s |" % (
            key, u["n_views"], u["n_fallback"],
            json.dumps(u["invalid_predictions"]) if u["invalid_predictions"] else "none"))
    line("")

    # ---- Q4: 2B vs 0.8B ----
    line("## Q4 - Larger 2B judge vs 0.8B judge (matched pairs)")
    line("")
    R["Q4_judge_size"] = {}
    for small, big, label in [("interactive", "interactive_rejudge2B", "interactive"),
                              ("statement", "statement_rejudge2B", "statement")]:
        if small in loaded and big in loaded:
            mp = matched_pairs(loaded[small]["views"], loaded[big]["views"])
            R["Q4_judge_size"][label] = mp
            line("### %s  (A = 0.8B `%s`, B = 2B `%s`)" % (
                label, os.path.basename(loaded[small]["path"]),
                os.path.basename(loaded[big]["path"])))
            line("")
            line("| metric | value |")
            line("|---|---|")
            for kk, vv in mp.items():
                line("| %s | %s |" % (kk, ("%.2f" % vv) if isinstance(vv, float) else vv))
            line("")
        else:
            line("- %s: cannot compare (missing %s)." %
                 (label, small if small not in loaded else big))
            line("")

    # ---- Q5: input-richness ladder (same 0.8B judge) ----
    line("## Q5 - Does more input help? baseline -> statement -> interactive")
    line("")
    line("Fair comparison uses the 0.8B judge in every rung. Interactive is shown "
         "as ABA (regenerated verdict). Baselines carry no A/B framing.")
    line("")
    ladder = []
    if "baseline_nomanual" in loaded:
        ladder.append(("baseline_nomanual (judge only)", loaded["baseline_nomanual"]["views"]))
    if "baseline_withmanual" in loaded:
        ladder.append(("baseline_withmanual (judge+manual)", loaded["baseline_withmanual"]["views"]))
    if "statement" in loaded:
        ladder.append(("statement (2 essays)", loaded["statement"]["views"]))
    if "interactive" in loaded:
        ladder.append(("interactive ABA (3-turn)",
                       [v for v in loaded["interactive"]["views"] if v["order"] == "ABA"]))
    line("| rung | n | accuracy % | mean P(belongs) |")
    line("|---|---|---|---|")
    R["Q5_ladder"] = []
    for name, views in ladder:
        acc = accuracy_by_stage(views).get("ALL", (0, 0, None))
        cs = confidence_summary(views)
        pb = cs["mean_prob_belongs(Yes)"]
        R["Q5_ladder"].append({"rung": name, "n": acc[0], "accuracy_pct": acc[2],
                               "mean_prob_belongs": pb})
        line("| %s | %d | %s | %s |" % (
            name, acc[0],
            "%.2f" % acc[2] if acc[2] is not None else "-",
            "%.3f" % pb if pb is not None else "-"))
    line("")

    # ---- Q6: manual vs no manual ----
    line("## Q6 - Baseline WITH manual vs WITHOUT manual (matched pairs)")
    line("")
    if "baseline_withmanual" in loaded and "baseline_nomanual" in loaded:
        mp = matched_pairs(loaded["baseline_withmanual"]["views"],
                           loaded["baseline_nomanual"]["views"])
        R["Q6_manual"] = mp
        line("A = WITH manual, B = WITHOUT manual.")
        line("")
        line("| metric | value |")
        line("|---|---|")
        for kk, vv in mp.items():
            line("| %s | %s |" % (kk, ("%.2f" % vv) if isinstance(vv, float) else vv))
        line("")
    else:
        line("- Cannot compare: one of the baseline files is missing.")
        line("")

    # ---- Missing / to-run guidance ----
    line("## What is still missing / to run")
    line("")
    if not missing:
        line("All expected `_full*.json` datasets were found. Nothing else is required "
             "to answer Q1-Q6.")
    else:
        for key in missing:
            line("- **%s**: none of %s present." %
                 (key, ", ".join("`%s`" % n for n in FILE_CANDIDATES[key])))
    line("")
    line("Note: this script only reads `*_full*.json`. Per-chunk completeness "
         "(gaps/overlaps/corruption) is the job of the existing read-only "
         "`check_progress.py`; run that separately if you want chunk-level status.")
    line("")

    # ---- Write outputs (never overwrite) ----
    md_path = safe_out_path(directory, "debate_analysis_report.md")
    json_path = safe_out_path(directory, "debate_analysis_report.json")
    with open(md_path, "w", encoding="utf-8") as f:
        f.write("\n".join(md) + "\n")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(R, f, indent=2, ensure_ascii=False)

    print("Wrote:")
    print("  %s" % md_path)
    print("  %s" % json_path)
    print("(no result files were modified)")


if __name__ == "__main__":
    main()
