# AI-Debate XMLC -- Question-driven analysis (read-only)

Directory scanned: `/home/s27erahn/NLP_LabSS26`

## 0. File presence & completeness (has anything not gone through?)

| dataset | backend | judge | records | expected | R1 | R2 | R3 | balanced | STATUS |
|---|---|---|---|---|---|---|---|---|---|
| baseline_withmanual | logprob | 0.8B | 3000 | 3000 | 1000 | 1000 | 1000 | yes | COMPLETE |
| baseline_nomanual | logprob | 0.8B | 3000 | 3000 | 1000 | 1000 | 1000 | yes | COMPLETE |
| statement | logprob | 0.8B | 3000 | 3000 | 1000 | 1000 | 1000 | yes | COMPLETE |
| statement_rejudge2B | logprob | 2B | 1287 | 3000 | 500 | 500 | 287 | NO | PARTIAL/INCOMPLETE |
| interactive | logprob | 0.8B | 3000 | 3000 | 1000 | 1000 | 1000 | yes | COMPLETE |
| interactive_rejudge2B | logprob | 2B | 553 | 3000 | 250 | 250 | 53 | NO | PARTIAL/INCOMPLETE |
| pydantic_baseline | pydantic | 0.8B | 3000 | 3000 | 1000 | 1000 | 1000 | yes | COMPLETE |
| pydantic_statement | pydantic | 0.8B | 3000 | 3000 | 1000 | 1000 | 1000 | yes | COMPLETE |
| pydantic_interactive | pydantic | 0.8B | 3000 | 3000 | 1000 | 1000 | 1000 | yes | COMPLETE |

Missing expected files:

## Q3. Unforced / Unknown verdicts (unparsable predictions)

| dataset | backend | views | parsed | DROPPED (unknown) | fallback used | examples |
|---|---|---|---|---|---|---|
| baseline_withmanual | logprob | 3000 | 3000 | 0 | 0 | - |
| baseline_nomanual | logprob | 3000 | 3000 | 0 | 0 | - |
| statement | logprob | 3000 | 3000 | 0 | 896 | - |
| statement_rejudge2B | logprob | 1287 | 1287 | 0 | 0 | - |
| interactive | logprob | 6000 | 6000 | 0 | 4174 | - |
| interactive_rejudge2B | logprob | 1106 | 1106 | 0 | 0 | - |
| pydantic_baseline | pydantic | 3000 | 3000 | 0 | 0 | - |
| pydantic_statement | pydantic | 3000 | 2871 | 129 | 0 | Unknown; Unknown; Unknown; Unknown; Unknown |
| pydantic_interactive | pydantic | 3000 | 2998 | 2 | 0 | Unknown; Unknown |

Logprob runs should show 0 dropped (guaranteed argmax fallback). Any drops in **pydantic_*** are the real 'Unknown' cases (no logprob fallback).

## Q5/Q6. Accuracy, Yes-bias & confidence across formats

| dataset | judge | acc % | R1 | R2 | R3 | pred-Yes % | true-Yes % | Yes-bias pp | verdict margin (mean) | corr(verdict,boolean) | boolean inverted |
|---|---|---|---|---|---|---|---|---|---|---|---|
| baseline_withmanual | 0.8B | 80.2 | 64.6 | 92.8 | 83.1 | 29.6 | 33.3 | -3.8 | 3.431 | 0.475 | no |
| baseline_nomanual | 0.8B | 83.3 | 76.9 | 91.2 | 81.9 | 34.6 | 33.3 | 1.3 | 3.189 | 0.626 | no |
| statement | 0.8B | 65.7 | 72.0 | 62.7 | 62.3 | 49.0 | 33.3 | 15.7 | 1.026 | 0.510 | no |
| statement_rejudge2B | 2B | 78.9 | 56.6 | 92.8 | 93.4 | 26.3 | 38.9 | -12.6 | -1.543 | 0.760 | no |
| interactive | 0.8B | 54.9 | 77.7 | 45.6 | 41.2 | 63.6 | 33.3 | 30.3 | 0.390 | 0.325 | no |
| interactive_rejudge2B | 2B | 74.7 | 69.6 | 80.2 | 72.6 | 43.0 | 45.2 | -2.2 | -1.802 | 0.796 | no |
| pydantic_baseline | 0.8B | 80.1 | 73.2 | 90.2 | 77.0 | 35.3 | 33.3 | 2.0 | n/a | n/a | no |
| pydantic_statement | 0.8B | 78.0 | 65.2 | 88.9 | 78.9 | 31.7 | 31.7 | -0.1 | n/a | n/a | no |
| pydantic_interactive | 0.8B | 66.7 | 65.3 | 71.1 | 63.8 | 43.5 | 33.3 | 10.2 | n/a | n/a | no |

