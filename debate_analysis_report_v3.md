# AI-Debate XMLC - analysis report v3

Directory scanned: `/home/s27erahn/NLP_LabSS26`

## Exclusion report (unparsable / Unknown views disregarded)

| dataset | views | disregarded | disregarded % | clean |
|---|---|---|---|---|
| baseline_withmanual | 3000 | 0 | 0.0 | 3000 |
| baseline_nomanual | 3000 | 0 | 0.0 | 3000 |
| statement | 3000 | 0 | 0.0 | 3000 |
| statement_rejudge2B | 3000 | 0 | 0.0 | 3000 |
| interactive | 6000 | 0 | 0.0 | 6000 |
| interactive_rejudge2B | 6000 | 0 | 0.0 | 6000 |
| pydantic_interactive | 3000 | 2 | 0.07 | 2998 |
| pydantic_statement | 3000 | 129 | 4.3 | 2871 |
| pydantic_baseline | 3000 | 0 | 0.0 | 3000 |

## Accuracy + Yes-bias (clean set only)

| dataset | clean | truth-known | acc % | pred-Yes % | true-Yes % | bias (pp) |
|---|---|---|---|---|---|---|
| baseline_withmanual | 3000 | 3000 | 80.17 | 29.57 | 33.33 | -3.76 |
| baseline_nomanual | 3000 | 3000 | 83.33 | 34.6 | 33.33 | 1.27 |
| statement | 3000 | 3000 | 65.67 | 49.0 | 33.33 | 15.67 |
| statement_rejudge2B | 3000 | 3000 | 79.5 | 24.57 | 33.33 | -8.76 |
| interactive | 6000 | 6000 | 54.85 | 63.62 | 33.33 | 30.29 |
| interactive_rejudge2B | 6000 | 6000 | 74.63 | 38.57 | 33.33 | 5.24 |
| pydantic_interactive | 2998 | 2998 | 66.74 | 43.46 | 33.29 | 10.17 |
| pydantic_statement | 2871 | 2871 | 77.99 | 31.66 | 31.73 | -0.07 |
| pydantic_baseline | 3000 | 3000 | 80.13 | 35.33 | 33.33 | 2.0 |

## Order / position effect (interactive)

| dataset | order pairs | order-flip % | mean P(A right) |
|---|---|---|---|
| interactive | 3000 | 38.23 | 0.707 |
| interactive_rejudge2B | 3000 | 30.27 | 0.771 |

## Confidence / framing guard

| dataset | mean margin | mean P(belongs) | mean P(true) | verdict/boolean agree % | boolean degenerate |
|---|---|---|---|---|---|
| baseline_withmanual | 3.431 | 0.968 | 0.48 | 65.5 | True |
| baseline_nomanual | 3.189 | 0.957 | 0.629 | 37.27 | True |
| statement | 1.026 | 0.718 | 0.468 | 56.93 | True |
| statement_rejudge2B | -1.588 | 0.213 | 0.26 | 76.83 | False |
| interactive | 0.39 | 0.591 | 0.636 | 64.07 | False |
| interactive_rejudge2B | -1.844 | 0.17 | 0.218 | 62.58 | False |
| pydantic_interactive | None | None | None | None | False |
| pydantic_statement | None | None | None | None | False |
| pydantic_baseline | None | None | None | None | False |

## Per-stage accuracy & Yes-bias

### baseline_withmanual

| stage | n | acc % | pred-Yes % | true-Yes % |
|---|---|---|---|---|
| Round 1: True Tag | 1000 | 64.6 | 64.6 | 100.0 |
| Round 2: Unrelated Tag | 1000 | 92.8 | 7.2 | 0.0 |
| Round 3: Similar Tag | 1000 | 83.1 | 16.9 | 0.0 |

### baseline_nomanual

| stage | n | acc % | pred-Yes % | true-Yes % |
|---|---|---|---|---|
| Round 1: True Tag | 1000 | 76.9 | 76.9 | 100.0 |
| Round 2: Unrelated Tag | 1000 | 91.2 | 8.8 | 0.0 |
| Round 3: Similar Tag | 1000 | 81.9 | 18.1 | 0.0 |

### statement

| stage | n | acc % | pred-Yes % | true-Yes % |
|---|---|---|---|---|
| Round 1: True Tag | 1000 | 72.0 | 72.0 | 100.0 |
| Round 2: Unrelated Tag | 1000 | 62.7 | 37.3 | 0.0 |
| Round 3: Similar Tag | 1000 | 62.3 | 37.7 | 0.0 |

### statement_rejudge2B

| stage | n | acc % | pred-Yes % | true-Yes % |
|---|---|---|---|---|
| Round 1: True Tag | 1000 | 56.1 | 56.1 | 100.0 |
| Round 2: Unrelated Tag | 1000 | 93.7 | 6.3 | 0.0 |
| Round 3: Similar Tag | 1000 | 88.7 | 11.3 | 0.0 |

### interactive

| stage | n | acc % | pred-Yes % | true-Yes % |
|---|---|---|---|---|
| Round 1: True Tag | 2000 | 77.7 | 77.7 | 100.0 |
| Round 2: Unrelated Tag | 2000 | 45.65 | 54.35 | 0.0 |
| Round 3: Similar Tag | 2000 | 41.2 | 58.8 | 0.0 |

### interactive_rejudge2B

| stage | n | acc % | pred-Yes % | true-Yes % |
|---|---|---|---|---|
| Round 1: True Tag | 2000 | 69.8 | 69.8 | 100.0 |
| Round 2: Unrelated Tag | 2000 | 80.25 | 19.75 | 0.0 |
| Round 3: Similar Tag | 2000 | 73.85 | 26.15 | 0.0 |

### pydantic_interactive

| stage | n | acc % | pred-Yes % | true-Yes % |
|---|---|---|---|---|
| Round 1: True Tag | 998 | 65.33 | 65.33 | 100.0 |
| Round 2: Unrelated Tag | 1000 | 71.1 | 28.9 | 0.0 |
| Round 3: Similar Tag | 1000 | 63.8 | 36.2 | 0.0 |

### pydantic_statement

| stage | n | acc % | pred-Yes % | true-Yes % |
|---|---|---|---|---|
| Round 1: True Tag | 911 | 65.2 | 65.2 | 100.0 |
| Round 2: Unrelated Tag | 986 | 88.95 | 11.05 | 0.0 |
| Round 3: Similar Tag | 974 | 78.85 | 21.15 | 0.0 |

### pydantic_baseline

| stage | n | acc % | pred-Yes % | true-Yes % |
|---|---|---|---|---|
| Round 1: True Tag | 1000 | 73.2 | 73.2 | 100.0 |
| Round 2: Unrelated Tag | 1000 | 90.2 | 9.8 | 0.0 |
| Round 3: Similar Tag | 1000 | 77.0 | 23.0 | 0.0 |