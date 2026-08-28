# Complete analysis of PubMed/MeSH result files

Generated: `2026-08-26T12:24:45.256545+00:00`

This report recomputes all metrics from normalized records. Source result JSON files are read-only. Numerical differences are described as controlled findings only when candidate identity and reused content were verified.

## Executive summary of the current runs

- Among complete runs, Baseline 2B — no manual has the highest observed balanced accuracy (86.1%).
- Baseline no manual: 0.8B → 2B changed exact-pair accuracy by +3.6 percentage points.
- Baseline with manual: 0.8B → 2B changed exact-pair accuracy by +4.8 percentage points.
- Statements: 0.8B → 2B changed exact-pair accuracy by +13.8 percentage points.
- Interactive ABA: 0.8B → 2B changed exact-pair accuracy by +19.8 percentage points.
- Interactive BAB: 0.8B → 2B changed exact-pair accuracy by +19.8 percentage points.
- In the common title-only subset, baseline → statements changed accuracy by -1.0 percentage points.
- In the common title-only subset, baseline → interactive aba changed accuracy by -5.5 percentage points.
- Partial runs are reported for diagnostics but excluded from the primary ranking: Baseline 0.8B — legacy, Interactive ABA — legacy, Statement — legacy.
- High fallback use requires parser-level caution in: Baseline 4B — no manual (36.7%), Baseline 4B — with manual (78.7%), Interactive ABA — 0.8B judge (73.6%), Interactive BAB — 0.8B judge (65.5%), Interactive BAB — displayed labels swapped (66.3%), Statement — 0.8B judge (29.9%).
- The BAB label swap changed individual verdicts on 25.3% of exact pairs, while the net accuracy change was +0.3 points.

### What fallback means

Fallback means that the intended structured verdict could not be used directly and a secondary recovery/scoring route supplied the prediction. It is not automatically wrong, but a high rate can indicate formatting, truncation, prompt, or parser incompatibility.

### Run quality and completion

| Condition | Records | Missing | Complete | Unknown | Coverage | Fallback | Primary ranking |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Title-only asymmetric — baseline | 3,000 | 0 | Yes | 0 | 100.0% | — | Yes |
| Title-only asymmetric — interactive ABA | 3,000 | 0 | Yes | 0 | 100.0% | — | Yes |
| Title-only asymmetric — statements | 3,000 | 0 | Yes | 0 | 100.0% | — | Yes |
| Baseline 0.8B — legacy | 1,189 | 1,811 | No | 486 | 59.1% | — | No |
| Baseline 0.8B — older Pydantic | 3,000 | 0 | Yes | 0 | 100.0% | — | Yes |
| Baseline 0.8B — no manual | 3,000 | 0 | Yes | 0 | 100.0% | 0 | Yes |
| Baseline 0.8B — with manual | 3,000 | 0 | Yes | 0 | 100.0% | 0 | Yes |
| Baseline 2B — no manual | 3,000 | 0 | Yes | 0 | 100.0% | 0 | Yes |
| Baseline 2B — with manual | 3,000 | 0 | Yes | 0 | 100.0% | 0 | Yes |
| Baseline 4B — no manual | 3,000 | 0 | Yes | 0 | 100.0% | 0.367 | Yes |
| Baseline 4B — with manual | 3,000 | 0 | Yes | 0 | 100.0% | 0.787 | Yes |
| Interactive ABA — legacy | 1,221 | 1,779 | No | 991 | 18.8% | — | No |
| Interactive ABA — rejudged by 2B | 3,000 | 0 | Yes | 0 | 100.0% | 0 | Yes |
| Interactive BAB — rejudged by 2B | 3,000 | 0 | Yes | 0 | 100.0% | 0 | Yes |
| Interactive ABA — 0.8B judge | 3,000 | 0 | Yes | 0 | 100.0% | 0.736 | Yes |
| Interactive BAB — 0.8B judge | 3,000 | 0 | Yes | 0 | 100.0% | 0.655 | Yes |
| Interactive BAB — displayed labels swapped | 3,000 | 0 | Yes | 0 | 100.0% | 0.663 | Yes |
| Statement — legacy | 1,470 | 1,530 | No | 1,224 | 16.7% | — | No |
| Statement — older Pydantic | 3,000 | 0 | Yes | 129 | 95.7% | — | Yes |
| Statement — rejudged by 2B | 3,000 | 0 | Yes | 0 | 100.0% | 0 | Yes |
| Statement — 0.8B judge | 3,000 | 0 | Yes | 0 | 100.0% | 0.299 | Yes |

### Judge size by protocol

| Protocol | Judge | Manual | N | Complete | Accuracy | Balanced | True tag | Unrelated | Similar | FPR | FNR | Fallback |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Baseline, no manual | 0.8B | No | 3,000 | Yes | 83.3% | 0.817 | 0.769 | 0.912 | 0.819 | 13.5% | 23.1% | 0 |
| Baseline, no manual | 2B | No | 3,000 | Yes | 86.9% | 0.861 | 0.837 | 0.945 | 0.826 | 11.5% | 16.3% | 0 |
| Baseline, no manual | 4B | No | 3,000 | Yes | 80.3% | 0.839 | 0.947 | 0.802 | 0.661 | 26.9% | 5.3% | 0.367 |
| Baseline, with manual | 0.8B | Yes | 3,000 | Yes | 80.2% | 0.763 | 0.646 | 0.928 | 0.831 | 12.0% | 35.4% | 0 |
| Baseline, with manual | 2B | Yes | 3,000 | Yes | 85.0% | 0.833 | 0.781 | 0.931 | 0.838 | 11.6% | 21.9% | 0 |
| Baseline, with manual | 4B | Yes | 3,000 | Yes | 54.7% | 0.659 | 0.995 | 0.410 | 0.235 | 67.8% | 0.5% | 0.787 |
| Independent statements | 0.8B | No | 3,000 | Yes | 65.7% | 0.672 | 0.720 | 0.627 | 0.623 | 37.5% | 28.0% | 0.299 |
| Independent statements | 2B | No | 3,000 | Yes | 79.5% | 0.737 | 0.561 | 0.937 | 0.887 | 8.8% | 43.9% | 0 |
| Interactive ABA | 0.8B | No | 3,000 | Yes | 55.4% | 0.609 | 0.773 | 0.460 | 0.428 | 55.6% | 22.7% | 0.736 |
| Interactive ABA | 2B | No | 3,000 | Yes | 75.2% | 0.730 | 0.664 | 0.831 | 0.760 | 20.4% | 33.6% | 0 |
| Interactive BAB | 0.8B | No | 3,000 | Yes | 54.3% | 0.603 | 0.781 | 0.453 | 0.396 | 57.6% | 21.9% | 0.655 |
| Interactive BAB | 2B | No | 3,000 | Yes | 74.1% | 0.739 | 0.732 | 0.774 | 0.717 | 25.4% | 26.8% | 0 |

### Exact-pair judge-size and manual comparisons

| Comparison | Pairs | A accuracy | B accuracy | Δ B−A | 95% CI | McNemar p | Status |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Baseline no manual: 0.8B → 2B | 3,000 | 83.3% | 86.9% | 0.036 | [0.022333333333333334, 0.04933333333333333] | 0.000 | controlled_after_exact_matching |
| Baseline no manual: 2B → 4B | 3,000 | 86.9% | 80.3% | -0.066 | [-0.081, -0.051] | 0.000 | controlled_after_exact_matching |
| Baseline with manual: 0.8B → 2B | 3,000 | 80.2% | 85.0% | 0.048 | [0.03266666666666666, 0.064] | 0.000 | controlled_after_exact_matching |
| Baseline with manual: 2B → 4B | 3,000 | 85.0% | 54.7% | -0.303 | [-0.32033333333333336, -0.286] | 0.000 | controlled_after_exact_matching |
| Manual effect at 0.8B | 3,000 | 83.3% | 80.2% | -0.032 | [-0.047, -0.016] | 0.000 | controlled_after_exact_matching |
| Manual effect at 2B | 3,000 | 86.9% | 85.0% | -0.019 | [-0.03133333333333333, -0.007333333333333333] | 0.002 | controlled_after_exact_matching |
| Manual effect at 4B | 3,000 | 80.3% | 54.7% | -0.257 | [-0.273, -0.23933333333333334] | 0.000 | controlled_after_exact_matching |
| Statements: 0.8B → 2B | 3,000 | 65.7% | 79.5% | 0.138 | [0.11965833333333334, 0.158] | 0.000 | controlled_after_exact_matching |
| Interactive ABA: 0.8B → 2B | 3,000 | 55.4% | 75.2% | 0.198 | [0.17733333333333334, 0.21866666666666668] | 0.000 | controlled_after_exact_matching |
| Interactive BAB: 0.8B → 2B | 3,000 | 54.3% | 74.1% | 0.198 | [0.17633333333333334, 0.219] | 0.000 | controlled_after_exact_matching |

### Does judge size help debate more than the baseline?

| Protocol | Common records | Baseline 0.8→2B gain | Protocol 0.8→2B gain | Difference-in-differences | 95% CI | Status |
| --- | --- | --- | --- | --- | --- | --- |
| Independent statements | 2,126 | 0.021 | 0.268 | +24.7% | [0.22038597384368913, 0.2731568998109641] | matched_difference_in_differences |
| Interactive ABA | 2,130 | 0.024 | 0.316 | +29.2% | [0.26187006801148166, 0.3221543869929858] | matched_difference_in_differences |
| Interactive BAB | 2,130 | 0.024 | 0.298 | +27.3% | [0.2419127988748242, 0.3052585058923904] | matched_difference_in_differences |

> A positive difference-in-differences means that the 0.8B→2B judge change helped the debate protocol more than it helped the no-manual baseline. It does not show that debate beats the baseline.

### Asymmetric title-only conditions on one common subset

| Condition | Common records | Accuracy | Balanced | FPR | FNR | Yes rate |
| --- | --- | --- | --- | --- | --- | --- |
| Title-only asymmetric — baseline | 2,045 | 85.6% | 0.709 | 13.8% | 44.4% | 14.7% |
| Title-only asymmetric — statements | 2,045 | 84.5% | 0.758 | 15.0% | 33.3% | 16.2% |
| Title-only asymmetric — interactive ABA | 2,045 | 80.0% | 0.692 | 19.4% | 42.2% | 20.3% |

| Comparison | Pairs | Δ B−A | 95% CI | McNemar p |
| --- | --- | --- | --- | --- |
| Baseline → statements | 2,045 | -0.010 | [-0.030612616947605486, 0.010309278350515462] | 0.343 |
| Baseline → interactive ABA | 2,045 | -0.055 | [-0.07647345348270823, -0.03383970299743243] | 0.000 |
| Statements → interactive ABA | 2,045 | -0.045 | [-0.06774668630338733, -0.022549019607843137] | 0.000 |

### BAB displayed-label stability

| Pairs | Agreement | Flips | Flip rate | Yes→No | No→Yes | Correctness gained | Correctness lost | Net accuracy Δ | Content test |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 3,000 | 0.747 | 758 | 25.3% | 367 | 391 | 383 | 375 | 0.3% | controlled |

## 1. Inventory, integrity, and provenance

| File | Family | Generation | Records | Complete | Unknown | Prediction paths | Issues |
| --- | --- | --- | --- | --- | --- | --- | --- |
| asymmetric_titleonly_baseline_full.json | baseline | asymmetric_titleonly | 3,000 | Yes | 0 | ["model_prediction"] | 0 |
| asymmetric_titleonly_interactive_aba_full.json | interactive | asymmetric_titleonly | 3,000 | Yes | 0 | ["model_prediction"] | 0 |
| asymmetric_titleonly_statement_full.json | statement | asymmetric_titleonly | 3,000 | Yes | 0 | ["model_prediction"] | 0 |
| baseline_nomanual_results_full.json | baseline | robust_0.8B | 3,000 | Yes | 0 | ["prediction"] | 0 |
| baseline_nomanual_results_full_rejudge2B.json | baseline | rejudge_2B | 3,000 | Yes | 0 | ["prediction"] | 0 |
| baseline_nomanual_results_full_rejudge4B.json | baseline | rejudge_4B | 3,000 | Yes | 0 | ["prediction"] | 0 |
| baseline_nomanual_results_rejudge2B_full.json | baseline | rejudge_2B | 3,000 | Yes | 0 | ["prediction"] | 0 |
| baseline_nomanual_results_rejudge4B_full.json | baseline | rejudge_4B | 3,000 | Yes | 0 | ["prediction"] | 0 |
| baseline_results_merged.json | baseline | legacy | 1,189 | No | 486 | ["model_prediction"] | 1 |
| baseline_withmanual_results_full.json | baseline | robust_0.8B | 3,000 | Yes | 0 | ["prediction"] | 0 |
| baseline_withmanual_results_full_rejudge2B.json | baseline | rejudge_2B | 3,000 | Yes | 0 | ["prediction"] | 0 |
| baseline_withmanual_results_rejudge2B_full.json | baseline | rejudge_2B | 3,000 | Yes | 0 | ["prediction"] | 0 |
| baseline_withmanual_results_rejudge4B_full.json | baseline | rejudge_4B | 3,000 | Yes | 0 | ["prediction"] | 0 |
| interactive_results_BAB_swapped_full.json | interactive | swapped_labels | 3,000 | Yes | 0 | ["judge_ABA.prediction", "judge_BAB.prediction", "judge_BAB_swapped_labels.prediction"] | 0 |
| interactive_results_BAB_swapped_labels_full.json | interactive | swapped_labels | 3,000 | Yes | 0 | ["judge_ABA.prediction", "judge_BAB.prediction", "judge_BAB_swapped_labels.prediction"] | 0 |
| interactive_results_full.json | interactive | robust_0.8B | 3,000 | Yes | 0 | ["judge_ABA.prediction", "judge_BAB.prediction"] | 0 |
| interactive_results_full_rejudge2B.json | interactive | rejudge_2B | 3,000 | Yes | 0 | ["judge_ABA.prediction", "judge_BAB.prediction"] | 0 |
| interactive_results_merged.json | interactive | legacy | 1,221 | No | 991 | ["model_prediction"] | 1 |
| pydantic_baseline_results_full.json | baseline | older_pydantic | 3,000 | Yes | 0 | ["model_prediction"] | 0 |
| pydantic_statement_results_full.json | statement | older_pydantic | 3,000 | Yes | 129 | ["model_prediction"] | 0 |
| statement_results_full.json | statement | robust_0.8B | 3,000 | Yes | 0 | ["prediction"] | 0 |
| statement_results_full_rejudge2B.json | statement | rejudge_2B | 3,000 | Yes | 0 | ["prediction"] | 0 |
| statement_results_merged.json | statement | legacy | 1,470 | No | 1,224 | ["model_prediction"] | 1 |

> Full nested schema audits remain available in `analysis_data.json`; the Markdown report uses compact schema labels to stay readable.

## 2. Condition overview

