# Results

Results for the PubMed/MeSH binary tagging experiments. The task is to decide whether a candidate MeSH tag belongs to a biomedical abstract.

## Dataset and completion rule

Each run should contain **3,000 unique `(stage, pmid)` records**:

- `Round 1: True Tag`: 1,000 positive cases; expected answer `Yes`.
- `Round 2: Unrelated Tag`: 1,000 unrelated negative cases; expected answer `No`.
- `Round 3: Similar Tag`: 1,000 difficult negative cases; expected answer `No`.

A run is considered **record-complete when all 3,000 records exist**. An `Unknown` prediction does not require a rerun, but it is an unresolved model/parser output and must be reported separately in analysis.

The latest supplied audit found every previously listed canonical `*_full.json` file record-complete. The only unresolved outputs were **129 `Unknown` predictions in `pydantic_statement_results_full.json`**. No rerun is required under the record-complete rule.

The additional asymmetric title-only and larger-baseline rejudge files listed below are considered completed results based on the supplied run/merge status from 26 August 2026. Analysis scripts should still validate their record counts, uniqueness, candidate tags, ground truth, and `Unknown` counts before comparison rather than relying only on filenames or top-level metadata.

The three legacy `*_merged.json` files were not included in the earlier audit output; audit them before using them in a complete-dataset comparison.

## Experiment families

- **Baseline:** judge sees the article information and candidate tag; no debater input.
- **Statement:** one PRO and one CON debater independently write essays; they do not interact.
- **Interactive:** PRO and CON debaters participate in a three-turn debate, either `ABA` or `BAB`.
- **Rejudge2B:** stored inputs or arguments are judged again by a 2B judge; debaters are not rerun.
- **Rejudge4B:** stored inputs are judged again by a 4B judge; debaters are not rerun.
- **Asymmetric title-only:** latest asymmetric-information variants in which the judge is restricted to title-level source context. The family includes a no-debate baseline, independent statements, and an interactive ABA debate. Use the newest generating scripts and file metadata as the source of truth for the exact information shown to each debater and judge.
- **Pydantic:** older runs requesting structured JSON and parsing it with Pydantic. These have no log-probability fallback.
- **Merged:** older chunk merges. Similar filenames do not imply prompt or schema equivalence with the newer robust files.

## Models used

The production scripts associated with the previously listed results use:

- **Standard judge:** `Qwen3.5-0.8B`
- **Large judge:** `Qwen3.5-2B`
- **Debaters:** `Qwen3.5-2B`

The new larger-baseline files add 2B and 4B rejudge conditions, as encoded by `rejudge2B` and `rejudge4B` in their filenames. Use the model identifier recorded in the generating script or JSON metadata for the exact 4B checkpoint; do not infer a full checkpoint name from the filename alone.

The proposal and `run_ai_debate.py` refer to Qwen2.5-0.5B/Qwen2.5-3B. That script writes `debate_experiment_results*`, so none of the listed result filenames clearly map to that older Qwen2.5 run. Use the generating script and record schema—not the proposal—as provenance.

## Latest completed additions

The following artifacts were added to the results inventory on 26 August 2026:

| Path | Mode | Owner | Group | Size (bytes) | Modified | Purpose/status |
|---|---:|---|---|---:|---|---|
| `asymmetric_titleonly_interactive_aba_full.json` | `-rw-------` | `alice` | `alice` | 12,915,222 | 2026-08-26 12:23 | Complete merged asymmetric title-only interactive ABA result |
| `asymmetric_titleonly_statement_full.json` | `-rw-------` | `alice` | `alice` | 10,209,324 | 2026-08-26 12:23 | Complete merged asymmetric title-only statement result |
| `asymmetric_titleonly_baseline_full.json` | `-rw-------` | `alice` | `alice` | 2,905,093 | 2026-08-26 12:23 | Complete merged asymmetric title-only baseline result |
| `checkpoints_larger_baselines/` | `drwxrwxr-x` | `alice` | `alice` | 4,096 | 2026-08-26 12:02 | Checkpoint directory for larger-baseline jobs; not a final result file |
| `baseline_withmanual_results_full_rejudge2B.json` | `-rw-rw-r--` | `alice` | `alice` | 6,104,291 | 2026-08-26 12:02 | Complete with-manual baseline rejudged by the 2B judge |
| `baseline_nomanual_results_full_rejudge4B.json` | `-rw-rw-r--` | `alice` | `alice` | 12,726,969 | 2026-08-26 12:02 | Complete no-manual baseline rejudged by the 4B judge |
| `baseline_nomanual_results_full_rejudge2B.json` | `-rw-rw-r--` | `alice` | `alice` | 5,417,793 | 2026-08-26 12:02 | Complete no-manual baseline rejudged by the 2B judge |

