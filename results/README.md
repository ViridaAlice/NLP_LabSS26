# Results folder

Judge outputs for the MeSH-tag classification experiments.

## Experiment types

- **Baseline:** Judge receives the abstract and candidate tag, but no debater arguments.
- **Statement:** Baseline plus independent PRO and CON essays. The debaters do not interact.
- **Interactive:** Baseline plus a multi-turn PRO/CON debate.
- **Pydantic:** Output was requested through a structured Pydantic schema.
- **Rejudge2B:** Existing arguments were judged again using Qwen3.5-2B instead of Qwen3.5-0.8B.

## Complete primary results

### `baseline_nomanual_results_full.json`

- Baseline without the MeSH tagging manual.
- Complete: 3,000 records; no invalid predictions.
- Accuracy: 83.33%.
- Metadata confirms `use_manual=False`.

### `baseline_withmanual_results_full.json`

- Baseline with the MeSH tagging manual.
- Complete: 3,000 records; no invalid predictions.
- Accuracy: 80.17%.
- Metadata confirms `use_manual=True`.
- Contains the same record set as the no-manual baseline.

### `statement_results_full.json`

- Judge receives independent PRO and CON statements in addition to the baseline input.
- Complete: 3,000 records; no invalid predictions.
- Accuracy: 65.67%.

### `interactive_results_full.json`

- Interactive debate results using the original speaker labels.
- Complete: 3,000 records; no invalid predictions.
- Contains two debate orders:
  - `judge_ABA`: A speaks first and last; accuracy 55.37%.
  - `judge_BAB`: B speaks first and last; accuracy 54.33%.

### `interactive_results_BAB_swapped_full.json`

- Extends `interactive_results_full.json`.
- Reuses the original BAB debate text and physical speaking order.
- Presents original speaker B as `A` and original speaker A as `B`.
- New outcome: `judge_BAB_swapped_labels`.
- Complete: 3,000 records; accuracy 54.60%.
- Use this file for speaker-label-bias analysis.

### `interactive_results_BAB_swapped_labels_full.json`

- Duplicate of `interactive_results_BAB_swapped_full.json`.
- Same 3,000 records, debate text, predictions, and raw judge outputs.
- Keep only for provenance; do not count it as a separate experimental condition.

## Structured-output results

### `pydantic_baseline_results_full.json`

- Baseline experiment using Pydantic-structured output.
- 3,000 records.
- Accuracy: 80.03%.
- Seven predictions are invalid.
- Its detected record-identity set differs from the two primary baseline files.
- Unknown: whether the difference is only record formatting/identification or a genuinely different sample.
- Unknown: whether the MeSH manual was included.

### `pydantic_statement_results_full.json`

- Statement experiment using Pydantic-structured output.
- Incomplete: 2,217 records.
- 225 predictions are invalid.
- Reported accuracy: 70.59%.
- Do not compare directly with complete 3,000-record runs without matching records and defining how invalid outputs are handled.

### Pydantic interactive results

- No `pydantic_interactive_results_full.json` is present.

## Qwen3.5-2B rejudging

### `statement_results_full_rejudge2B.json`

- Existing statement inputs rejudged with Qwen3.5-2B.
- Partial: 678 records.
- Accuracy: 79.20%.
- Source: `statement_results_full.json`.
- Compare with the 0.8B judge only on these same 678 records.

### `interactive_results_full_rejudge2B.json`

- Existing ABA and BAB debates rejudged with Qwen3.5-2B.
- Partial: 281 records.
- ABA accuracy: 69.40%.
- BAB accuracy: 71.89%.
- Source: `interactive_results_full.json`.
- Compare with the 0.8B judge only on these same 281 records.

## Likely legacy or incomplete files

### `baseline_results_merged.json`

- Likely an older baseline run.
- Partial: 1,189 records.
- 486 invalid predictions.
- Uses `model_prediction` rather than `prediction`.
- Metadata lists `Qwen/Qwen3.5-0.8B`.
- Reported accuracy: 39.87%.
- Exact prompt/manual configuration remains unknown.
- Exclude from primary comparisons unless the generating script is inspected.

### `statement_results_merged.json`

- Likely an older statement run.
- Partial: 1,470 records.
- 1,224 invalid predictions.
- Uses `model_prediction`.
- Reported accuracy: 11.09%.
- Exclude from primary comparisons.

### `interactive_results_merged.json`

- Likely an older interactive run with only one stored prediction per record.
- Partial: 1,221 records.
- 991 invalid predictions.
- Uses `model_prediction`.
- Reported accuracy: 10.73%.
- It does not have the complete ABA/BAB structure of `interactive_results_full.json`.
- Exclude from primary comparisons.

## Important comparison notes

- Do not compare conditions using aggregate accuracy alone when their record sets differ.
- Use matched records for Pydantic, legacy, and 2B comparisons.
- Decide consistently whether invalid predictions count as errors or are excluded.
- Use only one of the two identical swapped-BAB files.
- ABA versus BAB changes debate content as well as speaking order, so it is not a perfectly isolated order test.
- Original BAB versus swapped-label BAB holds text and order constant; this is the clean test of A/B label bias.
- The `*_rejudge2B.json` files are incomplete and should only be compared against their matching 0.8B subsets.
