#!/bin/bash
#SBATCH --job-name=asym_title
#SBATCH --output=logs/asymmetric_%A_%a.out
#SBATCH --error=logs/asymmetric_%A_%a.err
#SBATCH --time=01:00:00
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=4
#SBATCH --mem=32G
#SBATCH --gres=gpu:1
#SBATCH --array=0-3%4

# Judge-only asymmetric re-evaluation, split into four source chunks.
#
# This submission intentionally does NOT run asymmetric_baseline.py because the
# asymmetric title-only baseline is already complete. It also never invokes any
# 2B/4B larger-judge program.
#
# For each chunk it runs, in order:
#   1. asymmetric_statement.py   -- reuse saved 2B statement outputs
#   2. asymmetric_interactive.py -- reuse saved 2B ABA outputs
#
# Both Python programs load only ./Qwen3.5-0.8B as a model. Re-submit this same
# file after a timeout; compatible judge-only checkpoints resume automatically.

set -Eeuo pipefail

cd "${SLURM_SUBMIT_DIR:?Submit this file with sbatch from the project root}"
mkdir -p logs results

module purge
module load Python/3.12.3-GCCcore-13.3.0
source NLPLab_env/bin/activate

export HF_HUB_OFFLINE=1
export TRANSFORMERS_OFFLINE=1
export OMP_NUM_THREADS="${SLURM_CPUS_PER_TASK:-4}"
export TOKENIZERS_PARALLELISM=false
export PYTHONUNBUFFERED=1
export PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True

TOTAL_CHUNKS=4
CHUNK_ID="${SLURM_ARRAY_TASK_ID:?This script must run as a Slurm array}"

if (( CHUNK_ID < 0 || CHUNK_ID >= TOTAL_CHUNKS )); then
    echo "ERROR: Unexpected array task ${CHUNK_ID}; expected 0-3." >&2
    exit 2
fi

COMMON_ARGS=(
    --chunk_id "${CHUNK_ID}"
    --total_chunks "${TOTAL_CHUNKS}"
)

if [[ "${TEST_MODE:-0}" == "1" ]]; then
    COMMON_ARGS+=(--test_mode)
fi

# Refuse to mix completed records from the earlier, incorrect implementation
# (which regenerated debaters) into the corrected judge-only outputs. Run
# prepare_asymmetric_recompute.sh once before the first production submission.
if [[ "${TEST_MODE:-0}" != "1" ]]; then
python3 - "${CHUNK_ID}" <<'PY'
import json
import os
import sys

chunk_id = int(sys.argv[1])
paths = [
    f"results/asymmetric_titleonly_statement_chunk{chunk_id}.json",
    f"results/asymmetric_titleonly_interactive_aba_chunk{chunk_id}.json",
]

bad = []
for path in paths:
    if not os.path.isfile(path):
        continue
    try:
        with open(path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except Exception as exc:
        raise SystemExit(f"ERROR: Cannot safely read existing checkpoint {path}: {exc}")

    if isinstance(payload, dict):
        records = payload.get("results")
    elif isinstance(payload, list):
        records = payload
    else:
        records = None
    if not isinstance(records, list):
        raise SystemExit(f"ERROR: Existing checkpoint has no results list: {path}")

    for index, record in enumerate(records):
        if not isinstance(record, dict):
            bad.append((path, index, "record is not an object"))
            continue
        prediction = str(
            record.get("model_prediction", record.get("prediction", ""))
        ).strip().lower()
        if prediction not in ("yes", "no"):
            continue
        compatible = (
            record.get("debater_outputs_reused") is True
            and record.get("new_debater_generation") is False
            and record.get("judge_received_abstract") is False
        )
        if not compatible:
            bad.append((path, index, "not a verified saved-debate judge-only record"))

if bad:
    preview = "\n".join(
        f"  {path}, record {index}: {reason}"
        for path, index, reason in bad[:10]
    )
    raise SystemExit(
        "ERROR: Incompatible old asymmetric records still exist. They would be "
        "mistakenly skipped on resume. Run ./prepare_asymmetric_recompute.sh once "
        "before submitting.\n" + preview
    )
PY
fi

echo "Job ${SLURM_JOB_ID}, task ${CHUNK_ID}: judge-only asymmetric re-evaluation"
echo "No asymmetric baseline, 2B model, or 4B program will be run."

echo "Phase 1/2: statement -- reuse saved 2B statements; load only 0.8B judge"
python3 -u asymmetric_statement.py "${COMMON_ARGS[@]}"

echo "Phase 2/2: interactive ABA -- reuse saved 2B transcript; load only 0.8B judge"
python3 -u asymmetric_interactive.py "${COMMON_ARGS[@]}"

echo "Both judge-only asymmetric phases are complete for chunk ${CHUNK_ID}."
