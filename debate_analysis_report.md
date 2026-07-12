# AI-Debate XMLC - analysis report

Directory scanned: `/home/s27erahn/NLP_LabSS26`

## Current state / inventory

| dataset | file | records | metadata acc |
|---|---|---|---|
| baseline_withmanual | `baseline_withmanual_results_full.json` | 3000 | 80.0 |
| baseline_nomanual | `baseline_nomanual_results_full.json` | 3000 | 82.53333333333333 |
| statement | `statement_results_full.json` | 3000 | 64.26666666666667 |
| statement_rejudge2B | `statement_results_full_rejudge2B.json` | 678 | - |
| interactive | `interactive_results_full.json` | 3000 | 53.2 |
| interactive_rejudge2B | `interactive_results_full_rejudge2B.json` | 281 | - |
| pydantic_interactive | `pydantic_interactive_results_full.json` | 3000 | 66.7 |

## Per-dataset accuracy (overall + per stage) and Yes/No bias

### baseline_withmanual

| scope | n | correct | accuracy % |
|---|---|---|---|
| ALL | 3000 | 2405 | 80.17 |
| Round 1: True Tag | 1000 | 646 | 64.60 |
| Round 2: Unrelated Tag | 1000 | 928 | 92.80 |
| Round 3: Similar Tag | 1000 | 831 | 83.10 |

Verdict counts: {"Yes": 887, "No": 2113}

### baseline_nomanual

| scope | n | correct | accuracy % |
|---|---|---|---|
| ALL | 3000 | 2500 | 83.33 |
| Round 1: True Tag | 1000 | 769 | 76.90 |
| Round 2: Unrelated Tag | 1000 | 912 | 91.20 |
| Round 3: Similar Tag | 1000 | 819 | 81.90 |

Verdict counts: {"Yes": 1038, "No": 1962}

### statement

| scope | n | correct | accuracy % |
|---|---|---|---|
| ALL | 3000 | 1970 | 65.67 |
| Round 1: True Tag | 1000 | 720 | 72.00 |
| Round 2: Unrelated Tag | 1000 | 627 | 62.70 |
| Round 3: Similar Tag | 1000 | 623 | 62.30 |

Verdict counts: {"Yes": 1470, "No": 1530}

### statement_rejudge2B

| scope | n | correct | accuracy % |
|---|---|---|---|
| ALL | 678 | 537 | 79.20 |
| Round 1: True Tag | 250 | 139 | 55.60 |
| Round 2: Unrelated Tag | 250 | 231 | 92.40 |
| Round 3: Similar Tag | 178 | 167 | 93.82 |

Verdict counts: {"Yes": 169, "No": 509}

### interactive

| scope | n | correct | accuracy % |
|---|---|---|---|
| ALL | 6000 | 3291 | 54.85 |
| Round 1: True Tag | 2000 | 1554 | 77.70 |
| Round 2: Unrelated Tag | 2000 | 913 | 45.65 |
| Round 3: Similar Tag | 2000 | 824 | 41.20 |

Verdict counts: {"Yes": 3817, "No": 2183}

### interactive_rejudge2B

| scope | n | correct | accuracy % |
|---|---|---|---|
| ALL | 562 | 397 | 70.64 |
| Round 1: True Tag | 500 | 348 | 69.60 |
| Round 2: Unrelated Tag | 62 | 49 | 79.03 |

Verdict counts: {"Yes": 361, "No": 201}

### pydantic_interactive

| scope | n | correct | accuracy % |
|---|---|---|---|
| ALL | 3000 | 2001 | 66.70 |
| Round 1: True Tag | 1000 | 652 | 65.20 |
| Round 2: Unrelated Tag | 1000 | 711 | 71.10 |
| Round 3: Similar Tag | 1000 | 638 | 63.80 |

Verdict counts: {"No": 1695, "Yes": 1303, "Unknown": 2}

## Q1 - Log-probability framings (Yes/No, true/false, A/B)

| dataset | n conf | mean margin (logP Yes-No) | mean P(belongs) | mean P(true) | mean P(A right) | verdict/boolean agree % |
|---|---|---|---|---|---|---|
| baseline_withmanual | 3000 | 3.431 | 0.968 | 0.480 | - | 35.333 |
| baseline_nomanual | 3000 | 3.189 | 0.957 | 0.629 | - | 97.000 |
| statement | 3000 | 1.026 | 0.718 | 0.468 | 0.760 | 42.567 |
| statement_rejudge2B | 678 | -1.561 | 0.218 | 0.265 | 0.715 | 90.265 |
| interactive | 6000 | 0.390 | 0.591 | 0.636 | 0.707 | 77.617 |
| interactive_rejudge2B | 562 | -1.261 | 0.249 | 0.278 | 0.761 | 95.907 |
| pydantic_interactive | 0 | - | - | - | - | - |