| Condition | Judge | Debater | Judge input | Manual | Assigned tags to judge | N | Complete | Accuracy | Balanced | Unknown | Fallback |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Title-only asymmetric — baseline | ./Qwen3.5-0.8B | — | title_only | — | Yes | 3,000 | Yes | 77.5% | 0.731 | 0 | — |
| Title-only asymmetric — interactive ABA | ./Qwen3.5-0.8B | ./Qwen3.5-2B | title_only | — | — | 3,000 | Yes | 72.4% | 0.683 | 0 | — |
| Title-only asymmetric — statements | ./Qwen3.5-0.8B | ./Qwen3.5-2B | title_only | — | — | 3,000 | Yes | 76.6% | 0.725 | 0 | — |
| Baseline 0.8B — legacy | ./Qwen3.5-0.8B | — | standard_experiment_input | Yes | Yes | 1,189 | No | 39.9% | 0.595 | 486 | — |
| Baseline 0.8B — older Pydantic | ./Qwen3.5-0.8B | — | standard_experiment_input | Yes | Yes | 3,000 | Yes | 80.1% | 0.784 | 0 | — |
| Baseline 0.8B — no manual | ./Qwen3.5-0.8B | — | standard_experiment_input | No | Yes | 3,000 | Yes | 83.3% | 0.817 | 0 | 0 |
| Baseline 0.8B — with manual | ./Qwen3.5-0.8B | — | standard_experiment_input | Yes | Yes | 3,000 | Yes | 80.2% | 0.763 | 0 | 0 |
| Baseline 2B — no manual | Qwen3.5-2B | — | standard_experiment_input | No | No | 3,000 | Yes | 86.9% | 0.861 | 0 | 0 |
| Baseline 2B — with manual | Qwen3.5-2B | — | standard_experiment_input | Yes | No | 3,000 | Yes | 85.0% | 0.833 | 0 | 0 |
| Baseline 4B — no manual | Qwen3.5-4B | — | standard_experiment_input | No | Yes | 3,000 | Yes | 80.3% | 0.839 | 0 | 0.367 |
| Baseline 4B — with manual | Qwen3.5-4B | — | standard_experiment_input | Yes | Yes | 3,000 | Yes | 54.7% | 0.659 | 0 | 0.787 |
| Interactive ABA — legacy | ./Qwen3.5-0.8B | ./Qwen3.5-2B | standard_experiment_input | Yes | Yes | 1,221 | No | 10.7% | 0.166 | 991 | — |
| Interactive ABA — rejudged by 2B | Qwen3.5-2B | Qwen3.5-2B | standard_experiment_input | No | No | 3,000 | Yes | 75.2% | 0.730 | 0 | 0 |
| Interactive BAB — rejudged by 2B | Qwen3.5-2B | Qwen3.5-2B | standard_experiment_input | No | No | 3,000 | Yes | 74.1% | 0.739 | 0 | 0 |
| Interactive ABA — 0.8B judge | ./Qwen3.5-0.8B | ./Qwen3.5-2B | standard_experiment_input | No | No | 3,000 | Yes | 55.4% | 0.609 | 0 | 0.736 |
| Interactive BAB — 0.8B judge | ./Qwen3.5-0.8B | ./Qwen3.5-2B | standard_experiment_input | No | No | 3,000 | Yes | 54.3% | 0.603 | 0 | 0.655 |
| Interactive BAB — displayed labels swapped | ./Qwen3.5-0.8B | ./Qwen3.5-0.8B | standard_experiment_input | No | No | 3,000 | Yes | 54.6% | 0.609 | 0 | 0.663 |
| Statement — legacy | ./Qwen3.5-0.8B | ./Qwen3.5-2B | standard_experiment_input | Yes | Yes | 1,470 | No | 11.1% | 0.147 | 1,224 | — |
| Statement — older Pydantic | ./Qwen3.5-0.8B | ./Qwen3.5-2B | standard_experiment_input | No | No | 3,000 | Yes | 74.6% | 0.708 | 129 | — |
| Statement — rejudged by 2B | Qwen3.5-2B | Qwen3.5-2B | standard_experiment_input | No | No | 3,000 | Yes | 79.5% | 0.737 | 0 | 0 |
| Statement — 0.8B judge | ./Qwen3.5-0.8B | ./Qwen3.5-2B | standard_experiment_input | No | No | 3,000 | Yes | 65.7% | 0.672 | 0 | 0.299 |

> Strict accuracy counts unresolved predictions as failures. Partial runs are retained for diagnostics but excluded from the primary ranking.

## Preregistered expectations

The following expectations come from the project proposal and analysis plan; they are not findings.

| Variation | Expectation | Counter-hypothesis | Primary metrics |
| --- | --- | --- | --- |
| Baseline vs statement/interactive debate | Adding adversarial PRO and CON evidence may improve judge accuracy, especially when both sides are visible together. | Persuasive but incorrect arguments, extra context, or weak evidence evaluation may leave accuracy unchanged or reduce it. | Strict accuracy, balanced accuracy, stage accuracy, paired fixes/breaks |
| Independent statements vs interactive rebuttal | Direct rebuttal may expose reasoning flaws beyond side-by-side independent essays. | Side-by-side comparison may provide most of the benefit; extra turns may mainly add verbosity and positional effects. | Matched accuracy change, similar-negative accuracy, first/two-turn preference |
| True, unrelated-negative, and similar-negative stages | Semantically similar incorrect tags should be harder to reject than unrelated incorrect tags. | A conservative judge may reject both negative types equally while missing true tags. | Stage accuracy, FPR by negative stage, balanced accuracy |
| NLM manual absent vs present | Indexing guidance may improve fine-grained decisions, particularly similar negatives. | The long manual may distract or overload the 0.8B judge and encourage excessive conservatism. | Paired accuracy, similar-negative accuracy, FPR/FNR, fallback and calibration |
| Qwen3.5-0.8B vs Qwen3.5-2B rejudge | The larger judge may evaluate evidence and difficult similar tags more reliably. | Poor or misleading debate evidence may remain the limiting factor, and a larger judge may amplify rhetoric or a side preference. | Content-fixed paired accuracy, fixes/breaks, stage accuracy, bias and confidence |
| PRO/CON, A/B, position, turn count, and verbosity | A well-calibrated judge should follow evidence rather than side name, display order, or response length. | Sycophancy, label preference, first/last speaker preference, two-turn advantage, or verbosity bias may affect decisions. | Error asymmetry, mapped side-selection rates, paired swaps, stratified positional and length effects |
| Original BAB vs BAB with displayed A/B labels swapped | With identical text and physical order, changing speaker names should not change the verdict. | Frequent or directionally asymmetric flips would indicate label sensitivity or an A/B preference. | Agreement, flip directions, correctness gained/lost, displayed-A selection |
| Teacher-forced Yes/No, true/false, and A/B confidence | Useful confidence should discriminate errors, calibrate reasonably, and support selective prediction. | Framing sensitivity and fallback circularity may inflate apparent agreement without improving calibration. | AUC, Brier score, NLL, ECE, framing disagreement, selective accuracy |

## 3. Legacy baseline → statement → interactive

### Metrics

| family | stage | strict_accuracy | valid_only_accuracy | balanced_accuracy | false_positive_rate | false_negative_rate | accuracy_minus_always_no | always_no_accuracy | always_yes_accuracy | analysis_role | balanced_accuracy_minus_chance |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| baseline | — | 39.9% | 67.4% | 59.5% | 1.8% | 42.4% | 24.0% | 15.9% | 84.1% | descriptive_historical | 9.5% |
| statement | — | 11.1% | 66.3% | 14.7% | 9.4% | 60.2% | -20.9% | 32.0% | 68.0% | descriptive_historical | -35.3% |
| interactive | — | 10.7% | 57.0% | 16.6% | 29.6% | 50.3% | -7.4% | 18.1% | 81.9% | descriptive_historical | -33.4% |
| baseline | Round 1: True Tag | 30.7% | 57.6% | — | — | 42.4% | 30.7% | 0.0% | 100.0% | — | — |
| baseline | Round 2: Unrelated Tag | 88.4% | 98.2% | — | 1.8% | — | -11.6% | 100.0% | 0.0% | — | — |
| baseline | Round 3: Similar Tag | — | — | — | — | — | — | — | — | — | — |
| statement | Round 1: True Tag | 4.7% | 39.8% | — | — | 60.2% | 4.7% | 0.0% | 100.0% | — | — |
| statement | Round 2: Unrelated Tag | 24.7% | 90.6% | — | 9.4% | — | -75.3% | 100.0% | 0.0% | — | — |
| statement | Round 3: Similar Tag | — | — | — | — | — | — | — | — | — | — |
| interactive | Round 1: True Tag | 7.4% | 49.7% | — | — | 50.3% | 7.4% | 0.0% | 100.0% | — | — |
| interactive | Round 2: Unrelated Tag | 25.8% | 70.4% | — | 29.6% | — | -74.2% | 100.0% | 0.0% | — | — |
| interactive | Round 3: Similar Tag | — | — | — | — | — | — | — | — | — | — |

### Paired comparisons

| A | B | Exact pairs | Accuracy Δ (B−A) | 95% CI | McNemar p | Status |
| --- | --- | --- | --- | --- | --- | --- |
| baseline.legacy_0.8B | statement.legacy_0.8B | 292 | -49.0% | -55.1% to -42.7% | 0.000 | confounded |
| baseline.legacy_0.8B | interactive.legacy_0.8B.ABA | 228 | -38.2% | -45.4% to -31.0% | 0.000 | confounded |
| statement.legacy_0.8B | interactive.legacy_0.8B.ABA | 1,221 | 2.6% | +0.3% to +4.9% | 0.028 | confounded |

### Bias and position diagnostics

| a_longer.confidence_interval_95 | a_longer.count | a_longer.eligible_count | a_longer.rate | ab_label.accuracy_by_correct_displayed_label | ab_label.accuracy_when_correct_is_A_minus_when_correct_is_B | ab_label.by_stage_and_a_side | ab_label.confounding_notes | ab_label.contextual_accuracy_difference_confidence_interval_95 | ab_label.displayed_a_selection.confidence_interval_95 | ab_label.displayed_a_selection.count | ab_label.displayed_a_selection.eligible_count |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| — | — | — | — | [{"accuracy": null, "confidence_interval_95": null, "correct_answer_displayed_as": "A", "correct_count": 0, "eligible_count": 0}, {"accuracy": null, "confidence_interval_95": null, "correct_answer_displayed_as": "B", "correct_count": 0, "eligible_count": 0}] | — | [{"confidence_interval_95": null, "displayed_a_selection_count": 0, "displayed_a_selection_rate": null, "displayed_a_side": "PRO", "eligible_count": 0, "stage": "Round 1: True Tag"}, {"confidence_interval_95": null, "displayed_a_selection_count": 0, "displayed_a_selection_rate": null, "displayed_a_side": "CON", "eligible_count": 0, "stage": "Round 1: True Tag"}, {"confidence_interval_95": null, "displayed_a_selection_count": 0, "displayed_a_selection_rate": null, "displayed_a_side": "PRO", "eligible_count": 0, "stage": "Round 2: Unrelated Tag"}, {"confidence_interval_95": null, "displayed_a_selection_count": 0, "displayed_a_selection_rate": null, "displayed_a_side": "CON", "eligible_count": 0, "stage": "Round 2: Unrelated Tag"}, {"confidence_interval_95": null, "displayed_a_selection_count": 0, "displayed_a_selection_rate": null, "displayed_a_side": "PRO", "eligible_count": 0, "stage": "Round 3: Similar Tag"}, {"confidence_interval_95": null, "displayed_a_selection_count": 0, "displayed_a_selection_rate": null, "displayed_a_side": "CON", "eligible_count": 0, "stage": "Round 3: Similar Tag"}] | [] | — | — | 0 | 0 |
| — | — | — | — | [{"accuracy": 0.6693548387096774, "confidence_interval_95": [0.5825577946350449, 0.7459741259753707], "correct_answer_displayed_as": "A", "correct_count": 83, "eligible_count": 124}, {"accuracy": 0.6557377049180327, "confidence_interval_95": [0.5678346242942165, 0.7341326316174024], "correct_answer_displayed_as": "B", "correct_count": 80, "eligible_count": 122}] | 1.4% | [{"confidence_interval_95": [0.2109221407913507, 0.4548147985096737], "displayed_a_selection_count": 17, "displayed_a_selection_rate": 0.32075471698113206, "displayed_a_side": "PRO", "eligible_count": 53, "stage": "Round 1: True Tag"}, {"confidence_interval_95": [0.4185339926647454, 0.6540966587719579], "displayed_a_selection_count": 35, "displayed_a_selection_rate": 0.5384615384615384, "displayed_a_side": "CON", "eligible_count": 65, "stage": "Round 1: True Tag"}, {"confidence_interval_95": [0.060780601589980846, 0.23246448435174005], "displayed_a_selection_count": 7, "displayed_a_selection_rate": 0.12280701754385964, "displayed_a_side": "PRO", "eligible_count": 57, "stage": "Round 2: Unrelated Tag"}, {"confidence_interval_95": [0.8455098688621009, 0.969546397560289], "displayed_a_selection_count": 66, "displayed_a_selection_rate": 0.9295774647887324, "displayed_a_side": "CON", "eligible_count": 71, "stage": "Round 2: Unrelated Tag"}, {"confidence_interval_95": null, "displayed_a_selection_count": 0, "displayed_a_selection_rate": null, "displayed_a_side": "PRO", "eligible_count": 0, "stage": "Round 3: Similar Tag"}, {"confidence_interval_95": null, "displayed_a_selection_count": 0, "displayed_a_selection_rate": null, "displayed_a_side": "CON", "eligible_count": 0, "stage": "Round 3: Similar Tag"}] | ["Displayed A is also the first essay; label and position cannot be separated."] | [-0.10455431551977902, 0.1317885831030683] | [0.4460139819224683, 0.5699961711517288] | 125 | 246 |
| — | — | — | — | [{"accuracy": 0.5384615384615384, "confidence_interval_95": [0.44834691371990076, 0.626130836613735], "correct_answer_displayed_as": "A", "correct_count": 63, "eligible_count": 117}, {"accuracy": 0.6017699115044248, "confidence_interval_95": [0.509597946993007, 0.687249988937817], "correct_answer_displayed_as": "B", "correct_count": 68, "eligible_count": 113}] | -6.3% | [{"confidence_interval_95": [0.39720009365287134, 0.6151697969278761], "displayed_a_selection_count": 39, "displayed_a_selection_rate": 0.5064935064935064, "displayed_a_side": "PRO", "eligible_count": 77, "stage": "Round 1: True Tag"}, {"confidence_interval_95": [0.40069754605192803, 0.6256732547092813], "displayed_a_selection_count": 37, "displayed_a_selection_rate": 0.5138888888888888, "displayed_a_side": "CON", "eligible_count": 72, "stage": "Round 1: True Tag"}, {"confidence_interval_95": [0.10234437385158025, 0.3401358518706343], "displayed_a_selection_count": 8, "displayed_a_selection_rate": 0.1951219512195122, "displayed_a_side": "PRO", "eligible_count": 41, "stage": "Round 2: Unrelated Tag"}, {"confidence_interval_95": [0.44595893660346186, 0.7365167431570808], "displayed_a_selection_count": 24, "displayed_a_selection_rate": 0.6, "displayed_a_side": "CON", "eligible_count": 40, "stage": "Round 2: Unrelated Tag"}, {"confidence_interval_95": null, "displayed_a_selection_count": 0, "displayed_a_selection_rate": null, "displayed_a_side": "PRO", "eligible_count": 0, "stage": "Round 3: Similar Tag"}, {"confidence_interval_95": null, "displayed_a_selection_count": 0, "displayed_a_selection_rate": null, "displayed_a_side": "CON", "eligible_count": 0, "stage": "Round 3: Similar Tag"}] | ["The opening speaker is also the closing and two-turn speaker; first, last, and turn-count effects are confounded."] | [-0.19100483439178093, 0.06438808830600815] | [0.4060969254800542, 0.5340334514402552] | 108 | 230 |
| — | — | — | — | — | — | — | — | — | — | — | — |
| — | — | — | — | — | — | — | — | — | — | — | — |
| — | — | — | — | — | — | — | — | — | — | — | — |
| — | 0 | 0 | — | — | — | — | — | — | — | — | — |
| — | — | — | — | — | — | — | — | — | — | — | — |
| — | — | — | — | — | — | — | — | — | — | — | — |
| — | — | — | — | — | — | — | — | — | — | — | — |
| — | — | — | — | — | — | — | — | — | — | — | — |
| — | — | — | — | — | — | — | — | — | — | — | — |
| — | — | — | — | — | — | — | — | — | — | — | — |
| — | — | — | — | — | — | — | — | — | — | — | — |
| [0.4742778688382762, 0.5989400500853517] | 130 | 242 | 53.7% | — | — | — | — | — | — | — | — |
| — | — | — | — | — | — | — | — | — | — | — | — |
| — | — | — | — | — | — | — | — | — | — | — | — |
| — | — | — | — | — | — | — | — | — | — | — | — |
| — | — | — | — | — | — | — | — | — | — | — | — |
| — | — | — | — | — | — | — | — | — | — | — | — |
| — | — | — | — | — | — | — | — | — | — | — | — |
| — | — | — | — | — | — | — | — | — | — | — | — |
| [0.9835723791663494, 1.0] | 230 | 230 | 100.0% | — | — | — | — | — | — | — | — |
| — | — | — | — | — | — | — | — | — | — | — | — |
| — | — | — | — | — | — | — | — | — | — | — | — |
| — | — | — | — | — | — | — | — | — | — | — | — |
| — | — | — | — | — | — | — | — | — | — | — | — |
| — | — | — | — | — | — | — | — | — | — | — | — |
| — | — | — | — | — | — | — | — | — | — | — | — |
| — | — | — | — | — | — | — | — | — | — | — | — |

### Confidence and log-probability diagnostics