Notes:

- The three `asymmetric_titleonly_*_full.json` files are the canonical merged outputs for the latest asymmetric title-only evaluation round. Their former chunk files should not be pooled with the merged files.
- `asymmetric_titleonly_interactive_aba_full.json` contains the ABA condition named by the file. Do not assume that it also contains a paired BAB condition without checking its schema.
- The three baseline `*_rejudge2B.json`/`*_rejudge4B.json` files are separate judge-size conditions. Keep the manual and no-manual conditions separate.
- `checkpoints_larger_baselines/` is operational state, not an analysis input. Do not scan it as if it were a canonical `*_full.json` result.

## File overview

“Manual” and “assigned tags” below describe what is inserted into the **actual judge prompt**, not merely loaded by the script.

| File | Family | Judge | Debaters | Judge inputs beyond abstract + candidate | Log probabilities | Prediction field/path | Audit note |
|---|---|---|---|---|---|---|---|
| `baseline_nomanual_results_full.json` | Baseline | Qwen3.5-0.8B | None | Assigned tags; no manual | Yes | `prediction` | 3,000; 0 Unknown |
| `baseline_withmanual_results_full.json` | Baseline | Qwen3.5-0.8B | None | Assigned tags + NLM manual | Yes | `prediction` | 3,000; 0 Unknown |
| `baseline_nomanual_results_full_rejudge2B.json` | Baseline rejudge | 2B judge | None | Preserves no-manual condition; verify exact prompt from script/metadata | Inspect schema | Inspect schema | Complete; newly added |
| `baseline_nomanual_results_full_rejudge4B.json` | Baseline rejudge | 4B judge | None | Preserves no-manual condition; verify exact prompt from script/metadata | Inspect schema | Inspect schema | Complete; newly added |
| `baseline_withmanual_results_full_rejudge2B.json` | Baseline rejudge | 2B judge | None | Preserves with-manual condition; verify exact prompt from script/metadata | Inspect schema | Inspect schema | Complete; newly added |
| `asymmetric_titleonly_baseline_full.json` | Asymmetric title-only baseline | Use script/metadata | None | Title-only source context; verify other prompt inputs from script | Inspect schema | Inspect schema | Complete merged output; newly added |
| `pydantic_baseline_results_full.json` | Baseline | Qwen3.5-0.8B | None | Assigned tags + NLM manual | No | `model_prediction` | 3,000; 0 Unknown |
| `baseline_results_merged.json` | Baseline, legacy | Qwen3.5-0.8B | None | Assigned tags + NLM manual | No | Usually `model_prediction` | Not in supplied audit |
| `statement_results_full.json` | Statement | Qwen3.5-0.8B | Qwen3.5-2B | Two essays; no manual or assigned tags | Yes | `prediction` | 3,000; 0 Unknown |
| `statement_results_full_rejudge2B.json` | Statement rejudge | Qwen3.5-2B | Reused Qwen3.5-2B essays | Same stored essays; no manual or assigned tags | Yes | `prediction` | 3,000; 0 Unknown |
| `asymmetric_titleonly_statement_full.json` | Asymmetric title-only statement | Use script/metadata | Use script/metadata | Title-only source context + statement arguments | Inspect schema | Inspect schema | Complete merged output; newly added |
| `pydantic_statement_results_full.json` | Statement, older Pydantic | Qwen3.5-0.8B | Qwen3.5-2B | Two essays; no manual or assigned tags | No | `model_prediction` | 3,000; 129 Unknown |
| `statement_results_merged.json` | Statement, legacy | Qwen3.5-0.8B | Qwen3.5-2B | Two essays + assigned tags + NLM manual | No | Usually `model_prediction` | Not in supplied audit |
| `interactive_results_full.json` | Interactive | Qwen3.5-0.8B | Qwen3.5-2B | ABA/BAB transcript; no manual or assigned tags | Yes, per judge path | `judge_ABA.prediction`, `judge_BAB.prediction` | 3,000; 0 Unknown |
| `interactive_results_full_rejudge2B.json` | Interactive rejudge | Qwen3.5-2B | Reused Qwen3.5-2B transcripts | Same ABA/BAB transcripts | Yes, per judge path | `judge_ABA.prediction`, `judge_BAB.prediction` | 3,000; 0 Unknown |
| `asymmetric_titleonly_interactive_aba_full.json` | Asymmetric title-only interactive | Use script/metadata | Use script/metadata | Title-only source context + ABA transcript | Inspect schema | Inspect schema | Complete merged output; newly added |
| `interactive_results_BAB_swapped_labels_full.json` | Interactive label test | Qwen3.5-0.8B | Reused transcripts | Original BAB text displayed with A/B labels exchanged | Yes, per judge path | `judge_BAB_swapped_labels.prediction` plus original paths | 3,000; 0 Unknown |
| `interactive_results_BAB_swapped_full.json` | Interactive label test | Qwen3.5-0.8B | Reused transcripts | Same as preceding file | Yes, per judge path | Same as preceding file | 3,000; normalized duplicate |
| `interactive_results_merged.json` | Interactive, legacy | Qwen3.5-0.8B | Qwen3.5-2B | One ABA transcript + assigned tags + NLM manual | No | Usually `model_prediction` | Not in supplied audit |