## Q1. Judge decision log-probs across framings

verdict margin = logprob(Yes)-logprob(No); boolean margin = logprob(true)-logprob(false); debater margin = logprob(A)-logprob(B). P(A right) present only for statement/interactive.

| dataset | n_conf | P(belongs) | P(true) | P(A right) | verdict margin | boolean margin | debater margin | margin when CORRECT | margin when WRONG |
|---|---|---|---|---|---|---|---|---|---|
| baseline_withmanual | 3000 | 0.968 | 0.480 | n/a | 3.431 | -0.082 | n/a | 3.413 | 3.508 |
| baseline_nomanual | 3000 | 0.957 | 0.629 | n/a | 3.189 | 0.537 | n/a | 3.164 | 3.315 |
| statement | 3000 | 0.718 | 0.468 | 0.760 | 1.026 | -0.133 | 1.239 | 1.024 | 1.031 |
| statement_rejudge2B | 1287 | 0.222 | 0.264 | 0.717 | -1.543 | -1.079 | 0.961 | -1.657 | -1.118 |
| interactive | 6000 | 0.591 | 0.636 | 0.707 | 0.390 | 0.576 | 0.998 | 0.321 | 0.474 |
| interactive_rejudge2B | 1106 | 0.178 | 0.228 | 0.769 | -1.802 | -1.318 | 1.255 | -1.836 | -1.700 |
| pydantic_baseline | 0 | n/a | n/a | n/a | n/a | n/a | n/a | n/a | n/a |
| pydantic_statement | 0 | n/a | n/a | n/a | n/a | n/a | n/a | n/a | n/a |
| pydantic_interactive | 0 | n/a | n/a | n/a | n/a | n/a | n/a | n/a | n/a |

P(A right) > 0.5 across the board => positional bias toward debater A (first speaker).

## Q2. ABA vs BAB (interactive order effect)

| dataset | n | acc ABA % | acc BAB % | order-flip % | flips Yes->No | flips No->Yes | mean P(A right) ABA | mean P(A right) BAB |
|---|---|---|---|---|---|---|---|---|
| interactive | 3000 | 55.4 | 54.3 | 38.2 | 550 | 597 | 0.814 | 0.599 |
| interactive_rejudge2B | 553 | 75.0 | 74.3 | 30.0 | 69 | 97 | 0.769 | 0.769 |
| pydantic_interactive | 0 | 0.0 | 0.0 | 0.0 | 0 | 0 | n/a | n/a |

## Q4. Larger 2B judge vs 0.8B judge (SHARED subset only)

| comparison | shared (stage,pmid) | acc 0.8B % | acc 2B % | delta pp |
|---|---|---|---|---|
| statement: 0.8B vs 2B | 1287 | 66.82 | 78.87 | 12.04 |
| interactive: 0.8B vs 2B | 553 | 59.76 | 74.68 | 14.92 |

Comparison is restricted to records the 2B rejudge actually covered, so it is apples-to-apples despite the rejudge files being partial.


## is_correct cross-check (data integrity)

| dataset | recomputed-vs-stored mismatches |
|---|---|
| baseline_withmanual | 0 |
| baseline_nomanual | 0 |
| statement | 0 |
| statement_rejudge2B | 0 |
| interactive | 0 |
| interactive_rejudge2B | 0 |
| pydantic_baseline | 0 |
| pydantic_statement | 0 |
| pydantic_interactive | 0 |