| available | available_counts.debater_ab_converted | available_counts.generated_prediction | available_counts.true_false | available_counts.yes_no | by_stage | complete_all_framings_count | complete_all_framings_coverage | condition_id | confidence_provenance | fallback_false_count | fallback_metrics |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| No | — | — | — | — | — | — | — | baseline.legacy_0.8B | Teacher-forced continuation scores from separate follow-up prompt framings; they are not probabilities extracted from the original generated explanation. | 0 | [] |
| No | — | — | — | — | — | — | — | statement.legacy_0.8B | Teacher-forced continuation scores from separate follow-up prompt framings; they are not probabilities extracted from the original generated explanation. | 0 | [] |
| No | — | — | — | — | — | — | — | interactive.legacy_0.8B.ABA | Teacher-forced continuation scores from separate follow-up prompt framings; they are not probabilities extracted from the original generated explanation. | 0 | [] |
| — | 0 | 703 | 0 | 0 | [{"agreement_count": 0, "agreement_rate": null, "eligible_count": 0, "left_framing": "generated_prediction", "right_framing": "yes_no", "stage": "Round 1: True Tag"}, {"agreement_count": 0, "agreement_rate": null, "eligible_count": 0, "left_framing": "generated_prediction", "right_framing": "true_false", "stage": "Round 1: True Tag"}, {"agreement_count": 0, "agreement_rate": null, "eligible_count": 0, "left_framing": "generated_prediction", "right_framing": "debater_ab_converted", "stage": "Round 1: True Tag"}, {"agreement_count": 0, "agreement_rate": null, "eligible_count": 0, "left_framing": "yes_no", "right_framing": "true_false", "stage": "Round 1: True Tag"}, {"agreement_count": 0, "agreement_rate": null, "eligible_count": 0, "left_framing": "yes_no", "right_framing": "debater_ab_converted", "stage": "Round 1: True Tag"}, {"agreement_count": 0, "agreement_rate": null, "eligible_count": 0, "left_framing": "true_false", "right_framing": "debater_ab_converted", "stage": "Round 1: True Tag"}, {"agreement_count": 0, "agreement_rate": null, "eligible_count": 0, "left_framing": "generated_prediction", "right_framing": "yes_no", "stage": "Round 2: Unrelated Tag"}, {"agreement_count": 0, "agreement_rate": null, "eligible_count": 0, "left_framing": "generated_prediction", "right_framing": "true_false", "stage": "Round 2: Unrelated Tag"}, {"agreement_count": 0, "agreement_rate": null, "eligible_count": 0, "left_framing": "generated_prediction", "right_framing": "debater_ab_converted", "stage": "Round 2: Unrelated Tag"}, {"agreement_count": 0, "agreement_rate": null, "eligible_count": 0, "left_framing": "yes_no", "right_framing": "true_false", "stage": "Round 2: Unrelated Tag"}, {"agreement_count": 0, "agreement_rate": null, "eligible_count": 0, "left_framing": "yes_no", "right_framing": "debater_ab_converted", "stage": "Round 2: Unrelated Tag"}, {"agreement_count": 0, "agreement_rate": null, "eligible_count": 0, "left_framing": "true_false", "right_framing": "debater_ab_converted", "stage": "Round 2: Unrelated Tag"}, {"agreement_count": 0, "agreement_rate": null, "eligible_count": 0, "left_framing": "generated_prediction", "right_framing": "yes_no", "stage": "Round 3: Similar Tag"}, {"agreement_count": 0, "agreement_rate": null, "eligible_count": 0, "left_framing": "generated_prediction", "right_framing": "true_false", "stage": "Round 3: Similar Tag"}, {"agreement_count": 0, "agreement_rate": null, "eligible_count": 0, "left_framing": "generated_prediction", "right_framing": "debater_ab_converted", "stage": "Round 3: Similar Tag"}, {"agreement_count": 0, "agreement_rate": null, "eligible_count": 0, "left_framing": "yes_no", "right_framing": "true_false", "stage": "Round 3: Similar Tag"}, {"agreement_count": 0, "agreement_rate": null, "eligible_count": 0, "left_framing": "yes_no", "right_framing": "debater_ab_converted", "stage": "Round 3: Similar Tag"}, {"agreement_count": 0, "agreement_rate": null, "eligible_count": 0, "left_framing": "true_false", "right_framing": "debater_ab_converted", "stage": "Round 3: Similar Tag"}] | 0 | 0.0% | — | — | — | — |
| — | 0 | 246 | 0 | 0 | [{"agreement_count": 0, "agreement_rate": null, "eligible_count": 0, "left_framing": "generated_prediction", "right_framing": "yes_no", "stage": "Round 1: True Tag"}, {"agreement_count": 0, "agreement_rate": null, "eligible_count": 0, "left_framing": "generated_prediction", "right_framing": "true_false", "stage": "Round 1: True Tag"}, {"agreement_count": 0, "agreement_rate": null, "eligible_count": 0, "left_framing": "generated_prediction", "right_framing": "debater_ab_converted", "stage": "Round 1: True Tag"}, {"agreement_count": 0, "agreement_rate": null, "eligible_count": 0, "left_framing": "yes_no", "right_framing": "true_false", "stage": "Round 1: True Tag"}, {"agreement_count": 0, "agreement_rate": null, "eligible_count": 0, "left_framing": "yes_no", "right_framing": "debater_ab_converted", "stage": "Round 1: True Tag"}, {"agreement_count": 0, "agreement_rate": null, "eligible_count": 0, "left_framing": "true_false", "right_framing": "debater_ab_converted", "stage": "Round 1: True Tag"}, {"agreement_count": 0, "agreement_rate": null, "eligible_count": 0, "left_framing": "generated_prediction", "right_framing": "yes_no", "stage": "Round 2: Unrelated Tag"}, {"agreement_count": 0, "agreement_rate": null, "eligible_count": 0, "left_framing": "generated_prediction", "right_framing": "true_false", "stage": "Round 2: Unrelated Tag"}, {"agreement_count": 0, "agreement_rate": null, "eligible_count": 0, "left_framing": "generated_prediction", "right_framing": "debater_ab_converted", "stage": "Round 2: Unrelated Tag"}, {"agreement_count": 0, "agreement_rate": null, "eligible_count": 0, "left_framing": "yes_no", "right_framing": "true_false", "stage": "Round 2: Unrelated Tag"}, {"agreement_count": 0, "agreement_rate": null, "eligible_count": 0, "left_framing": "yes_no", "right_framing": "debater_ab_converted", "stage": "Round 2: Unrelated Tag"}, {"agreement_count": 0, "agreement_rate": null, "eligible_count": 0, "left_framing": "true_false", "right_framing": "debater_ab_converted", "stage": "Round 2: Unrelated Tag"}, {"agreement_count": 0, "agreement_rate": null, "eligible_count": 0, "left_framing": "generated_prediction", "right_framing": "yes_no", "stage": "Round 3: Similar Tag"}, {"agreement_count": 0, "agreement_rate": null, "eligible_count": 0, "left_framing": "generated_prediction", "right_framing": "true_false", "stage": "Round 3: Similar Tag"}, {"agreement_count": 0, "agreement_rate": null, "eligible_count": 0, "left_framing": "generated_prediction", "right_framing": "debater_ab_converted", "stage": "Round 3: Similar Tag"}, {"agreement_count": 0, "agreement_rate": null, "eligible_count": 0, "left_framing": "yes_no", "right_framing": "true_false", "stage": "Round 3: Similar Tag"}, {"agreement_count": 0, "agreement_rate": null, "eligible_count": 0, "left_framing": "yes_no", "right_framing": "debater_ab_converted", "stage": "Round 3: Similar Tag"}, {"agreement_count": 0, "agreement_rate": null, "eligible_count": 0, "left_framing": "true_false", "right_framing": "debater_ab_converted", "stage": "Round 3: Similar Tag"}] | 0 | 0.0% | — | — | — | — |
| — | 0 | 230 | 0 | 0 | [{"agreement_count": 0, "agreement_rate": null, "eligible_count": 0, "left_framing": "generated_prediction", "right_framing": "yes_no", "stage": "Round 1: True Tag"}, {"agreement_count": 0, "agreement_rate": null, "eligible_count": 0, "left_framing": "generated_prediction", "right_framing": "true_false", "stage": "Round 1: True Tag"}, {"agreement_count": 0, "agreement_rate": null, "eligible_count": 0, "left_framing": "generated_prediction", "right_framing": "debater_ab_converted", "stage": "Round 1: True Tag"}, {"agreement_count": 0, "agreement_rate": null, "eligible_count": 0, "left_framing": "yes_no", "right_framing": "true_false", "stage": "Round 1: True Tag"}, {"agreement_count": 0, "agreement_rate": null, "eligible_count": 0, "left_framing": "yes_no", "right_framing": "debater_ab_converted", "stage": "Round 1: True Tag"}, {"agreement_count": 0, "agreement_rate": null, "eligible_count": 0, "left_framing": "true_false", "right_framing": "debater_ab_converted", "stage": "Round 1: True Tag"}, {"agreement_count": 0, "agreement_rate": null, "eligible_count": 0, "left_framing": "generated_prediction", "right_framing": "yes_no", "stage": "Round 2: Unrelated Tag"}, {"agreement_count": 0, "agreement_rate": null, "eligible_count": 0, "left_framing": "generated_prediction", "right_framing": "true_false", "stage": "Round 2: Unrelated Tag"}, {"agreement_count": 0, "agreement_rate": null, "eligible_count": 0, "left_framing": "generated_prediction", "right_framing": "debater_ab_converted", "stage": "Round 2: Unrelated Tag"}, {"agreement_count": 0, "agreement_rate": null, "eligible_count": 0, "left_framing": "yes_no", "right_framing": "true_false", "stage": "Round 2: Unrelated Tag"}, {"agreement_count": 0, "agreement_rate": null, "eligible_count": 0, "left_framing": "yes_no", "right_framing": "debater_ab_converted", "stage": "Round 2: Unrelated Tag"}, {"agreement_count": 0, "agreement_rate": null, "eligible_count": 0, "left_framing": "true_false", "right_framing": "debater_ab_converted", "stage": "Round 2: Unrelated Tag"}, {"agreement_count": 0, "agreement_rate": null, "eligible_count": 0, "left_framing": "generated_prediction", "right_framing": "yes_no", "stage": "Round 3: Similar Tag"}, {"agreement_count": 0, "agreement_rate": null, "eligible_count": 0, "left_framing": "generated_prediction", "right_framing": "true_false", "stage": "Round 3: Similar Tag"}, {"agreement_count": 0, "agreement_rate": null, "eligible_count": 0, "left_framing": "generated_prediction", "right_framing": "debater_ab_converted", "stage": "Round 3: Similar Tag"}, {"agreement_count": 0, "agreement_rate": null, "eligible_count": 0, "left_framing": "yes_no", "right_framing": "true_false", "stage": "Round 3: Similar Tag"}, {"agreement_count": 0, "agreement_rate": null, "eligible_count": 0, "left_framing": "yes_no", "right_framing": "debater_ab_converted", "stage": "Round 3: Similar Tag"}, {"agreement_count": 0, "agreement_rate": null, "eligible_count": 0, "left_framing": "true_false", "right_framing": "debater_ab_converted", "stage": "Round 3: Similar Tag"}] | 0 | 0.0% | — | — | — | — |
| No | — | — | — | — | — | — | — | — | Teacher-forced continuation scores from separate follow-up prompt framings; they are not probabilities extracted from the original generated explanation. | 0 | [] |
| No | — | — | — | — | — | — | — | — | Teacher-forced continuation scores from separate follow-up prompt framings; they are not probabilities extracted from the original generated explanation. | 0 | [] |
| No | — | — | — | — | — | — | — | — | Teacher-forced continuation scores from separate follow-up prompt framings; they are not probabilities extracted from the original generated explanation. | 0 | [] |
| No | — | — | — | — | — | — | — | — | Teacher-forced continuation scores from separate follow-up prompt framings; they are not probabilities extracted from the original generated explanation. | 0 | [] |
| No | — | — | — | — | — | — | — | — | Teacher-forced continuation scores from separate follow-up prompt framings; they are not probabilities extracted from the original generated explanation. | 0 | [] |
| No | — | — | — | — | — | — | — | — | Teacher-forced continuation scores from separate follow-up prompt framings; they are not probabilities extracted from the original generated explanation. | 0 | [] |

### Takeaways

- Baseline 0.8B — legacy: strict accuracy 39.87%, balanced accuracy 59.53%, valid-output coverage 59.13%.
- Statement — legacy: strict accuracy 11.09%, balanced accuracy 14.69%, valid-output coverage 16.73%.
- Interactive ABA — legacy: strict accuracy 10.73%, balanced accuracy 16.60%, valid-output coverage 18.84%.
- baseline_to_statement changed strict accuracy by -48.97 percentage points on 292 exact pairs, 95% PMID-clustered bootstrap CI [-55.14, -42.71] pp; this is a descriptive, confounded historical comparison.
- baseline_to_interactive changed strict accuracy by -38.16 percentage points on 228 exact pairs, 95% PMID-clustered bootstrap CI [-45.37, -30.97] pp; this is a descriptive, confounded historical comparison.
- statement_to_interactive changed strict accuracy by +2.62 percentage points on 1,221 exact pairs, 95% PMID-clustered bootstrap CI [+0.33, +4.88] pp; this is a descriptive, confounded historical comparison.
- Baseline 0.8B — legacy showed more false-negative/CON-side errors (FPR−FNR -40.64 pp).
- Statement — legacy showed more false-negative/CON-side errors (FPR−FNR -50.79 pp).
- Interactive ABA — legacy showed more false-negative/CON-side errors (FPR−FNR -20.71 pp).
- The audited legacy conditions expose no usable teacher-forced confidence fields, so log-probability accuracy and calibration are not applicable.

### Section-specific limitations

- Cross-generation comparisons change multiple implementation factors.
- The opening speaker is also the closing/two-turn speaker within this order.
- Displayed A is also the first essay; label and position cannot be separated.
- The opening speaker is also the closing and two-turn speaker; first, last, and turn-count effects are confounded.
- Legacy files are historical conditions and are not pooled with robust runs.
- Exact candidate matching does not make separately generated prompts, arguments, parsers, or retries identical.
- In legacy statement, displayed A and first position are confounded.
- In legacy ABA, A is first, last, and receives two turns; those effects cannot be separated.
- Raw Yes/PRO selection is not interpreted as bias without FPR/FNR or a controlled intervention.
- Unknown outputs count as failures in strict metrics and are excluded only in explicitly labelled valid-only metrics.

## 4. Baseline without manual vs with manual

### Paired comparisons

| A | B | Exact pairs | Accuracy Δ (B−A) | 95% CI | McNemar p | Status |
| --- | --- | --- | --- | --- | --- | --- |
| baseline without manual | baseline with manual | 3,000 | -3.2% | -4.7% to -1.6% | — | controlled |

### Bias and position diagnostics

| eligible | equal_length_records | first.eligible | first.selection_rate | last.eligible | last.selection_rate | longer_side_eligible | longer_side_selection_rate | mean_con_words | mean_pro_words | name | records_with_word_counts |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| — | — | 0 | — | 0 | — | — | — | — | — | position_selection | — |
| — | 0 | — | — | — | — | 0 | — | — | — | verbosity | 0 |
| 0 | — | — | — | — | — | — | — | — | — | first | — |
| 0 | — | — | — | — | — | — | — | — | — | last | — |
| 0 | — | — | — | — | — | — | — | — | — | two_turn | — |

### Confidence and log-probability diagnostics

| a_b.available_records | all_agree | caution | disagree | disagreement_rate | fallback_records | name | nonfallback_records | records_with_at_least_two_framings | true_false.available_records | true_false.brier_score | true_false.calibration_bins |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 0 | — | — | — | — | — | framings | — | — | 3,000 | 0.291 | [{"empirical_yes_rate": 0.0, "lower": 0.3, "mean_probability_yes": 0.38861802670584894, "records": 1, "upper": 0.4}, {"empirical_yes_rate": 0.033707865168539325, "lower": 0.4, "mean_probability_yes": 0.4723593103879789, "records": 89, "upper": 0.5}, {"empirical_yes_rate": 0.13959085439229843, "lower": 0.5, "mean_probability_yes": 0.5609447084083508, "records": 831, "upper": 0.6}, {"empirical_yes_rate": 0.37849079025549615, "lower": 0.6, "mean_probability_yes": 0.6472220849677963, "records": 1683, "upper": 0.7}, {"empirical_yes_rate": 0.6132315521628499, "lower": 0.7, "mean_probability_yes": 0.7272389828309227, "records": 393, "upper": 0.8}, {"empirical_yes_rate": 1.0, "lower": 0.8, "mean_probability_yes": 0.8039854600194883, "records": 3, "upper": 0.9}] |
| — | 2,910 | — | 90 | 3.0% | — | cross_framing | — | 3,000 | — | — | — |
| — | — | When fallback selected the final answer from Yes/No scores, prediction-confidence agreement is mechanically inflated. | — | — | 0 | fallback_strata | 3,000 | — | — | — | — |
| 0 | — | — | — | — | — | framings | — | — | 3,000 | 0.233 | [{"empirical_yes_rate": 0.0, "lower": 0.2, "mean_probability_yes": 0.2689414213699951, "records": 1, "upper": 0.3}, {"empirical_yes_rate": 0.015625, "lower": 0.3, "mean_probability_yes": 0.383850525764754, "records": 128, "upper": 0.4}, {"empirical_yes_rate": 0.27112092766427387, "lower": 0.4, "mean_probability_yes": 0.45898631882273105, "records": 1811, "upper": 0.5}, {"empirical_yes_rate": 0.4761450381679389, "lower": 0.5, "mean_probability_yes": 0.525968426740449, "records": 1048, "upper": 0.6}, {"empirical_yes_rate": 0.6666666666666666, "lower": 0.6, "mean_probability_yes": 0.6076187036025947, "records": 12, "upper": 0.7}] |
| — | 1,060 | — | 1,940 | 64.7% | — | cross_framing | — | 3,000 | — | — | — |
| — | — | When fallback selected the final answer from Yes/No scores, prediction-confidence agreement is mechanically inflated. | — | — | 0 | fallback_strata | 3,000 | — | — | — | — |