## File details

### Baseline

- **`baseline_nomanual_results_full.json`**
  - Generated by `debate_baseline_judge.py --no_manual`.
  - Clean comparison partner for the with-manual baseline.
  - Forced structured Yes/No output with a log-probability fallback.
  - Stores assigned tags, raw judge output, fallback use, correctness, and confidence.

- **`baseline_withmanual_results_full.json`**
  - Generated by `debate_baseline_judge.py`.
  - Same setup as the no-manual run, with the NLM indexing manual added to the judge prompt.
  - Best file for measuring the effect of supplying the manual.

- **`baseline_nomanual_results_full_rejudge2B.json`**
  - Completed no-manual baseline condition evaluated by the 2B judge.
  - Compare with `baseline_nomanual_results_full.json` only after confirming exact record identity and that the stored source inputs were reused unchanged.
  - Recompute metrics from records and inspect the schema for prediction and confidence paths.

- **`baseline_nomanual_results_full_rejudge4B.json`**
  - Completed no-manual baseline condition evaluated by the 4B judge.
  - Enables a judge-size comparison with the original and 2B no-manual baselines when records and prompts match.
  - Use the generating script or metadata for the exact 4B checkpoint identity.

- **`baseline_withmanual_results_full_rejudge2B.json`**
  - Completed with-manual baseline condition evaluated by the 2B judge.
  - Compare with `baseline_withmanual_results_full.json` only after verifying identical records and preserved manual/prompt contents.

- **`asymmetric_titleonly_baseline_full.json`**
  - Canonical merged baseline output for the latest asymmetric title-only round.
  - Contains no debate condition and serves as the comparison baseline for the title-only statement and interactive ABA runs.
  - Treat the newest script and JSON schema as authoritative for exact prompt inputs, model identity, prediction path, and confidence fields.

- **`pydantic_baseline_results_full.json`**
  - Generated by `pydantic_baseline.py`.
  - Requests JSON with `thinking` and `answer`, retries malformed outputs, but has no log-probability scoring or guaranteed fallback.
  - Stores `full_model_output`; does not store the abstract or assigned tags.