*Interpretation hints:* a mean |margin| near 0 and P(belongs)~0.5 means the judge is barely distinguishing Yes from No (log-probs uninformative). A `mean P(A right)` far from 0.5 that is stable across ABA/BAB indicates a position/letter bias rather than genuine argument evaluation.

## Q2 - Interactive round: ABA vs BAB

### interactive

| metric | value |
|---|---|
| acc_ABA_pct | 55.37 |
| acc_BAB_pct | 54.33 |
| order_flip_pct | 38.23 |
| both_correct | 1072 |
| only_ABA_correct | 589 |
| only_BAB_correct | 558 |
| both_wrong | 781 |
| metadata_order_flip_rate | 38.00 |

### interactive_rejudge2B

| metric | value |
|---|---|
| acc_ABA_pct | 69.40 |
| acc_BAB_pct | 71.89 |
| order_flip_pct | 29.54 |
| both_correct | 157 |
| only_ABA_correct | 38 |
| only_BAB_correct | 45 |
| both_wrong | 41 |
| metadata_order_flip_rate | None |

## Q3 - Unknown / unforced outputs and fallback usage

| dataset | views | fallback used | invalid predictions |
|---|---|---|---|
| baseline_withmanual | 3000 | 0 | none |
| baseline_nomanual | 3000 | 0 | none |
| statement | 3000 | 896 | none |
| statement_rejudge2B | 678 | 0 | none |
| interactive | 6000 | 4174 | none |
| interactive_rejudge2B | 562 | 0 | none |
| pydantic_interactive | 3000 | 0 | {"'Unknown'": 2} |

## Q4 - Larger 2B judge vs 0.8B judge (matched pairs)

### interactive  (A = 0.8B `interactive_results_full.json`, B = 2B `interactive_results_full_rejudge2B.json`)

| metric | value |
|---|---|
| n_matched | 562 |
| n_scored | 562 |
| both_correct | 312 |
| only_A_correct | 104 |
| only_B_correct | 85 |
| both_wrong | 61 |
| acc_A_pct | 74.02 |
| acc_B_pct | 70.64 |
| prediction_flip_pct | 33.63 |

### statement  (A = 0.8B `statement_results_full.json`, B = 2B `statement_results_full_rejudge2B.json`)

| metric | value |
|---|---|
| n_matched | 678 |
| n_scored | 678 |
| both_correct | 383 |
| only_A_correct | 72 |
| only_B_correct | 154 |
| both_wrong | 69 |
| acc_A_pct | 67.11 |
| acc_B_pct | 79.20 |
| prediction_flip_pct | 33.33 |

## Q5 - Does more input help? baseline -> statement -> interactive

Fair comparison uses the 0.8B judge in every rung. Interactive is shown as ABA (regenerated verdict). Baselines carry no A/B framing.

| rung | n | accuracy % | mean P(belongs) |
|---|---|---|---|
| baseline_nomanual (judge only) | 3000 | 83.33 | 0.957 |
| baseline_withmanual (judge+manual) | 3000 | 80.17 | 0.968 |
| statement (2 essays) | 3000 | 65.67 | 0.718 |
| interactive ABA (3-turn) | 3000 | 55.37 | 0.574 |

## Q6 - Baseline WITH manual vs WITHOUT manual (matched pairs)

A = WITH manual, B = WITHOUT manual.

| metric | value |
|---|---|
| n_matched | 3000 |
| n_scored | 3000 |
| both_correct | 2135 |
| only_A_correct | 270 |
| only_B_correct | 365 |
| both_wrong | 230 |
| acc_A_pct | 80.17 |
| acc_B_pct | 83.33 |
| prediction_flip_pct | 21.17 |

## What is still missing / to run

All expected `_full*.json` datasets were found. Nothing else is required to answer Q1-Q6.

Note: this script only reads `*_full*.json`. Per-chunk completeness (gaps/overlaps/corruption) is the job of the existing read-only `check_progress.py`; run that separately if you want chunk-level status.