### Takeaways

- Effect of adding the NLM manual: the right-hand condition reduced paired strict accuracy by -3.17 percentage points across 3,000 exact matches; the clustered 95% interval excludes zero. Interpretation: controlled manual ablation after exact candidate verification.
- On similar negative tags, adding the manual changed paired accuracy by +1.20 percentage points.
- The fallback rate changed from 0.00% without the manual to 0.00% with it.

### Section-specific limitations

- The comparison is treated as controlled only for exact candidate matches.
- Teacher-forced confidence is analyzed separately from the generated verdict.
- Fallback confidence agreement is partly circular when fallback chose the verdict.

## 5. Older Pydantic implementation comparisons

### Paired comparisons

| A | B | Exact pairs | Accuracy Δ (B−A) | 95% CI | McNemar p | Status |
| --- | --- | --- | --- | --- | --- | --- |
| legacy baseline | older Pydantic baseline | 1,189 | 36.1% | +32.9% to +39.3% | — | confounded |
| older Pydantic baseline | robust with-manual baseline | 2,194 | 3.0% | +1.1% to +4.8% | — | confounded |
| legacy statement | older Pydantic statement | 639 | 61.3% | +57.1% to +65.5% | — | confounded |
| older Pydantic statement | robust statement | 2,158 | -16.8% | -19.3% to -14.3% | — | confounded |
| legacy interactive | older Pydantic interactive | 0 | — | — | — | confounded |
| older Pydantic interactive | corrected robust ABA | 0 | — | — | — | confounded |

### Bias and position diagnostics

| eligible | equal_length_records | first.eligible | first.selection_rate | last.eligible | last.selection_rate | longer_side_eligible | longer_side_selection_rate | mean_con_words | mean_pro_words | name | records_with_word_counts |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| — | — | 0 | — | 0 | — | — | — | — | — | position_selection | — |
| — | 0 | — | — | — | — | 0 | — | — | — | verbosity | 0 |
| 0 | — | — | — | — | — | — | — | — | — | first | — |
| 0 | — | — | — | — | — | — | — | — | — | last | — |
| 0 | — | — | — | — | — | — | — | — | — | two_turn | — |
| — | — | 2,871 | 50.4% | 2,871 | 49.6% | — | — | — | — | position_selection | — |
| — | 75 | — | — | — | — | 2,800 | 54.5% | 84.030 | 83.755 | verbosity | 3,000 |
| 2,871 | — | — | — | — | — | — | — | — | — | first | — |
| 2,871 | — | — | — | — | — | — | — | — | — | last | — |

### Confidence and log-probability diagnostics

| a_b.available_records | all_agree | caution | disagree | disagreement_rate | fallback_records | name | nonfallback_records | records_with_at_least_two_framings | true_false.available_records | yes_no.available_records | yes_no_fallback.available_records |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 0 | — | — | — | — | — | framings | — | — | 0 | 0 | — |
| — | 0 | — | 0 | — | — | cross_framing | — | 0 | — | — | — |
| — | — | When fallback selected the final answer from Yes/No scores, prediction-confidence agreement is mechanically inflated. | — | — | 0 | fallback_strata | 0 | — | — | — | 0 |

### Takeaways

- legacy baseline vs older Pydantic baseline: the right-hand condition improved paired strict accuracy by +36.08 percentage points across 1,189 exact matches; the clustered 95% interval excludes zero. Interpretation: descriptive/confounded implementation comparison; do not attribute the difference to Pydantic alone.
- older Pydantic baseline vs robust with-manual baseline: the right-hand condition improved paired strict accuracy by +2.96 percentage points across 2,194 exact matches; the clustered 95% interval excludes zero. Interpretation: descriptive/confounded implementation comparison; do not attribute the difference to Pydantic alone.
- legacy statement vs older Pydantic statement: the right-hand condition improved paired strict accuracy by +61.35 percentage points across 639 exact matches; the clustered 95% interval excludes zero. Interpretation: confounded: stored content mismatch detected.
- older Pydantic statement vs robust statement: the right-hand condition reduced paired strict accuracy by -16.82 percentage points across 2,158 exact matches; the clustered 95% interval excludes zero. Interpretation: confounded: stored content mismatch detected.
- legacy interactive vs older Pydantic interactive: no exact candidate-matched records were available.
- older Pydantic interactive vs corrected robust ABA: no exact candidate-matched records were available.

### Section-specific limitations

- Cross-generation comparisons change multiple implementation factors.
- The opening speaker is also the closing/two-turn speaker within this order.
- ABA and BAB transcripts were generated separately; their difference is not a pure order effect.
- These are implementation comparisons, not clean tests of Pydantic formatting.
- Strict and valid-only accuracy must both be shown when Unknowns occur.
- The interactive transcript-label issue can create a mapping-specific artifact.
- Log probabilities are unavailable for the older named Pydantic files.

## 6. Original 0.8B judge vs rejudged 2B judge

### Paired comparisons

| A | B | Exact pairs | Accuracy Δ (B−A) | 95% CI | McNemar p | Status |
| --- | --- | --- | --- | --- | --- | --- |
| statement judge 0.8B | statement judge 2B | 3,000 | 13.8% | +11.9% to +15.8% | — | controlled |
| interactive ABA judge 0.8B | interactive ABA judge 2B | 3,000 | 19.8% | +17.7% to +21.9% | — | controlled |
| interactive BAB judge 0.8B | interactive BAB judge 2B | 3,000 | 19.8% | +17.6% to +21.9% | — | controlled |
| older Pydantic statement | robust statement rejudged by 2B | 2,158 | 8.7% | +6.7% to +10.6% | — | confounded |
| older Pydantic interactive | robust ABA rejudged by 2B | 0 | — | — | — | confounded |

### Bias and position diagnostics

| bias.displayed_a_eligible | bias.displayed_a_selection_rate | bias.eligible_records | bias.false_negative_rate | bias.false_positive_rate | bias.fpr_minus_fnr | bias.position_selection.first.eligible | bias.position_selection.first.selection_rate | bias.position_selection.last.eligible | bias.position_selection.last.selection_rate | bias.position_selection.two_turn.eligible | bias.position_selection.two_turn.selection_rate |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 3,000 | 48.8% | 3,000 | 28.0% | 37.5% | 9.5% | 3,000 | 48.8% | 3,000 | 51.2% | 0 | — |
| 3,000 | 49.7% | 3,000 | 43.9% | 8.8% | -35.1% | 3,000 | 49.7% | 3,000 | 50.3% | 0 | — |
| 3,000 | 50.6% | 3,000 | 22.7% | 55.6% | 32.9% | 3,000 | 50.6% | 3,000 | 50.6% | 3,000 | 50.6% |
| 3,000 | 50.4% | 3,000 | 33.6% | 20.4% | -13.2% | 3,000 | 50.4% | 3,000 | 50.4% | 3,000 | 50.4% |
| 3,000 | 46.5% | 3,000 | 21.9% | 57.6% | 35.7% | 3,000 | 53.5% | 3,000 | 53.5% | 3,000 | 53.5% |
| 3,000 | 47.4% | 3,000 | 26.8% | 25.4% | -1.4% | 3,000 | 52.6% | 3,000 | 52.6% | 3,000 | 52.6% |
| — | — | — | — | — | — | — | — | — | — | — | — |
| — | — | — | — | — | — | — | — | — | — | — | — |
| — | — | — | — | — | — | — | — | — | — | — | — |
| — | — | — | — | — | — | — | — | — | — | — | — |
| — | — | — | — | — | — | — | — | — | — | — | — |
| — | — | — | — | — | — | — | — | — | — | — | — |
| — | — | — | — | — | — | — | — | — | — | — | — |
| — | — | — | — | — | — | — | — | — | — | — | — |
| — | — | — | — | — | — | — | — | — | — | — | — |
| — | — | — | — | — | — | — | — | — | — | — | — |
| — | — | — | — | — | — | — | — | — | — | — | — |
| — | — | — | — | — | — | — | — | — | — | — | — |
| — | — | — | — | — | — | — | — | — | — | — | — |
| — | — | — | — | — | — | — | — | — | — | — | — |
| — | — | — | — | — | — | — | — | — | — | — | — |
| — | — | — | — | — | — | — | — | — | — | — | — |
| — | — | — | — | — | — | — | — | — | — | — | — |
| — | — | — | — | — | — | — | — | — | — | — | — |
| — | — | — | — | — | — | — | — | — | — | — | — |
| — | — | — | — | — | — | — | — | — | — | — | — |
| — | — | — | — | — | — | — | — | — | — | — | — |
| — | — | — | — | — | — | — | — | — | — | — | — |
| — | — | — | — | — | — | — | — | — | — | — | — |
| — | — | — | — | — | — | — | — | — | — | — | — |

### Confidence and log-probability diagnostics

| a_b.available_records | a_b.brier_score | a_b.calibration_bins | a_b.expected_calibration_error_10_bins | a_b.generated_prediction_agreement | a_b.high_confidence_error_count_at_0_9 | a_b.mean_threshold_confidence_correct | a_b.mean_threshold_confidence_error | a_b.negative_log_likelihood | a_b.roc_auc | a_b.threshold_accuracy | all_agree |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| — | — | — | — | — | — | — | — | — | — | — | — |
| — | — | — | — | — | — | — | — | — | — | — | — |
| — | — | — | — | — | — | — | — | — | — | — | — |
| — | — | — | — | — | — | — | — | — | — | — | — |
| — | — | — | — | — | — | — | — | — | — | — | — |
| — | — | — | — | — | — | — | — | — | — | — | — |
| 3,000 | 0.335 | [{"empirical_yes_rate": 0.2037037037037037, "lower": 0.0, "mean_probability_yes": 0.08132295910989852, "records": 54, "upper": 0.1}, {"empirical_yes_rate": 0.22394678492239467, "lower": 0.1, "mean_probability_yes": 0.15702488533772133, "records": 451, "upper": 0.2}, {"empirical_yes_rate": 0.365234375, "lower": 0.2, "mean_probability_yes": 0.2460039051445298, "records": 512, "upper": 0.3}, {"empirical_yes_rate": 0.4409722222222222, "lower": 0.3, "mean_probability_yes": 0.3401596226276717, "records": 288, "upper": 0.4}, {"empirical_yes_rate": 0.42727272727272725, "lower": 0.4, "mean_probability_yes": 0.44168846340066914, "records": 110, "upper": 0.5}, {"empirical_yes_rate": 0.4186046511627907, "lower": 0.5, "mean_probability_yes": 0.5565196271829962, "records": 86, "upper": 0.6}, {"empirical_yes_rate": 0.3791469194312796, "lower": 0.6, "mean_probability_yes": 0.6608132199909057, "records": 211, "upper": 0.7}, {"empirical_yes_rate": 0.35608856088560886, "lower": 0.7, "mean_probability_yes": 0.7556831850266813, "records": 542, "upper": 0.8}, {"empirical_yes_rate": 0.3, "lower": 0.8, "mean_probability_yes": 0.8453904568886664, "records": 660, "upper": 0.9}, {"empirical_yes_rate": 0.23255813953488372, "lower": 0.9, "mean_probability_yes": 0.9174262629122378, "records": 86, "upper": 1.0}] | 0.278 | 49.2% | 77 | 0.767 | 0.767 | 0.920 | 0.512 | 49.0% | — |
| — | — | — | — | — | — | — | — | — | — | — | 627 |
| — | — | — | — | — | — | — | — | — | — | — | — |
| 3,000 | 0.306 | [{"empirical_yes_rate": 0.4222222222222222, "lower": 0.1, "mean_probability_yes": 0.17339277502326536, "records": 180, "upper": 0.2}, {"empirical_yes_rate": 0.30842391304347827, "lower": 0.2, "mean_probability_yes": 0.2521873217793772, "records": 736, "upper": 0.3}, {"empirical_yes_rate": 0.3263888888888889, "lower": 0.3, "mean_probability_yes": 0.3413991484693613, "records": 432, "upper": 0.4}, {"empirical_yes_rate": 0.38202247191011235, "lower": 0.4, "mean_probability_yes": 0.442475114262022, "records": 89, "upper": 0.5}, {"empirical_yes_rate": 0.4065040650406504, "lower": 0.5, "mean_probability_yes": 0.5609066451301534, "records": 123, "upper": 0.6}, {"empirical_yes_rate": 0.3157894736842105, "lower": 0.6, "mean_probability_yes": 0.6614185809786859, "records": 456, "upper": 0.7}, {"empirical_yes_rate": 0.3006535947712418, "lower": 0.7, "mean_probability_yes": 0.747706180634324, "records": 765, "upper": 0.8}, {"empirical_yes_rate": 0.44495412844036697, "lower": 0.8, "mean_probability_yes": 0.8259691857625325, "records": 218, "upper": 0.9}, {"empirical_yes_rate": 1.0, "lower": 0.9, "mean_probability_yes": 0.9001793324323768, "records": 1, "upper": 1.0}] | 0.233 | 49.7% | 0 | 0.719 | 0.719 | 0.826 | 0.502 | 49.4% | — |
| — | — | — | — | — | — | — | — | — | — | — | 1,363 |
| — | — | — | — | — | — | — | — | — | — | — | — |
| 3,000 | 0.364 | [{"empirical_yes_rate": 0.25949367088607594, "lower": 0.0, "mean_probability_yes": 0.08423047057938973, "records": 158, "upper": 0.1}, {"empirical_yes_rate": 0.31025957972805934, "lower": 0.1, "mean_probability_yes": 0.15025681754058576, "records": 809, "upper": 0.2}, {"empirical_yes_rate": 0.39849624060150374, "lower": 0.2, "mean_probability_yes": 0.23961812247299194, "records": 399, "upper": 0.3}, {"empirical_yes_rate": 0.45614035087719296, "lower": 0.3, "mean_probability_yes": 0.33910705042971045, "records": 114, "upper": 0.4}, {"empirical_yes_rate": 0.325, "lower": 0.4, "mean_probability_yes": 0.4429252761282713, "records": 40, "upper": 0.5}, {"empirical_yes_rate": 0.5714285714285714, "lower": 0.5, "mean_probability_yes": 0.5555529697428092, "records": 28, "upper": 0.6}, {"empirical_yes_rate": 0.4772727272727273, "lower": 0.6, "mean_probability_yes": 0.6578948442923456, "records": 88, "upper": 0.7}, {"empirical_yes_rate": 0.43874643874643876, "lower": 0.7, "mean_probability_yes": 0.7587793185796902, "records": 351, "upper": 0.8}, {"empirical_yes_rate": 0.28211284513805523, "lower": 0.8, "mean_probability_yes": 0.8510394429379932, "records": 833, "upper": 0.9}, {"empirical_yes_rate": 0.20555555555555555, "lower": 0.9, "mean_probability_yes": 0.917903991215582, "records": 180, "upper": 1.0}] | 0.323 | 50.6% | 184 | 0.811 | 0.821 | 1.018 | 0.480 | 49.6% | — |
| — | — | — | — | — | — | — | — | — | — | — | 1,128 |
| — | — | — | — | — | — | — | — | — | — | — | — |
| 3,000 | 0.329 | [{"empirical_yes_rate": 0.3076923076923077, "lower": 0.0, "mean_probability_yes": 0.09207233645286493, "records": 13, "upper": 0.1}, {"empirical_yes_rate": 0.3037974683544304, "lower": 0.1, "mean_probability_yes": 0.16435643109910986, "records": 632, "upper": 0.2}, {"empirical_yes_rate": 0.34796238244514105, "lower": 0.2, "mean_probability_yes": 0.24047540804060957, "records": 638, "upper": 0.3}, {"empirical_yes_rate": 0.4020100502512563, "lower": 0.3, "mean_probability_yes": 0.3365721946517291, "records": 199, "upper": 0.4}, {"empirical_yes_rate": 0.4888888888888889, "lower": 0.4, "mean_probability_yes": 0.44308315973518286, "records": 45, "upper": 0.5}, {"empirical_yes_rate": 0.4745762711864407, "lower": 0.5, "mean_probability_yes": 0.5572840918820564, "records": 59, "upper": 0.6}, {"empirical_yes_rate": 0.3877551020408163, "lower": 0.6, "mean_probability_yes": 0.6613584080048301, "records": 196, "upper": 0.7}, {"empirical_yes_rate": 0.3218562874251497, "lower": 0.7, "mean_probability_yes": 0.7566594382432512, "records": 668, "upper": 0.8}, {"empirical_yes_rate": 0.29259259259259257, "lower": 0.8, "mean_probability_yes": 0.8372724339129054, "records": 540, "upper": 0.9}, {"empirical_yes_rate": 0.3, "lower": 0.9, "mean_probability_yes": 0.9042714079710755, "records": 10, "upper": 1.0}] | 0.275 | 50.3% | 11 | 0.772 | 0.769 | 0.894 | 0.496 | 49.6% | — |
| — | — | — | — | — | — | — | — | — | — | — | 1,518 |
| — | — | — | — | — | — | — | — | — | — | — | — |
| 3,000 | 0.275 | [{"empirical_yes_rate": 0.6666666666666666, "lower": 0.0, "mean_probability_yes": 0.09408932432984614, "records": 3, "upper": 0.1}, {"empirical_yes_rate": 0.24752475247524752, "lower": 0.1, "mean_probability_yes": 0.17004045328209014, "records": 101, "upper": 0.2}, {"empirical_yes_rate": 0.31290322580645163, "lower": 0.2, "mean_probability_yes": 0.25810592701094176, "records": 310, "upper": 0.3}, {"empirical_yes_rate": 0.29191321499013806, "lower": 0.3, "mean_probability_yes": 0.35340339536521187, "records": 507, "upper": 0.4}, {"empirical_yes_rate": 0.35688405797101447, "lower": 0.4, "mean_probability_yes": 0.45077875346468393, "records": 552, "upper": 0.5}, {"empirical_yes_rate": 0.397708674304419, "lower": 0.5, "mean_probability_yes": 0.5493103431965607, "records": 611, "upper": 0.6}, {"empirical_yes_rate": 0.327683615819209, "lower": 0.6, "mean_probability_yes": 0.647764930966645, "records": 531, "upper": 0.7}, {"empirical_yes_rate": 0.29754601226993865, "lower": 0.7, "mean_probability_yes": 0.7441284051791958, "records": 326, "upper": 0.8}, {"empirical_yes_rate": 0.27586206896551724, "lower": 0.8, "mean_probability_yes": 0.8262720220662306, "records": 58, "upper": 0.9}, {"empirical_yes_rate": 1.0, "lower": 0.9, "mean_probability_yes": 0.9520418961921002, "records": 1, "upper": 1.0}] | 0.183 | 50.2% | 2 | 0.639 | 0.640 | 0.752 | 0.509 | 51.2% | — |
| — | — | — | — | — | — | — | — | — | — | — | 1,227 |
| — | — | — | — | — | — | — | — | — | — | — | — |
| 3,000 | 0.335 | [{"empirical_yes_rate": 0.15384615384615385, "lower": 0.0, "mean_probability_yes": 0.08901796213696216, "records": 13, "upper": 0.1}, {"empirical_yes_rate": 0.2841068917018284, "lower": 0.1, "mean_probability_yes": 0.16048746118112162, "records": 711, "upper": 0.2}, {"empirical_yes_rate": 0.3766478342749529, "lower": 0.2, "mean_probability_yes": 0.2396300779167502, "records": 531, "upper": 0.3}, {"empirical_yes_rate": 0.4407894736842105, "lower": 0.3, "mean_probability_yes": 0.3415008026445372, "records": 152, "upper": 0.4}, {"empirical_yes_rate": 0.3709677419354839, "lower": 0.4, "mean_probability_yes": 0.4475994432851574, "records": 62, "upper": 0.5}, {"empirical_yes_rate": 0.4675324675324675, "lower": 0.5, "mean_probability_yes": 0.5487711269793548, "records": 77, "upper": 0.6}, {"empirical_yes_rate": 0.3875, "lower": 0.6, "mean_probability_yes": 0.6619442565832448, "records": 160, "upper": 0.7}, {"empirical_yes_rate": 0.3301282051282051, "lower": 0.7, "mean_probability_yes": 0.7608380823995334, "records": 624, "upper": 0.8}, {"empirical_yes_rate": 0.30257186081694404, "lower": 0.8, "mean_probability_yes": 0.837603470274226, "records": 661, "upper": 0.9}, {"empirical_yes_rate": 0.2222222222222222, "lower": 0.9, "mean_probability_yes": 0.9136141212135698, "records": 9, "upper": 1.0}] | 0.287 | 47.9% | 9 | 0.779 | 0.776 | 0.911 | 0.503 | 49.4% | — |
| — | — | — | — | — | — | — | — | — | — | — | 1,426 |
| — | — | — | — | — | — | — | — | — | — | — | — |