- **`baseline_results_merged.json`**
  - Mapped by its output prefix/schema to `judge_baseline.py`.
  - Older free-text `<thinking>... Answer: Yes/No` format with up to three retries.
  - No confidence/log-probability fields.
  - Treat as a separate legacy prompt/parser condition.

### Statement

- **`statement_results_full.json`**
  - Generated by `debate_statement_judge.py`.
  - Qwen3.5-2B independently generates one PRO and one CON essay; PRO is randomly displayed as A or B.
  - The actual debater and judge prompts use the abstract and candidate tag. The script loads the manual and stores assigned tags, but does **not** insert either into these prompts.
  - Stores abstract, assigned tags, PRO/CON essays, displayed `arg_a`/`arg_b`, side-to-label mapping, prediction, raw judge output, fallback use, and confidence.

- **`statement_results_full_rejudge2B.json`**
  - Generated by `debate_rejudge_large.py --mode statement` from `statement_results_full.json`.
  - Reuses the exact stored essays and changes only the judge from Qwen3.5-0.8B to Qwen3.5-2B.
  - Clean paired test of judge size, provided records are matched by candidate tag as well as `(stage, pmid)`.

- **`asymmetric_titleonly_statement_full.json`**
  - Canonical merged statement output for the latest asymmetric title-only round.
  - Represents the independent PRO/CON statement condition under title-only judge context.
  - Compare it with the corresponding asymmetric title-only baseline only after exact record and prompt-condition validation.

- **`pydantic_statement_results_full.json`**
  - Generated by `pydantic_statement.py`.
  - Debaters see abstract, assigned tags, and candidate tag; the judge sees abstract, candidate tag, and the two essays.
  - The manual is loaded but never inserted into either prompt.
  - No log probabilities or guaranteed fallback; 129 outputs remain `Unknown`.
  - `is_correct` is false for `Unknown`, so stored/metadata accuracy counts these as failures.

- **`statement_results_merged.json`**
  - Most likely generated from `run_ai_debate2.py` chunks.
  - Both debaters and judge receive the NLM manual and assigned tags.
  - Uses free-text answer parsing and retries; no log probabilities.
  - Confirm provenance from schema: `model_prediction` + `pro_first` + no `confidence` indicates `run_ai_debate2.py`.

### Interactive

- **`interactive_results_full.json`**
  - Generated by `debate_interactive_judge.py`.
  - Stores two conditions for every record:
    - `ABA`: A opens, B rebuts, A closes.
    - `BAB`: B opens, A rebuts, B closes.
  - A keeps the same PRO/CON side across both orders.
  - ABA debater turns were reused from `pydantic_interactive_results_full.json` when available; missing ABA turns were regenerated. BAB turns were generated anew. Both judge decisions were generated anew.
  - Actual debater/judge prompts omit the loaded manual and assigned tags.
  - Stores full transcripts, side mappings, both judgments, confidence, and `order_flip`.

- **`interactive_results_full_rejudge2B.json`**
  - Generated by `debate_rejudge_large.py --mode interactive`.
  - Reuses both exact transcripts and changes only the judge to Qwen3.5-2B.
  - Clean paired judge-size test against `interactive_results_full.json`.

- **`asymmetric_titleonly_interactive_aba_full.json`**
  - Canonical merged interactive ABA output for the latest asymmetric title-only round.
  - The filename identifies a single ABA protocol; do not normalize it as a paired ABA/BAB file unless the record schema explicitly contains both paths.
  - Compare it with the asymmetric title-only baseline and statement conditions only on exactly matched records.

- **`interactive_results_BAB_swapped_labels_full.json`**
  - Generated by `judge_bab_swapped_labels.py` from `interactive_results_full.json`.
  - Reuses the BAB text byte-for-byte and changes only displayed speaker names:
    - displayed A = original B opening and closing;
    - displayed B = original A rebuttal.
  - The physical first/middle/last argument content is unchanged.
  - Adds `debate_BAB_swapped_labels`, label mappings, `judge_BAB_swapped_labels`, and a flip indicator while retaining the source ABA/BAB data.
  - Cleanest test of displayed A/B label bias.

