# Result repair and completion

This directory finishes the incomplete result files without recomputing valid records.

## Matched original scripts

- `submit_rejudge.sh` → `debate_rejudge_large.py`
  - Handles both `interactive_results_full_rejudge2B.json` and `statement_results_full_rejudge2B.json`.
  - The original rejudge script is resumable but not chunkable, so this package uses a chunk-safe worker that calls the same judging functions.
- `pydantic_baseline.py` generated `pydantic_baseline_results_full.json`.
  - `pydantic_fix_unknowns.py` contains the relevant retry idea, but no attached submit script correctly runs it.
- `pydantic_statement.py` generated `pydantic_statement_results_full.json`.
  - No attached `.sh` file matches this run.
- Do not use `run_debate2.sh`: it runs the non-Pydantic `run_ai_debate2.py` experiment.
- Do not use `run_retries.sh`: it calls the unattached `retry_unknowns.py`.

## What is repaired

- 2B interactive rejudge: reuses stored ABA/BAB debates; runs only the 2B judge.
- 2B statement rejudge: reuses stored PRO/CON arguments; runs only the 2B judge.
- Pydantic baseline: rejudges only invalid/Unknown records.
- Pydantic statement:
  - rejudges invalid/Unknown records using their stored arguments;
  - generates debater arguments and a judgment only for genuinely missing records.

Valid records in either the current final file or an existing repair chunk are skipped.

## Directory layout

Place this directory at:

```text
PROJECT_ROOT/fix_results/
```

The project root must also contain:

```text
results/
pubmed_xmlc_dataset.json
NLM_Indexing_manual.txt
debate_utils.py
debate_rejudge_large.py
debate_statement_judge.py
debate_interactive_judge.py
Qwen3.5-0.8B/
Qwen3.5-2B/
NLPLab_env/
```

Repair checkpoints and logs are written beneath:

```text
PROJECT_ROOT/Chunks/
```

## Usage

First inspect the current state without submitting anything:

```bash
python3 fix_results/manage_results.py --status
```

Submit only missing array tasks:

```bash
python3 fix_results/manage_results.py --submit
```

After jobs finish or hit the one-hour limit, run the same command again:

```bash
python3 fix_results/manage_results.py --submit
```

It merges a run automatically when all 3,000 unique records have valid predictions. Repeated execution is safe.

Optional continuous monitoring from a stable login session:

```bash
python3 fix_results/manage_results.py --watch --poll-seconds 120
```

A convenience wrapper is also available:

```bash
bash fix_results/run_repairs.sh
```

## Safety properties

- Atomic JSON checkpoint after every completed record.
- Deterministic chunk assignment.
- Existing valid records are never regenerated.
- Invalid records are replaced only after a valid Yes/No result is obtained.
- SLURM signal and runtime guards stop between records.
- Per-chunk file locks prevent two jobs from writing the same checkpoint.
- Final files are replaced atomically only after validation finds exactly 3,000 unique valid records.

## Important notes

- `Chunks` means `PROJECT_ROOT/Chunks`, not filesystem `/Chunks`.
- The two BAB-swapped files are already complete duplicates and are not submitted again.
- A missing Pydantic statement record has no earlier candidate-tag choice to recover. Its positive candidate and A/B assignment are therefore selected deterministically. Existing records retain their original candidate tags, arguments, and ordering.
- ABA/BAB and statement arguments are not regenerated during the 2B rejudges.
- If the cluster limits the number of simultaneous array tasks, reduce the `TOTAL_CHUNKS` value consistently in both `manage_results.py` and the corresponding `.sh` file before the first repair submission. Do not change it after chunks have been created.