### Takeaways

- statement judge 2B: the right-hand condition improved paired strict accuracy by +13.83 percentage points across 3,000 exact matches; the clustered 95% interval excludes zero. Interpretation: controlled judge-size comparison conditional on identical stored essays.
- interactive ABA judge 2B: the right-hand condition improved paired strict accuracy by +19.80 percentage points across 3,000 exact matches; the clustered 95% interval excludes zero. Interpretation: controlled judge-size comparison conditional on identical ABA transcript; stored content unavailable for verification.
- interactive BAB judge 2B: the right-hand condition improved paired strict accuracy by +19.77 percentage points across 3,000 exact matches; the clustered 95% interval excludes zero. Interpretation: controlled judge-size comparison conditional on identical BAB transcript; stored content unavailable for verification.
- robust statement rejudged by 2B: the right-hand condition improved paired strict accuracy by +8.67 percentage points across 2,158 exact matches; the clustered 95% interval excludes zero. Interpretation: confounded: stored content mismatch detected.
- robust ABA rejudged by 2B: no exact candidate-matched records were available.

### Section-specific limitations

- Cross-generation comparisons change multiple implementation factors.
- The opening speaker is also the closing/two-turn speaker within this order.
- ABA and BAB transcripts were generated separately; their difference is not a pure order effect.
- The 2B judge has the same nominal size as the debaters, so this no longer represents the original weak-judge scalable-oversight setting.
- Never attribute these historical differences to judge size alone.
- A primary result is controlled only where stored content is verified identical.
- The 2B-vs-Pydantic comparisons are historical and multi-factor.
- Confidence scores are teacher-forced follow-up scores, not the original verdict token probability.

## 7. ABA, BAB, and swapped BAB labels

### Paired comparisons

| A | B | Exact pairs | Accuracy Δ (B−A) | 95% CI | McNemar p | Status |
| --- | --- | --- | --- | --- | --- | --- |
| original BAB labels | BAB with displayed labels swapped | 3,000 | 0.3% | -1.5% to +2.0% | — | controlled |
| interactive ABA | interactive BAB | 3,000 | -1.0% | -3.3% to +1.2% | — | confounded |
| original BAB labels | BAB with displayed labels swapped | 3,000 | 0.3% | -1.5% to +2.0% | — | controlled |
| 2B judge on ABA | 2B judge on BAB | 3,000 | -1.1% | -3.1% to +1.0% | — | confounded |

### Bias and position diagnostics

| eligible | equal_length_records | first.eligible | first.selection_rate | last.eligible | last.selection_rate | longer_side_eligible | longer_side_selection_rate | mean_con_words | mean_pro_words | name | records_with_word_counts |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| — | — | 3,000 | 50.6% | 3,000 | 50.6% | — | — | — | — | position_selection | — |
| — | 1 | — | — | — | — | 2,999 | 50.5% | 140.019 | 140.898 | verbosity | 3,000 |
| 3,000 | — | — | — | — | — | — | — | — | — | first | — |
| 3,000 | — | — | — | — | — | — | — | — | — | last | — |
| 3,000 | — | — | — | — | — | — | — | — | — | two_turn | — |
| — | — | 3,000 | 53.5% | 3,000 | 53.5% | — | — | — | — | position_selection | — |
| — | 0 | — | — | — | — | 3,000 | 53.6% | 154.521 | 170.031 | verbosity | 3,000 |
| 3,000 | — | — | — | — | — | — | — | — | — | first | — |
| 3,000 | — | — | — | — | — | — | — | — | — | last | — |
| 3,000 | — | — | — | — | — | — | — | — | — | two_turn | — |
| — | — | 3,000 | 53.1% | 3,000 | 53.1% | — | — | — | — | position_selection | — |
| — | 0 | — | — | — | — | 3,000 | 53.1% | 154.521 | 170.031 | verbosity | 3,000 |
| 3,000 | — | — | — | — | — | — | — | — | — | first | — |
| 3,000 | — | — | — | — | — | — | — | — | — | last | — |
| 3,000 | — | — | — | — | — | — | — | — | — | two_turn | — |

### Confidence and log-probability diagnostics

| a_b.available_records | a_b.brier_score | a_b.calibration_bins | a_b.expected_calibration_error_10_bins | a_b.generated_prediction_agreement | a_b.high_confidence_error_count_at_0_9 | a_b.mean_threshold_confidence_correct | a_b.mean_threshold_confidence_error | a_b.negative_log_likelihood | a_b.roc_auc | a_b.threshold_accuracy | all_agree |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 3,000 | 0.364 | [{"empirical_yes_rate": 0.25949367088607594, "lower": 0.0, "mean_probability_yes": 0.08423047057938973, "records": 158, "upper": 0.1}, {"empirical_yes_rate": 0.31025957972805934, "lower": 0.1, "mean_probability_yes": 0.15025681754058576, "records": 809, "upper": 0.2}, {"empirical_yes_rate": 0.39849624060150374, "lower": 0.2, "mean_probability_yes": 0.23961812247299194, "records": 399, "upper": 0.3}, {"empirical_yes_rate": 0.45614035087719296, "lower": 0.3, "mean_probability_yes": 0.33910705042971045, "records": 114, "upper": 0.4}, {"empirical_yes_rate": 0.325, "lower": 0.4, "mean_probability_yes": 0.4429252761282713, "records": 40, "upper": 0.5}, {"empirical_yes_rate": 0.5714285714285714, "lower": 0.5, "mean_probability_yes": 0.5555529697428092, "records": 28, "upper": 0.6}, {"empirical_yes_rate": 0.4772727272727273, "lower": 0.6, "mean_probability_yes": 0.6578948442923456, "records": 88, "upper": 0.7}, {"empirical_yes_rate": 0.43874643874643876, "lower": 0.7, "mean_probability_yes": 0.7587793185796902, "records": 351, "upper": 0.8}, {"empirical_yes_rate": 0.28211284513805523, "lower": 0.8, "mean_probability_yes": 0.8510394429379932, "records": 833, "upper": 0.9}, {"empirical_yes_rate": 0.20555555555555555, "lower": 0.9, "mean_probability_yes": 0.917903991215582, "records": 180, "upper": 1.0}] | 0.323 | 50.6% | 184 | 0.811 | 0.821 | 1.018 | 0.480 | 49.6% | — |
| — | — | — | — | — | — | — | — | — | — | — | 1,128 |
| — | — | — | — | — | — | — | — | — | — | — | — |
| 3,000 | 0.275 | [{"empirical_yes_rate": 0.6666666666666666, "lower": 0.0, "mean_probability_yes": 0.09408932432984614, "records": 3, "upper": 0.1}, {"empirical_yes_rate": 0.24752475247524752, "lower": 0.1, "mean_probability_yes": 0.17004045328209014, "records": 101, "upper": 0.2}, {"empirical_yes_rate": 0.31290322580645163, "lower": 0.2, "mean_probability_yes": 0.25810592701094176, "records": 310, "upper": 0.3}, {"empirical_yes_rate": 0.29191321499013806, "lower": 0.3, "mean_probability_yes": 0.35340339536521187, "records": 507, "upper": 0.4}, {"empirical_yes_rate": 0.35688405797101447, "lower": 0.4, "mean_probability_yes": 0.45077875346468393, "records": 552, "upper": 0.5}, {"empirical_yes_rate": 0.397708674304419, "lower": 0.5, "mean_probability_yes": 0.5493103431965607, "records": 611, "upper": 0.6}, {"empirical_yes_rate": 0.327683615819209, "lower": 0.6, "mean_probability_yes": 0.647764930966645, "records": 531, "upper": 0.7}, {"empirical_yes_rate": 0.29754601226993865, "lower": 0.7, "mean_probability_yes": 0.7441284051791958, "records": 326, "upper": 0.8}, {"empirical_yes_rate": 0.27586206896551724, "lower": 0.8, "mean_probability_yes": 0.8262720220662306, "records": 58, "upper": 0.9}, {"empirical_yes_rate": 1.0, "lower": 0.9, "mean_probability_yes": 0.9520418961921002, "records": 1, "upper": 1.0}] | 0.183 | 50.2% | 2 | 0.639 | 0.640 | 0.752 | 0.509 | 51.2% | — |
| — | — | — | — | — | — | — | — | — | — | — | 1,227 |
| — | — | — | — | — | — | — | — | — | — | — | — |
| 3,000 | 0.343 | [{"empirical_yes_rate": 0.24210526315789474, "lower": 0.0, "mean_probability_yes": 0.08187597694975128, "records": 95, "upper": 0.1}, {"empirical_yes_rate": 0.3353028064992615, "lower": 0.1, "mean_probability_yes": 0.15122790638352998, "records": 677, "upper": 0.2}, {"empirical_yes_rate": 0.34854771784232363, "lower": 0.2, "mean_probability_yes": 0.24357822149370306, "records": 482, "upper": 0.3}, {"empirical_yes_rate": 0.2974683544303797, "lower": 0.3, "mean_probability_yes": 0.3329733569203423, "records": 158, "upper": 0.4}, {"empirical_yes_rate": 0.22413793103448276, "lower": 0.4, "mean_probability_yes": 0.44420534424638014, "records": 58, "upper": 0.5}, {"empirical_yes_rate": 0.4025974025974026, "lower": 0.5, "mean_probability_yes": 0.5498852940070917, "records": 77, "upper": 0.6}, {"empirical_yes_rate": 0.358974358974359, "lower": 0.6, "mean_probability_yes": 0.6578488372082939, "records": 156, "upper": 0.7}, {"empirical_yes_rate": 0.3201754385964912, "lower": 0.7, "mean_probability_yes": 0.7615466526637439, "records": 456, "upper": 0.8}, {"empirical_yes_rate": 0.34285714285714286, "lower": 0.8, "mean_probability_yes": 0.8469388230537656, "records": 700, "upper": 0.9}, {"empirical_yes_rate": 0.3475177304964539, "lower": 0.9, "mean_probability_yes": 0.916916868290815, "records": 141, "upper": 1.0}] | 0.300 | 53.1% | 115 | 0.791 | 0.795 | 0.952 | 0.506 | 50.5% | — |
| — | — | — | — | — | — | — | — | — | — | — | 1,210 |
| — | — | — | — | — | — | — | — | — | — | — | — |

### Prediction patterns

| correctness_--- | correctness_--S | correctness_-B- | correctness_-BS | correctness_A-- | correctness_A-S | correctness_AB- | correctness_ABS | count | pattern | share_within_stage | stage |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 600 | — | — | — | — | — | — | 894 | 1,494 | ABA = BAB = swapped | 0.498 | ALL |
| — | 181 | — | — | — | — | 178 | — | 359 | ABA = BAB; swapped differs | 0.120 | ALL |
| — | — | 197 | — | — | 202 | — | — | 399 | ABA = swapped; BAB differs | 0.133 | ALL |
| — | — | — | 361 | 387 | — | — | — | 748 | ABA differs; BAB = swapped | 0.249 | ALL |
| 50 | — | — | — | — | — | — | 581 | 631 | ABA = BAB = swapped | 0.631 | Round 1: True Tag |
| — | 28 | — | — | — | — | 51 | — | 79 | ABA = BAB; swapped differs | 0.079 | Round 1: True Tag |
| — | — | 21 | — | — | 60 | — | — | 81 | ABA = swapped; BAB differs | 0.081 | Round 1: True Tag |
| — | — | — | 128 | 81 | — | — | — | 209 | ABA differs; BAB = swapped | 0.209 | Round 1: True Tag |
| 242 | — | — | — | — | — | — | 176 | 418 | ABA = BAB = swapped | 0.418 | Round 2: Unrelated Tag |
| — | 87 | — | — | — | — | 66 | — | 153 | ABA = BAB; swapped differs | 0.153 | Round 2: Unrelated Tag |
| — | — | 94 | — | — | 69 | — | — | 163 | ABA = swapped; BAB differs | 0.163 | Round 2: Unrelated Tag |
| — | — | — | 117 | 149 | — | — | — | 266 | ABA differs; BAB = swapped | 0.266 | Round 2: Unrelated Tag |
| 308 | — | — | — | — | — | — | 137 | 445 | ABA = BAB = swapped | 0.445 | Round 3: Similar Tag |
| — | 66 | — | — | — | — | 61 | — | 127 | ABA = BAB; swapped differs | 0.127 | Round 3: Similar Tag |
| — | — | 82 | — | — | 73 | — | — | 155 | ABA = swapped; BAB differs | 0.155 | Round 3: Similar Tag |
| — | — | — | 116 | 157 | — | — | — | 273 | ABA differs; BAB = swapped | 0.273 | Round 3: Similar Tag |

### Takeaways