- **`interactive_results_BAB_swapped_full.json`**
  - Same normalized `results` array as `interactive_results_BAB_swapped_labels_full.json` in the supplied audit.
  - Treat `interactive_results_BAB_swapped_labels_full.json` as the canonical descriptive name and exclude the duplicate from aggregate comparisons.

- **`interactive_results_merged.json`**
  - Most likely generated from `run_interactive_debate.py` chunks.
  - Contains one ABA transcript per record, not paired ABA/BAB debates.
  - Debaters and judge receive the manual and assigned tags.
  - Uses free-text answer parsing and retries; no log probabilities.
  - Confirm provenance from fields such as `a_turn1`, `b_turn1`, `a_turn2`, `pro_is_debater_a`, and `model_prediction`.

## General JSON structure

Most files use this top-level form:

```json
{
  "metadata": {
    "overall_accuracy": 0.0
  },
  "results": [
    {
      "pmid": "...",
      "stage": "Round 1: True Tag",
      "candidate_tag": "...",
      "ground_truth": "Yes"
    }
  ]
}
```

Common record fields:

- `pmid`, `stage`: primary record identity.
- `candidate_tag`, `ground_truth`: evaluated label and expected Yes/No answer.
- `assigned_tags`: present only in some schemas; it may be stored even when not used in the prompt.
- `prediction` or `model_prediction`: final judge decision, depending on script generation.
- `is_correct`: cached comparison against `ground_truth`.
- `judge_output` or `full_model_output`: raw generated judge text.
- `needed_fallback`: whether structured generation failed and the log-probability fallback supplied the decision.
- `pro_is_a`, `pro_first`, `a_is_pro`, or `pro_is_debater_a`: related but schema-specific side/label indicators; normalize carefully.

Interactive robust files nest decisions under `judge_ABA`, `judge_BAB`, and optionally `judge_BAB_swapped_labels`. Do not look only for a top-level prediction. The new `asymmetric_titleonly_interactive_aba_full.json` may use a different single-ABA schema; inspect it explicitly rather than assuming the older paired format.

## Confidence and log probabilities

New robust files contain a `confidence` object:

```json
{
  "verdict_logprob": {"Yes": -1.2, "No": -2.3},
  "verdict_prob_belongs": 0.75,
  "boolean_logprob": {"true": -1.4, "false": -2.0},
  "boolean_prob_true": 0.65,
  "debater_logprob": {"A": -1.1, "B": -2.1},
  "debater_prob_A_right": 0.73
}
```

- Baseline robust files include the Yes/No and true/false framings.
- Statement and interactive robust files additionally include the A/B framing.
- These are **teacher-forced continuation scores from separate follow-up prompt framings**, not token log probabilities of the original generated explanation.
- Raw log probabilities are summed over label tokens and normalized only within each displayed pair.
- Do not assume the Yes/No, true/false, and A/B probabilities are directly interchangeable or calibrated.
- Inspect the new asymmetric title-only and larger-baseline rejudge schemas before assuming they expose every confidence framing shown above.

## Unknown predictions

- `Unknown` means structured/free-text parsing did not recover a valid Yes/No response.
- It is not a substantive third class and must never be silently converted to `No`.
- Under the current rule, a file with 3,000 records is complete even if it contains Unknowns.
- For every analysis, report:
  - total records;
  - valid Yes/No records;
  - Unknown count and rate;
  - accuracy on valid predictions;
  - optionally, accuracy with Unknown counted as incorrect, clearly labelled.
- The 129 Unknowns in `pydantic_statement_results_full.json` make comparisons involving that file partly selective if they are dropped. Use both coverage and performance statistics.
- Unknown counts for the newly added files were not included in the earlier audit statement and must be computed during analysis.

## Guidance for the comparison script