- ABA versus BAB: the right-hand condition changed paired strict accuracy by -1.03 percentage points across 3,000 exact matches; the clustered 95% interval includes zero or is unavailable. Interpretation: order/content comparison: ABA and BAB transcripts were generated separately, so speaking order and turn allocation are confounded with argument quality.
- BAB displayed-label swap: the right-hand condition changed paired strict accuracy by +0.27 percentage points across 3,000 exact matches; the clustered 95% interval includes zero or is unavailable. Interpretation: clean displayed-label test conditional on fixed-content verification; stored content unavailable for verification.
- 2B ABA versus BAB: the right-hand condition changed paired strict accuracy by -1.07 percentage points across 3,000 exact matches; the clustered 95% interval includes zero or is unavailable. Interpretation: order/content comparison: fixed judge but separately generated ABA/BAB transcripts still confound order with argument quality.

### Section-specific limitations

- The opening speaker is also the closing/two-turn speaker within this order.
- ABA and BAB transcripts were generated separately; their difference is not a pure order effect.
- Treat as a clean label test only after byte-level content/order verification.
- ABA-vs-BAB is not a pure order intervention because its arguments were generated separately.
- BAB-vs-swapped is the clean label test only where physical transcript equality is verified.
- A/first/last/two-turn effects are structurally confounded within one three-turn order.
- The normalized duplicate swapped-BAB file is excluded as an independent condition.

## 8. Cross-condition confidence/log-probability overview

| framing | threshold_accuracy | roc_auc | brier_score | negative_log_likelihood | expected_calibration_error | argmax_confidence_ece | complete_all_framings_count | condition_id | confidence_provenance | coverage | coverage_within_scope |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| — | — | — | — | — | — | — | — | asymmetric_titleonly.baseline | Teacher-forced continuation scores from separate follow-up prompt framings; they are not probabilities extracted from the original generated explanation. | — | — |
| — | — | — | — | — | — | — | — | asymmetric_titleonly.interactive.ABA | Teacher-forced continuation scores from separate follow-up prompt framings; they are not probabilities extracted from the original generated explanation. | — | — |
| — | — | — | — | — | — | — | — | asymmetric_titleonly.statement | Teacher-forced continuation scores from separate follow-up prompt framings; they are not probabilities extracted from the original generated explanation. | — | — |
| — | — | — | — | — | — | — | — | baseline.legacy_0.8B | Teacher-forced continuation scores from separate follow-up prompt framings; they are not probabilities extracted from the original generated explanation. | — | — |
| — | — | — | — | — | — | — | — | baseline.older_pydantic_0.8B | Teacher-forced continuation scores from separate follow-up prompt framings; they are not probabilities extracted from the original generated explanation. | — | — |
| yes_no | 33.3% | 0.780 | 0.604 | 2.076 | 0.624 | 62.4% | 0 | baseline.robust_0.8B.no_manual | Teacher-forced continuation scores from separate follow-up prompt framings; they are not probabilities extracted from the original generated explanation. | 100.0% | — |
| true_false | 36.1% | 0.726 | 0.291 | 0.779 | 0.296 | 29.6% | 0 | baseline.robust_0.8B.no_manual | Teacher-forced continuation scores from separate follow-up prompt framings; they are not probabilities extracted from the original generated explanation. | 100.0% | — |
| yes_no | 33.3% | 0.780 | 0.604 | 2.076 | 0.624 | 62.4% | — | baseline.robust_0.8B.no_manual | Teacher-forced continuation scores from separate follow-up prompt framings; they are not probabilities extracted from the original generated explanation. | — | 100.0% |
| true_false | 36.1% | 0.726 | 0.291 | 0.779 | 0.296 | 29.6% | — | baseline.robust_0.8B.no_manual | Teacher-forced continuation scores from separate follow-up prompt framings; they are not probabilities extracted from the original generated explanation. | — | 100.0% |
| yes_no | 33.3% | 0.794 | 0.621 | 2.258 | 0.634 | 63.4% | 0 | baseline.robust_0.8B.with_manual | Teacher-forced continuation scores from separate follow-up prompt framings; they are not probabilities extracted from the original generated explanation. | 100.0% | — |
| true_false | 65.1% | 0.677 | 0.233 | 0.660 | 0.147 | 14.7% | 0 | baseline.robust_0.8B.with_manual | Teacher-forced continuation scores from separate follow-up prompt framings; they are not probabilities extracted from the original generated explanation. | 100.0% | — |
| yes_no | 33.3% | 0.794 | 0.621 | 2.258 | 0.634 | 63.4% | — | baseline.robust_0.8B.with_manual | Teacher-forced continuation scores from separate follow-up prompt framings; they are not probabilities extracted from the original generated explanation. | — | 100.0% |
| true_false | 65.1% | 0.677 | 0.233 | 0.660 | 0.147 | 14.7% | — | baseline.robust_0.8B.with_manual | Teacher-forced continuation scores from separate follow-up prompt framings; they are not probabilities extracted from the original generated explanation. | — | 100.0% |
| yes_no | 67.4% | 0.892 | 0.210 | 0.606 | 0.211 | 21.1% | 0 | baseline.robust_2B.no_manual | Teacher-forced continuation scores from separate follow-up prompt framings; they are not probabilities extracted from the original generated explanation. | 100.0% | — |
| true_false | 52.3% | 0.736 | 0.269 | 0.743 | 0.281 | 28.1% | 0 | baseline.robust_2B.no_manual | Teacher-forced continuation scores from separate follow-up prompt framings; they are not probabilities extracted from the original generated explanation. | 100.0% | — |
| yes_no | 67.4% | 0.892 | 0.210 | 0.606 | 0.211 | 21.1% | — | baseline.robust_2B.no_manual | Teacher-forced continuation scores from separate follow-up prompt framings; they are not probabilities extracted from the original generated explanation. | — | 100.0% |
| true_false | 52.3% | 0.736 | 0.269 | 0.743 | 0.281 | 28.1% | — | baseline.robust_2B.no_manual | Teacher-forced continuation scores from separate follow-up prompt framings; they are not probabilities extracted from the original generated explanation. | — | 100.0% |
| yes_no | 66.8% | 0.850 | 0.213 | 0.604 | 0.183 | 18.3% | 0 | baseline.robust_2B.with_manual | Teacher-forced continuation scores from separate follow-up prompt framings; they are not probabilities extracted from the original generated explanation. | 100.0% | — |
| true_false | 33.3% | 0.695 | 0.503 | 1.415 | 0.542 | 54.2% | 0 | baseline.robust_2B.with_manual | Teacher-forced continuation scores from separate follow-up prompt framings; they are not probabilities extracted from the original generated explanation. | 100.0% | — |
| yes_no | 66.8% | 0.850 | 0.213 | 0.604 | 0.183 | 18.3% | — | baseline.robust_2B.with_manual | Teacher-forced continuation scores from separate follow-up prompt framings; they are not probabilities extracted from the original generated explanation. | — | 100.0% |
| true_false | 33.3% | 0.695 | 0.503 | 1.415 | 0.542 | 54.2% | — | baseline.robust_2B.with_manual | Teacher-forced continuation scores from separate follow-up prompt framings; they are not probabilities extracted from the original generated explanation. | — | 100.0% |
| yes_no | 33.3% | 0.850 | 0.563 | 1.720 | 0.596 | 59.6% | 0 | baseline.robust_4B.no_manual | Teacher-forced continuation scores from separate follow-up prompt framings; they are not probabilities extracted from the original generated explanation. | 100.0% | — |
| true_false | 39.6% | 0.680 | 0.295 | 0.790 | 0.300 | 30.0% | 0 | baseline.robust_4B.no_manual | Teacher-forced continuation scores from separate follow-up prompt framings; they are not probabilities extracted from the original generated explanation. | 100.0% | — |
| yes_no | 21.9% | 0.891 | 0.657 | 1.985 | 0.706 | 70.6% | — | baseline.robust_4B.no_manual | Teacher-forced continuation scores from separate follow-up prompt framings; they are not probabilities extracted from the original generated explanation. | — | 100.0% |
| true_false | 29.7% | 0.747 | 0.324 | 0.850 | 0.414 | 41.4% | — | baseline.robust_4B.no_manual | Teacher-forced continuation scores from separate follow-up prompt framings; they are not probabilities extracted from the original generated explanation. | — | 100.0% |
| yes_no | 53.1% | 0.781 | 0.402 | 1.264 | 0.406 | 40.6% | — | baseline.robust_4B.no_manual | Teacher-forced continuation scores from separate follow-up prompt framings; they are not probabilities extracted from the original generated explanation. | — | 100.0% |
| true_false | 56.6% | 0.635 | 0.247 | 0.688 | 0.105 | 10.5% | — | baseline.robust_4B.no_manual | Teacher-forced continuation scores from separate follow-up prompt framings; they are not probabilities extracted from the original generated explanation. | — | 100.0% |
| yes_no | 35.7% | 0.859 | 0.307 | 0.812 | 0.358 | 35.8% | 0 | baseline.robust_4B.with_manual | Teacher-forced continuation scores from separate follow-up prompt framings; they are not probabilities extracted from the original generated explanation. | 100.0% | — |
| true_false | 66.8% | 0.668 | 0.210 | 0.609 | 0.058 | 5.8% | 0 | baseline.robust_4B.with_manual | Teacher-forced continuation scores from separate follow-up prompt framings; they are not probabilities extracted from the original generated explanation. | 100.0% | — |
| yes_no | 9.4% | 0.948 | 0.391 | 0.991 | 0.593 | 59.3% | — | baseline.robust_4B.with_manual | Teacher-forced continuation scores from separate follow-up prompt framings; they are not probabilities extracted from the original generated explanation. | — | 100.0% |
| true_false | 94.2% | 0.714 | 0.131 | 0.445 | 0.291 | 29.1% | — | baseline.robust_4B.with_manual | Teacher-forced continuation scores from separate follow-up prompt framings; they are not probabilities extracted from the original generated explanation. | — | 100.0% |
| yes_no | 42.9% | 0.839 | 0.284 | 0.763 | 0.295 | 29.5% | — | baseline.robust_4B.with_manual | Teacher-forced continuation scores from separate follow-up prompt framings; they are not probabilities extracted from the original generated explanation. | — | 100.0% |
| true_false | 59.4% | 0.658 | 0.231 | 0.654 | 0.076 | 7.6% | — | baseline.robust_4B.with_manual | Teacher-forced continuation scores from separate follow-up prompt framings; they are not probabilities extracted from the original generated explanation. | — | 100.0% |
| — | — | — | — | — | — | — | — | interactive.legacy_0.8B.ABA | Teacher-forced continuation scores from separate follow-up prompt framings; they are not probabilities extracted from the original generated explanation. | — | — |
| yes_no | 68.0% | 0.900 | 0.194 | 0.551 | 0.188 | 18.8% | 3,000 | interactive.rejudge_2B.ABA | Teacher-forced continuation scores from separate follow-up prompt framings; they are not probabilities extracted from the original generated explanation. | 100.0% | — |
| true_false | 67.5% | 0.862 | 0.194 | 0.560 | 0.156 | 15.6% | 3,000 | interactive.rejudge_2B.ABA | Teacher-forced continuation scores from separate follow-up prompt framings; they are not probabilities extracted from the original generated explanation. | 100.0% | — |
| debater_ab_converted | 49.6% | 0.496 | 0.329 | 0.894 | 0.275 | 27.5% | 3,000 | interactive.rejudge_2B.ABA | Teacher-forced continuation scores from separate follow-up prompt framings; they are not probabilities extracted from the original generated explanation. | 100.0% | — |
| yes_no | 68.0% | 0.900 | 0.194 | 0.551 | 0.188 | 18.8% | — | interactive.rejudge_2B.ABA | Teacher-forced continuation scores from separate follow-up prompt framings; they are not probabilities extracted from the original generated explanation. | — | 100.0% |
| true_false | 67.5% | 0.862 | 0.194 | 0.560 | 0.156 | 15.6% | — | interactive.rejudge_2B.ABA | Teacher-forced continuation scores from separate follow-up prompt framings; they are not probabilities extracted from the original generated explanation. | — | 100.0% |
| debater_ab_converted | 49.6% | 0.496 | 0.329 | 0.894 | 0.275 | 27.5% | — | interactive.rejudge_2B.ABA | Teacher-forced continuation scores from separate follow-up prompt framings; they are not probabilities extracted from the original generated explanation. | — | 100.0% |
| yes_no | 67.8% | 0.857 | 0.193 | 0.552 | 0.162 | 16.2% | 3,000 | interactive.rejudge_2B.BAB | Teacher-forced continuation scores from separate follow-up prompt framings; they are not probabilities extracted from the original generated explanation. | 100.0% | — |
| true_false | 67.7% | 0.777 | 0.198 | 0.576 | 0.109 | 10.9% | 3,000 | interactive.rejudge_2B.BAB | Teacher-forced continuation scores from separate follow-up prompt framings; they are not probabilities extracted from the original generated explanation. | 100.0% | — |
| debater_ab_converted | 49.4% | 0.503 | 0.335 | 0.911 | 0.287 | 28.7% | 3,000 | interactive.rejudge_2B.BAB | Teacher-forced continuation scores from separate follow-up prompt framings; they are not probabilities extracted from the original generated explanation. | 100.0% | — |
| yes_no | 67.8% | 0.857 | 0.193 | 0.552 | 0.162 | 16.2% | — | interactive.rejudge_2B.BAB | Teacher-forced continuation scores from separate follow-up prompt framings; they are not probabilities extracted from the original generated explanation. | — | 100.0% |
| true_false | 67.7% | 0.777 | 0.198 | 0.576 | 0.109 | 10.9% | — | interactive.rejudge_2B.BAB | Teacher-forced continuation scores from separate follow-up prompt framings; they are not probabilities extracted from the original generated explanation. | — | 100.0% |
| debater_ab_converted | 49.4% | 0.503 | 0.335 | 0.911 | 0.287 | 28.7% | — | interactive.rejudge_2B.BAB | Teacher-forced continuation scores from separate follow-up prompt framings; they are not probabilities extracted from the original generated explanation. | — | 100.0% |
| yes_no | 48.1% | 0.609 | 0.274 | 0.746 | 0.241 | 24.1% | 3,000 | interactive.robust_0.8B.ABA | Teacher-forced continuation scores from separate follow-up prompt framings; they are not probabilities extracted from the original generated explanation. | 100.0% | — |
| true_false | 36.9% | 0.603 | 0.303 | 0.807 | 0.295 | 29.5% | 3,000 | interactive.robust_0.8B.ABA | Teacher-forced continuation scores from separate follow-up prompt framings; they are not probabilities extracted from the original generated explanation. | 100.0% | — |
| debater_ab_converted | 49.6% | 0.480 | 0.364 | 1.018 | 0.323 | 32.3% | 3,000 | interactive.robust_0.8B.ABA | Teacher-forced continuation scores from separate follow-up prompt framings; they are not probabilities extracted from the original generated explanation. | 100.0% | — |
| yes_no | 47.3% | 0.598 | 0.275 | 0.748 | 0.255 | 25.5% | — | interactive.robust_0.8B.ABA | Teacher-forced continuation scores from separate follow-up prompt framings; they are not probabilities extracted from the original generated explanation. | — | 100.0% |
| true_false | 34.2% | 0.585 | 0.315 | 0.834 | 0.323 | 32.3% | — | interactive.robust_0.8B.ABA | Teacher-forced continuation scores from separate follow-up prompt framings; they are not probabilities extracted from the original generated explanation. | — | 100.0% |
| debater_ab_converted | 46.1% | 0.460 | 0.382 | 1.059 | 0.357 | 35.7% | — | interactive.robust_0.8B.ABA | Teacher-forced continuation scores from separate follow-up prompt framings; they are not probabilities extracted from the original generated explanation. | — | 100.0% |
| yes_no | 48.3% | 0.612 | 0.273 | 0.745 | 0.236 | 23.6% | — | interactive.robust_0.8B.ABA | Teacher-forced continuation scores from separate follow-up prompt framings; they are not probabilities extracted from the original generated explanation. | — | 100.0% |
| true_false | 37.9% | 0.611 | 0.299 | 0.797 | 0.285 | 28.5% | — | interactive.robust_0.8B.ABA | Teacher-forced continuation scores from separate follow-up prompt framings; they are not probabilities extracted from the original generated explanation. | — | 100.0% |
| debater_ab_converted | 50.9% | 0.487 | 0.357 | 1.003 | 0.312 | 31.2% | — | interactive.robust_0.8B.ABA | Teacher-forced continuation scores from separate follow-up prompt framings; they are not probabilities extracted from the original generated explanation. | — | 100.0% |
| yes_no | 41.9% | 0.542 | 0.303 | 0.811 | 0.274 | 27.4% | 3,000 | interactive.robust_0.8B.BAB | Teacher-forced continuation scores from separate follow-up prompt framings; they are not probabilities extracted from the original generated explanation. | 100.0% | — |
| true_false | 36.7% | 0.624 | 0.309 | 0.820 | 0.310 | 31.0% | 3,000 | interactive.robust_0.8B.BAB | Teacher-forced continuation scores from separate follow-up prompt framings; they are not probabilities extracted from the original generated explanation. | 100.0% | — |
| debater_ab_converted | 51.2% | 0.509 | 0.275 | 0.752 | 0.183 | 18.3% | 3,000 | interactive.robust_0.8B.BAB | Teacher-forced continuation scores from separate follow-up prompt framings; they are not probabilities extracted from the original generated explanation. | 100.0% | — |
| yes_no | 38.3% | 0.527 | 0.315 | 0.835 | 0.320 | 32.0% | — | interactive.robust_0.8B.BAB | Teacher-forced continuation scores from separate follow-up prompt framings; they are not probabilities extracted from the original generated explanation. | — | 100.0% |
| true_false | 32.0% | 0.614 | 0.328 | 0.861 | 0.363 | 36.3% | — | interactive.robust_0.8B.BAB | Teacher-forced continuation scores from separate follow-up prompt framings; they are not probabilities extracted from the original generated explanation. | — | 100.0% |
| debater_ab_converted | 53.0% | 0.527 | 0.269 | 0.738 | 0.214 | 21.4% | — | interactive.robust_0.8B.BAB | Teacher-forced continuation scores from separate follow-up prompt framings; they are not probabilities extracted from the original generated explanation. | — | 100.0% |
| yes_no | 43.8% | 0.547 | 0.297 | 0.799 | 0.250 | 25.0% | — | interactive.robust_0.8B.BAB | Teacher-forced continuation scores from separate follow-up prompt framings; they are not probabilities extracted from the original generated explanation. | — | 100.0% |
| true_false | 39.2% | 0.631 | 0.299 | 0.798 | 0.282 | 28.2% | — | interactive.robust_0.8B.BAB | Teacher-forced continuation scores from separate follow-up prompt framings; they are not probabilities extracted from the original generated explanation. | — | 100.0% |
| debater_ab_converted | 50.2% | 0.498 | 0.279 | 0.759 | 0.175 | 17.5% | — | interactive.robust_0.8B.BAB | Teacher-forced continuation scores from separate follow-up prompt framings; they are not probabilities extracted from the original generated explanation. | — | 100.0% |
| yes_no | 42.8% | 0.537 | 0.302 | 0.808 | 0.270 | 27.0% | 3,000 | interactive.robust_0.8B.BAB_swapped_labels | Teacher-forced continuation scores from separate follow-up prompt framings; they are not probabilities extracted from the original generated explanation. | 100.0% | — |
| true_false | 38.4% | 0.607 | 0.299 | 0.797 | 0.289 | 28.9% | 3,000 | interactive.robust_0.8B.BAB_swapped_labels | Teacher-forced continuation scores from separate follow-up prompt framings; they are not probabilities extracted from the original generated explanation. | 100.0% | — |
| debater_ab_converted | 50.5% | 0.506 | 0.343 | 0.952 | 0.300 | 30.0% | 3,000 | interactive.robust_0.8B.BAB_swapped_labels | Teacher-forced continuation scores from separate follow-up prompt framings; they are not probabilities extracted from the original generated explanation. | 100.0% | — |
| yes_no | 40.2% | 0.508 | 0.311 | 0.827 | 0.305 | 30.5% | — | interactive.robust_0.8B.BAB_swapped_labels | Teacher-forced continuation scores from separate follow-up prompt framings; they are not probabilities extracted from the original generated explanation. | — | 100.0% |
| true_false | 32.8% | 0.577 | 0.314 | 0.830 | 0.333 | 33.3% | — | interactive.robust_0.8B.BAB_swapped_labels | Teacher-forced continuation scores from separate follow-up prompt framings; they are not probabilities extracted from the original generated explanation. | — | 100.0% |
| debater_ab_converted | 51.1% | 0.508 | 0.339 | 0.942 | 0.300 | 30.0% | — | interactive.robust_0.8B.BAB_swapped_labels | Teacher-forced continuation scores from separate follow-up prompt framings; they are not probabilities extracted from the original generated explanation. | — | 100.0% |
| yes_no | 44.2% | 0.547 | 0.298 | 0.799 | 0.252 | 25.2% | — | interactive.robust_0.8B.BAB_swapped_labels | Teacher-forced continuation scores from separate follow-up prompt framings; they are not probabilities extracted from the original generated explanation. | — | 100.0% |
| true_false | 41.3% | 0.621 | 0.291 | 0.780 | 0.267 | 26.7% | — | interactive.robust_0.8B.BAB_swapped_labels | Teacher-forced continuation scores from separate follow-up prompt framings; they are not probabilities extracted from the original generated explanation. | — | 100.0% |
| debater_ab_converted | 50.2% | 0.504 | 0.345 | 0.957 | 0.300 | 30.0% | — | interactive.robust_0.8B.BAB_swapped_labels | Teacher-forced continuation scores from separate follow-up prompt framings; they are not probabilities extracted from the original generated explanation. | — | 100.0% |
| — | — | — | — | — | — | — | — | statement.legacy_0.8B | Teacher-forced continuation scores from separate follow-up prompt framings; they are not probabilities extracted from the original generated explanation. | — | — |
| — | — | — | — | — | — | — | — | statement.older_pydantic_0.8B | Teacher-forced continuation scores from separate follow-up prompt framings; they are not probabilities extracted from the original generated explanation. | — | — |
| yes_no | 73.9% | 0.895 | 0.161 | 0.476 | 0.145 | 14.5% | 3,000 | statement.rejudge_2B | Teacher-forced continuation scores from separate follow-up prompt framings; they are not probabilities extracted from the original generated explanation. | 100.0% | — |
| true_false | 67.9% | 0.802 | 0.192 | 0.564 | 0.114 | 11.4% | 3,000 | statement.rejudge_2B | Teacher-forced continuation scores from separate follow-up prompt framings; they are not probabilities extracted from the original generated explanation. | 100.0% | — |
| debater_ab_converted | 49.4% | 0.502 | 0.306 | 0.826 | 0.233 | 23.3% | 3,000 | statement.rejudge_2B | Teacher-forced continuation scores from separate follow-up prompt framings; they are not probabilities extracted from the original generated explanation. | 100.0% | — |
| yes_no | 73.9% | 0.895 | 0.161 | 0.476 | 0.145 | 14.5% | — | statement.rejudge_2B | Teacher-forced continuation scores from separate follow-up prompt framings; they are not probabilities extracted from the original generated explanation. | — | 100.0% |
| true_false | 67.9% | 0.802 | 0.192 | 0.564 | 0.114 | 11.4% | — | statement.rejudge_2B | Teacher-forced continuation scores from separate follow-up prompt framings; they are not probabilities extracted from the original generated explanation. | — | 100.0% |
| debater_ab_converted | 49.4% | 0.502 | 0.306 | 0.826 | 0.233 | 23.3% | — | statement.rejudge_2B | Teacher-forced continuation scores from separate follow-up prompt framings; they are not probabilities extracted from the original generated explanation. | — | 100.0% |
| yes_no | 36.6% | 0.606 | 0.366 | 0.979 | 0.385 | 38.5% | 3,000 | statement.robust_0.8B | Teacher-forced continuation scores from separate follow-up prompt framings; they are not probabilities extracted from the original generated explanation. | 100.0% | — |
| true_false | 61.4% | 0.634 | 0.230 | 0.652 | 0.134 | 13.4% | 3,000 | statement.robust_0.8B | Teacher-forced continuation scores from separate follow-up prompt framings; they are not probabilities extracted from the original generated explanation. | 100.0% | — |
| debater_ab_converted | 49.0% | 0.512 | 0.335 | 0.920 | 0.278 | 27.8% | 3,000 | statement.robust_0.8B | Teacher-forced continuation scores from separate follow-up prompt framings; they are not probabilities extracted from the original generated explanation. | 100.0% | — |
| yes_no | 34.5% | 0.608 | 0.379 | 1.011 | 0.407 | 40.7% | — | statement.robust_0.8B | Teacher-forced continuation scores from separate follow-up prompt framings; they are not probabilities extracted from the original generated explanation. | — | 100.0% |
| true_false | 60.8% | 0.630 | 0.231 | 0.654 | 0.153 | 15.3% | — | statement.robust_0.8B | Teacher-forced continuation scores from separate follow-up prompt framings; they are not probabilities extracted from the original generated explanation. | — | 100.0% |
| debater_ab_converted | 48.3% | 0.505 | 0.338 | 0.925 | 0.285 | 28.5% | — | statement.robust_0.8B | Teacher-forced continuation scores from separate follow-up prompt framings; they are not probabilities extracted from the original generated explanation. | — | 100.0% |
| yes_no | 41.5% | 0.613 | 0.336 | 0.903 | 0.334 | 33.4% | — | statement.robust_0.8B | Teacher-forced continuation scores from separate follow-up prompt framings; they are not probabilities extracted from the original generated explanation. | — | 100.0% |
| true_false | 62.7% | 0.648 | 0.228 | 0.648 | 0.091 | 9.1% | — | statement.robust_0.8B | Teacher-forced continuation scores from separate follow-up prompt framings; they are not probabilities extracted from the original generated explanation. | — | 100.0% |
| debater_ab_converted | 50.4% | 0.526 | 0.329 | 0.908 | 0.267 | 26.7% | — | statement.robust_0.8B | Teacher-forced continuation scores from separate follow-up prompt framings; they are not probabilities extracted from the original generated explanation. | — | 100.0% |

## 9. Cross-experiment synthesis

### Descriptive condition ranking

| condition | strict_accuracy | valid_only_accuracy | balanced_accuracy | unknown_rate | records | complete |
| --- | --- | --- | --- | --- | --- | --- |
| Baseline 2B — no manual | 86.9% | 86.9% | 86.1% | 0.0% | 3,000 | Yes |
| Baseline 4B — no manual | 80.3% | 80.3% | 83.9% | 0.0% | 3,000 | Yes |
| Baseline 2B — with manual | 85.0% | 85.0% | 83.3% | 0.0% | 3,000 | Yes |
| Baseline 0.8B — no manual | 83.3% | 83.3% | 81.7% | 0.0% | 3,000 | Yes |
| Baseline 0.8B — older Pydantic | 80.1% | 80.1% | 78.4% | 0.0% | 3,000 | Yes |
| Baseline 0.8B — with manual | 80.2% | 80.2% | 76.3% | 0.0% | 3,000 | Yes |
| Interactive BAB — rejudged by 2B | 74.1% | 74.1% | 73.9% | 0.0% | 3,000 | Yes |
| Statement — rejudged by 2B | 79.5% | 79.5% | 73.7% | 0.0% | 3,000 | Yes |
| Title-only asymmetric — baseline | 77.5% | 77.5% | 73.1% | 0.0% | 3,000 | Yes |
| Interactive ABA — rejudged by 2B | 75.2% | 75.2% | 73.0% | 0.0% | 3,000 | Yes |
| Title-only asymmetric — statements | 76.6% | 76.6% | 72.5% | 0.0% | 3,000 | Yes |
| Statement — older Pydantic | 74.6% | 78.0% | 70.8% | 4.3% | 3,000 | Yes |
| Title-only asymmetric — interactive ABA | 72.4% | 72.4% | 68.3% | 0.0% | 3,000 | Yes |
| Statement — 0.8B judge | 65.7% | 65.7% | 67.2% | 0.0% | 3,000 | Yes |
| Baseline 4B — with manual | 54.7% | 54.7% | 65.9% | 0.0% | 3,000 | Yes |
| Interactive BAB — displayed labels swapped | 54.6% | 54.6% | 60.9% | 0.0% | 3,000 | Yes |
| Interactive ABA — 0.8B judge | 55.4% | 55.4% | 60.9% | 0.0% | 3,000 | Yes |
| Interactive BAB — 0.8B judge | 54.3% | 54.3% | 60.3% | 0.0% | 3,000 | Yes |

### Controlled findings

- From baseline without manual to baseline with manual, accuracy decreased by 3.2% on 3,000 exact matched records (100.0% of eligible records); 95% CI -4.7% to -1.6%. Interpretation: clear evidence in this controlled comparison; comparison is controlled.
- From statement judge 0.8B to statement judge 2B, accuracy increased by 13.8% on 3,000 exact matched records (100.0% of eligible records); 95% CI +11.9% to +15.8%. Interpretation: clear evidence in this controlled comparison; comparison is controlled.
- From interactive ABA judge 0.8B to interactive ABA judge 2B, accuracy increased by 19.8% on 3,000 exact matched records (100.0% of eligible records); 95% CI +17.7% to +21.9%. Interpretation: clear evidence in this controlled comparison; comparison is controlled.
- From interactive BAB judge 0.8B to interactive BAB judge 2B, accuracy increased by 19.8% on 3,000 exact matched records (100.0% of eligible records); 95% CI +17.6% to +21.9%. Interpretation: clear evidence in this controlled comparison; comparison is controlled.
- From original BAB labels to BAB with displayed labels swapped, accuracy increased by 0.3% on 3,000 exact matched records (100.0% of eligible records); 95% CI -1.5% to +2.0%. Interpretation: no clear difference; the confidence interval includes zero; comparison is controlled.

### Descriptive or confounded observations

- From baseline.legacy_0.8B to statement.legacy_0.8B, accuracy decreased by 49.0% on 292 exact matched records (100.0% of eligible records); 95% CI -55.1% to -42.7%. Interpretation: descriptive difference only (confounded); comparison is confounded.
- From baseline.legacy_0.8B to interactive.legacy_0.8B.ABA, accuracy decreased by 38.2% on 228 exact matched records (100.0% of eligible records); 95% CI -45.4% to -31.0%. Interpretation: descriptive difference only (confounded); comparison is confounded.
- From statement.legacy_0.8B to interactive.legacy_0.8B.ABA, accuracy increased by 2.6% on 1,221 exact matched records (100.0% of eligible records); 95% CI +0.3% to +4.9%. Interpretation: descriptive difference only (confounded); comparison is confounded.
- From legacy baseline to older Pydantic baseline, accuracy increased by 36.1% on 1,189 exact matched records (100.0% of eligible records); 95% CI +32.9% to +39.3%. Interpretation: descriptive difference only (confounded); comparison is confounded.
- From older Pydantic baseline to robust with-manual baseline, accuracy increased by 3.0% on 2,194 exact matched records (73.1% of eligible records); 95% CI +1.1% to +4.8%. Interpretation: descriptive difference only (confounded); comparison is confounded.
- From legacy statement to older Pydantic statement, accuracy increased by 61.3% on 639 exact matched records (43.5% of eligible records); 95% CI +57.1% to +65.5%. Interpretation: descriptive difference only (confounded); comparison is confounded.
- From older Pydantic statement to robust statement, accuracy decreased by 16.8% on 2,158 exact matched records (71.9% of eligible records); 95% CI -19.3% to -14.3%. Interpretation: descriptive difference only (confounded); comparison is confounded.
- From older Pydantic statement to robust statement rejudged by 2B, accuracy increased by 8.7% on 2,158 exact matched records (71.9% of eligible records); 95% CI +6.7% to +10.6%. Interpretation: descriptive difference only (confounded); comparison is confounded.
- From interactive ABA to interactive BAB, accuracy decreased by 1.0% on 3,000 exact matched records (100.0% of eligible records); 95% CI -3.3% to +1.2%. Interpretation: descriptive difference only (confounded); comparison is confounded.
- From 2B judge on ABA to 2B judge on BAB, accuracy decreased by 1.1% on 3,000 exact matched records (100.0% of eligible records); 95% CI -3.1% to +1.0%. Interpretation: descriptive difference only (confounded); comparison is confounded.

### Bias summary