1. **Load schemas explicitly.** Normalize `prediction`, `model_prediction`, nested interactive judge paths, and any new asymmetric title-only paths into separate condition rows.
2. **Match on more than `(stage, pmid)`.** Also verify `candidate_tag` and `ground_truth`. Positive candidate tags are randomly selected, and chunk-specific seeds can cause different runs to evaluate different true tags for the same PMID.
3. **Recompute metrics from records.** Do not rely only on top-level metadata, which may use different Unknown handling or reflect an intermediate merge.
4. **Keep separate experimental conditions separate.** Manual use, assigned-tag use, title-only versus abstract access, prompt wording, output parser, fallback behavior, and model size are all potential confounds.
5. **Exclude duplicate and intermediate data.** Exclude the duplicate swapped-BAB file, all source chunks after their canonical `*_full.json` merge is loaded, and files under `checkpoints_larger_baselines/`.
6. **Use paired tests where content is reused:**
   - baseline no-manual vs with-manual: manual effect, after candidate verification;
   - baseline no-manual original vs no-manual rejudge2B vs no-manual rejudge4B: judge-size effect, if prompts and records are otherwise fixed;
   - baseline with-manual original vs with-manual rejudge2B: judge-size effect with the manual condition preserved;
   - statement full vs statement rejudge2B: judge-size effect with fixed essays;
   - interactive full vs interactive rejudge2B: judge-size effect with fixed transcripts;
   - original BAB vs swapped-label BAB: displayed-label effect with fixed content/order;
   - asymmetric title-only baseline vs statement vs interactive ABA: debate-protocol comparison only after exact record matching and verification of all non-debate prompt inputs.
7. **Interpret ABA vs BAB cautiously.** Their transcripts were generated separately, so differences combine speaking order and argument-content variation.
8. **Treat Pydantic/legacy comparisons as multi-factor comparisons.** They differ in prompts, available inputs, parsing, retries, and confidence fallback—not only output formatting.
9. **Audit merged title-only files once, not their chunks.** Verify `merged_from`, `merged_records`, duplicate keys, and recomputed accuracy, then use only the canonical `*_full.json` file in analysis.

## Provenance map

| Result prefix/file | Generating script |
|---|---|
| `baseline_nomanual_results*` | `debate_baseline_judge.py --no_manual` |
| `baseline_withmanual_results*` | `debate_baseline_judge.py` |
| `baseline_nomanual_results_full_rejudge2B.json` | Latest larger-baseline rejudge script; confirm exact script and model from metadata/checkpoint records |
| `baseline_nomanual_results_full_rejudge4B.json` | Latest larger-baseline rejudge script; confirm exact script and model from metadata/checkpoint records |
| `baseline_withmanual_results_full_rejudge2B.json` | Latest larger-baseline rejudge script; confirm exact script and model from metadata/checkpoint records |
| `asymmetric_titleonly_baseline_full.json` | Latest asymmetric title-only baseline script; canonical merge of its chunk files |
| `asymmetric_titleonly_statement_full.json` | Latest asymmetric title-only statement script; canonical merge of its chunk files |
| `asymmetric_titleonly_interactive_aba_full.json` | Latest asymmetric title-only interactive ABA script; canonical merge of its chunk files |
| `pydantic_baseline_results*` | `pydantic_baseline.py` |
| Legacy `baseline_results*` | `judge_baseline.py` |
| Robust `statement_results_full*` | `debate_statement_judge.py` |
| `pydantic_statement_results*` | `pydantic_statement.py` |
| Legacy statement schema/chunks | `run_ai_debate2.py` |
| Robust `interactive_results_full*` | `debate_interactive_judge.py` |
| Prior reusable ABA source | `pydantic_interactive.py` |
| Legacy interactive schema/chunks | `run_interactive_debate.py` |
| Existing statement/interactive `*_rejudge2B.json` | `debate_rejudge_large.py` |
| `interactive_results_BAB_swapped_labels*` | `judge_bab_swapped_labels.py` |

When a shared output prefix makes provenance ambiguous, identify the producer from the record schema and confidence fields described above. For the latest asymmetric title-only and larger-baseline rejudge additions, replace the provisional provenance descriptions with exact script filenames once those names are confirmed from the scripts or run metadata.