- asymmetric_titleonly.baseline: error asymmetry descriptively favors No/CON (FPR 13.8% vs FNR 40.0%).
- asymmetric_titleonly.interactive.ABA: error asymmetry descriptively favors No/CON (FPR 19.4% vs FNR 44.0%); displayed A was selected 55.2% of the time, but uncertainty is insufficient to call this a bias; first speaker was selected 55.2% of the time, but uncertainty is insufficient to call this a bias; two-turn speaker was selected 55.2% of the time, but uncertainty is insufficient to call this a bias; longer side was selected 55.8% of the time, but uncertainty is insufficient to call this a bias.
- asymmetric_titleonly.statement: error asymmetry descriptively favors No/CON (FPR 15.0% vs FNR 40.0%); longer side was selected 57.1% of the time, but uncertainty is insufficient to call this a bias.
- baseline.legacy_0.8B: error asymmetry descriptively favors No/CON (FPR 1.8% vs FNR 42.4%).
- baseline.older_pydantic_0.8B: error asymmetry descriptively favors No/CON (FPR 16.4% vs FNR 26.8%).
- baseline.robust_0.8B.no_manual: error asymmetry descriptively favors No/CON (FPR 13.5% vs FNR 23.1%).
- baseline.robust_0.8B.with_manual: error asymmetry descriptively favors No/CON (FPR 12.0% vs FNR 35.4%).
- baseline.robust_2B.no_manual: error asymmetry descriptively favors No/CON (FPR 11.5% vs FNR 16.3%).
- baseline.robust_2B.with_manual: error asymmetry descriptively favors No/CON (FPR 11.6% vs FNR 21.9%).
- baseline.robust_4B.no_manual: error asymmetry descriptively favors Yes/PRO (FPR 26.9% vs FNR 5.3%).
- baseline.robust_4B.with_manual: error asymmetry descriptively favors Yes/PRO (FPR 67.8% vs FNR 0.5%).
- interactive.legacy_0.8B.ABA: error asymmetry descriptively favors No/CON (FPR 29.6% vs FNR 50.3%).
- interactive.rejudge_2B.ABA: error asymmetry descriptively favors No/CON (FPR 20.4% vs FNR 33.6%).
- interactive.rejudge_2B.BAB: FPR and FNR are similar (25.4% vs 26.8%), so there is no large error-asymmetry signal.
- interactive.robust_0.8B.ABA: error asymmetry descriptively favors Yes/PRO (FPR 55.6% vs FNR 22.7%).
- interactive.robust_0.8B.BAB: error asymmetry descriptively favors Yes/PRO (FPR 57.6% vs FNR 21.9%).
- interactive.robust_0.8B.BAB_swapped_labels: error asymmetry descriptively favors Yes/PRO (FPR 58.0% vs FNR 20.3%).
- statement.legacy_0.8B: error asymmetry descriptively favors No/CON (FPR 9.4% vs FNR 60.2%); longer side was selected 44.2% of the time, but uncertainty is insufficient to call this a bias.
- statement.older_pydantic_0.8B: error asymmetry descriptively favors No/CON (FPR 16.1% vs FNR 34.8%).
- statement.rejudge_2B: error asymmetry descriptively favors No/CON (FPR 8.8% vs FNR 43.9%); longer side was selected 44.1% of the time, but uncertainty is insufficient to call this a bias.
- statement.robust_0.8B: error asymmetry descriptively favors Yes/PRO (FPR 37.5% vs FNR 28.0%).

### Confidence summary

- baseline.robust_0.8B.no_manual: confidence discriminates errors well (AUC 0.780); Brier score is 0.604 (lower is better); calibration error is substantial (ECE 0.624).
- baseline.robust_0.8B.no_manual: confidence discriminates errors well (AUC 0.726); Brier score is 0.291 (lower is better); calibration error is substantial (ECE 0.296).
- baseline.robust_0.8B.with_manual: confidence discriminates errors well (AUC 0.794); Brier score is 0.621 (lower is better); calibration error is substantial (ECE 0.634).
- baseline.robust_0.8B.with_manual: confidence has modest discrimination (AUC 0.677); Brier score is 0.233 (lower is better); calibration error is substantial (ECE 0.147).
- baseline.robust_2B.no_manual: confidence discriminates errors well (AUC 0.892); Brier score is 0.210 (lower is better); calibration error is substantial (ECE 0.211).
- baseline.robust_2B.no_manual: confidence discriminates errors well (AUC 0.736); Brier score is 0.269 (lower is better); calibration error is substantial (ECE 0.281).
- baseline.robust_2B.with_manual: confidence discriminates errors well (AUC 0.850); Brier score is 0.213 (lower is better); calibration error is substantial (ECE 0.183).
- baseline.robust_2B.with_manual: confidence has modest discrimination (AUC 0.695); Brier score is 0.503 (lower is better); calibration error is substantial (ECE 0.542).
- baseline.robust_4B.no_manual: confidence discriminates errors well (AUC 0.850); Brier score is 0.563 (lower is better); calibration error is substantial (ECE 0.596).
- baseline.robust_4B.no_manual: confidence has modest discrimination (AUC 0.680); Brier score is 0.295 (lower is better); calibration error is substantial (ECE 0.300).
- baseline.robust_4B.no_manual: confidence discriminates errors well (AUC 0.891); Brier score is 0.657 (lower is better); calibration error is substantial (ECE 0.706).
- baseline.robust_4B.no_manual: confidence discriminates errors well (AUC 0.747); Brier score is 0.324 (lower is better); calibration error is substantial (ECE 0.414).
- baseline.robust_4B.no_manual: confidence discriminates errors well (AUC 0.781); Brier score is 0.402 (lower is better); calibration error is substantial (ECE 0.406).
- baseline.robust_4B.no_manual: confidence has modest discrimination (AUC 0.635); Brier score is 0.247 (lower is better); calibration error is substantial (ECE 0.105).
- baseline.robust_4B.with_manual: confidence discriminates errors well (AUC 0.859); Brier score is 0.307 (lower is better); calibration error is substantial (ECE 0.358).
- baseline.robust_4B.with_manual: confidence has modest discrimination (AUC 0.668); Brier score is 0.210 (lower is better); calibration error is moderate (ECE 0.058).
- baseline.robust_4B.with_manual: confidence discriminates errors well (AUC 0.948); Brier score is 0.391 (lower is better); calibration error is substantial (ECE 0.593).
- baseline.robust_4B.with_manual: confidence discriminates errors well (AUC 0.714); Brier score is 0.131 (lower is better); calibration error is substantial (ECE 0.291).
- baseline.robust_4B.with_manual: confidence discriminates errors well (AUC 0.839); Brier score is 0.284 (lower is better); calibration error is substantial (ECE 0.295).
- baseline.robust_4B.with_manual: confidence has modest discrimination (AUC 0.658); Brier score is 0.231 (lower is better); calibration error is moderate (ECE 0.076).
- interactive.rejudge_2B.ABA: confidence discriminates errors well (AUC 0.900); Brier score is 0.194 (lower is better); calibration error is substantial (ECE 0.188).
- interactive.rejudge_2B.ABA: confidence discriminates errors well (AUC 0.862); Brier score is 0.194 (lower is better); calibration error is substantial (ECE 0.156).
- interactive.rejudge_2B.ABA: confidence has weak or no useful discrimination (AUC 0.496); Brier score is 0.329 (lower is better); calibration error is substantial (ECE 0.275).
- interactive.rejudge_2B.BAB: confidence discriminates errors well (AUC 0.857); Brier score is 0.193 (lower is better); calibration error is substantial (ECE 0.162).
- interactive.rejudge_2B.BAB: confidence discriminates errors well (AUC 0.777); Brier score is 0.198 (lower is better); calibration error is substantial (ECE 0.109).
- interactive.rejudge_2B.BAB: confidence has weak or no useful discrimination (AUC 0.503); Brier score is 0.335 (lower is better); calibration error is substantial (ECE 0.287).
- interactive.robust_0.8B.ABA: confidence has modest discrimination (AUC 0.609); Brier score is 0.274 (lower is better); calibration error is substantial (ECE 0.241).
- interactive.robust_0.8B.ABA: confidence has modest discrimination (AUC 0.603); Brier score is 0.303 (lower is better); calibration error is substantial (ECE 0.295).
- interactive.robust_0.8B.ABA: confidence has weak or no useful discrimination (AUC 0.480); Brier score is 0.364 (lower is better); calibration error is substantial (ECE 0.323).
- interactive.robust_0.8B.ABA: confidence has modest discrimination (AUC 0.598); Brier score is 0.275 (lower is better); calibration error is substantial (ECE 0.255).
- interactive.robust_0.8B.ABA: confidence has modest discrimination (AUC 0.585); Brier score is 0.315 (lower is better); calibration error is substantial (ECE 0.323).
- interactive.robust_0.8B.ABA: confidence has weak or no useful discrimination (AUC 0.460); Brier score is 0.382 (lower is better); calibration error is substantial (ECE 0.357).
- interactive.robust_0.8B.ABA: confidence has modest discrimination (AUC 0.612); Brier score is 0.273 (lower is better); calibration error is substantial (ECE 0.236).
- interactive.robust_0.8B.ABA: confidence has modest discrimination (AUC 0.611); Brier score is 0.299 (lower is better); calibration error is substantial (ECE 0.285).
- interactive.robust_0.8B.ABA: confidence has weak or no useful discrimination (AUC 0.487); Brier score is 0.357 (lower is better); calibration error is substantial (ECE 0.312).
- interactive.robust_0.8B.BAB: confidence has weak or no useful discrimination (AUC 0.542); Brier score is 0.303 (lower is better); calibration error is substantial (ECE 0.274).
- interactive.robust_0.8B.BAB: confidence has modest discrimination (AUC 0.624); Brier score is 0.309 (lower is better); calibration error is substantial (ECE 0.310).
- interactive.robust_0.8B.BAB: confidence has weak or no useful discrimination (AUC 0.509); Brier score is 0.275 (lower is better); calibration error is substantial (ECE 0.183).
- interactive.robust_0.8B.BAB: confidence has weak or no useful discrimination (AUC 0.527); Brier score is 0.315 (lower is better); calibration error is substantial (ECE 0.320).
- interactive.robust_0.8B.BAB: confidence has modest discrimination (AUC 0.614); Brier score is 0.328 (lower is better); calibration error is substantial (ECE 0.363).
- interactive.robust_0.8B.BAB: confidence has weak or no useful discrimination (AUC 0.527); Brier score is 0.269 (lower is better); calibration error is substantial (ECE 0.214).
- interactive.robust_0.8B.BAB: confidence has weak or no useful discrimination (AUC 0.547); Brier score is 0.297 (lower is better); calibration error is substantial (ECE 0.250).
- interactive.robust_0.8B.BAB: confidence has modest discrimination (AUC 0.631); Brier score is 0.299 (lower is better); calibration error is substantial (ECE 0.282).
- interactive.robust_0.8B.BAB: confidence has weak or no useful discrimination (AUC 0.498); Brier score is 0.279 (lower is better); calibration error is substantial (ECE 0.175).
- interactive.robust_0.8B.BAB_swapped_labels: confidence has weak or no useful discrimination (AUC 0.537); Brier score is 0.302 (lower is better); calibration error is substantial (ECE 0.270).
- interactive.robust_0.8B.BAB_swapped_labels: confidence has modest discrimination (AUC 0.607); Brier score is 0.299 (lower is better); calibration error is substantial (ECE 0.289).
- interactive.robust_0.8B.BAB_swapped_labels: confidence has weak or no useful discrimination (AUC 0.506); Brier score is 0.343 (lower is better); calibration error is substantial (ECE 0.300).
- interactive.robust_0.8B.BAB_swapped_labels: confidence has weak or no useful discrimination (AUC 0.508); Brier score is 0.311 (lower is better); calibration error is substantial (ECE 0.305).
- interactive.robust_0.8B.BAB_swapped_labels: confidence has modest discrimination (AUC 0.577); Brier score is 0.314 (lower is better); calibration error is substantial (ECE 0.333).
- interactive.robust_0.8B.BAB_swapped_labels: confidence has weak or no useful discrimination (AUC 0.508); Brier score is 0.339 (lower is better); calibration error is substantial (ECE 0.300).
- interactive.robust_0.8B.BAB_swapped_labels: confidence has weak or no useful discrimination (AUC 0.547); Brier score is 0.298 (lower is better); calibration error is substantial (ECE 0.252).
- interactive.robust_0.8B.BAB_swapped_labels: confidence has modest discrimination (AUC 0.621); Brier score is 0.291 (lower is better); calibration error is substantial (ECE 0.267).
- interactive.robust_0.8B.BAB_swapped_labels: confidence has weak or no useful discrimination (AUC 0.504); Brier score is 0.345 (lower is better); calibration error is substantial (ECE 0.300).
- statement.rejudge_2B: confidence discriminates errors well (AUC 0.895); Brier score is 0.161 (lower is better); calibration error is substantial (ECE 0.145).
- statement.rejudge_2B: confidence discriminates errors well (AUC 0.802); Brier score is 0.192 (lower is better); calibration error is substantial (ECE 0.114).
- statement.rejudge_2B: confidence has weak or no useful discrimination (AUC 0.502); Brier score is 0.306 (lower is better); calibration error is substantial (ECE 0.233).
- statement.robust_0.8B: confidence has modest discrimination (AUC 0.606); Brier score is 0.366 (lower is better); calibration error is substantial (ECE 0.385).
- statement.robust_0.8B: confidence has modest discrimination (AUC 0.634); Brier score is 0.230 (lower is better); calibration error is substantial (ECE 0.134).
- statement.robust_0.8B: confidence has weak or no useful discrimination (AUC 0.512); Brier score is 0.335 (lower is better); calibration error is substantial (ECE 0.278).
- statement.robust_0.8B: confidence has modest discrimination (AUC 0.608); Brier score is 0.379 (lower is better); calibration error is substantial (ECE 0.407).
- statement.robust_0.8B: confidence has modest discrimination (AUC 0.630); Brier score is 0.231 (lower is better); calibration error is substantial (ECE 0.153).
- statement.robust_0.8B: confidence has weak or no useful discrimination (AUC 0.505); Brier score is 0.338 (lower is better); calibration error is substantial (ECE 0.285).
- statement.robust_0.8B: confidence has modest discrimination (AUC 0.613); Brier score is 0.336 (lower is better); calibration error is substantial (ECE 0.334).
- statement.robust_0.8B: confidence has modest discrimination (AUC 0.648); Brier score is 0.228 (lower is better); calibration error is moderate (ECE 0.091).
- statement.robust_0.8B: confidence has weak or no useful discrimination (AUC 0.526); Brier score is 0.329 (lower is better); calibration error is substantial (ECE 0.267).

### Comparison with expectations

- Similar negatives were less accurate than unrelated negatives in 18 of 21 comparable conditions.

## Limitations

- Runs are paired only after `(stage, pmid, normalized candidate_tag, ground_truth)` verification; `(stage, pmid)` alone is insufficient because positive candidate tags may differ.
- The dataset has 1,000 positive and 2,000 negative records. Always-No reaches 66.7% ordinary accuracy but only 50% balanced accuracy.
- `Unknown` is never converted to `No`. Strict accuracy counts it as incorrect; valid-only accuracy can be selective and must include coverage.
- Legacy and named Pydantic comparisons can differ in prompts, available inputs, parsing, retries, fallback behavior, candidate choice, and transcript construction. They are implementation comparisons, not pure formatting ablations.
- ABA and BAB transcripts were generated separately, so their difference combines speaking order/turn allocation with argument-content quality.
- Original BAB versus swapped-label BAB is a clean displayed-label test only after identical physical content and order have been verified.
- Teacher-forced Yes/No, true/false, and A/B scores are follow-up framing scores rather than token probabilities from the original explanation and need not be mutually calibrated.
- When fallback determines the final prediction from Yes/No scores, confidence–prediction agreement is circular; all, fallback-only, and non-fallback subsets must be reported separately.
- Speaker A, first position, last position, and receiving two turns are confounded in some debate formats; do not label their aggregate effect as a pure A/B bias.
- Multiple related tests increase false-positive risk. Benjamini–Hochberg-adjusted results are supplied alongside effect sizes and confidence intervals.
- The 2B rejudge is the same nominal size as the debaters, so it no longer represents the original weak-judge scalable-oversight setup.
- Cross-generation comparisons change multiple implementation factors.
- The opening speaker is also the closing/two-turn speaker within this order.
- Displayed A is also the first essay; label and position cannot be separated.
- The opening speaker is also the closing and two-turn speaker; first, last, and turn-count effects are confounded.
- Legacy files are historical conditions and are not pooled with robust runs.
- Exact candidate matching does not make separately generated prompts, arguments, parsers, or retries identical.
- In legacy statement, displayed A and first position are confounded.
- In legacy ABA, A is first, last, and receives two turns; those effects cannot be separated.
- Raw Yes/PRO selection is not interpreted as bias without FPR/FNR or a controlled intervention.
- Unknown outputs count as failures in strict metrics and are excluded only in explicitly labelled valid-only metrics.
- The comparison is treated as controlled only for exact candidate matches.
- Teacher-forced confidence is analyzed separately from the generated verdict.
- Fallback confidence agreement is partly circular when fallback chose the verdict.
- ABA and BAB transcripts were generated separately; their difference is not a pure order effect.
- These are implementation comparisons, not clean tests of Pydantic formatting.
- Strict and valid-only accuracy must both be shown when Unknowns occur.
- The interactive transcript-label issue can create a mapping-specific artifact.
- Log probabilities are unavailable for the older named Pydantic files.
- The 2B judge has the same nominal size as the debaters, so this no longer represents the original weak-judge scalable-oversight setting.
- Never attribute these historical differences to judge size alone.
- A primary result is controlled only where stored content is verified identical.
- The 2B-vs-Pydantic comparisons are historical and multi-factor.
- Confidence scores are teacher-forced follow-up scores, not the original verdict token probability.
- Treat as a clean label test only after byte-level content/order verification.
- ABA-vs-BAB is not a pure order intervention because its arguments were generated separately.
- BAB-vs-swapped is the clean label test only where physical transcript equality is verified.
- A/first/last/two-turn effects are structurally confounded within one three-turn order.
- The normalized duplicate swapped-BAB file is excluded as an independent condition.
