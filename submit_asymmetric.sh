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

# Judge-only asymmetric rerun.
#
# This script intentionally does NOT invoke asymmetric_baseline.py and does not
# reference any 2B/4B larger-judge result or checkpoint. For each chunk it:
#   1. rejudges the previously saved 2B statement arguments with the 0.8B judge;
#   2. rejudges the previously saved 2B ABA transcript with the 0.8B judge.
#
# asymmetric_statement.py and asymmetric_interactive.py must remain judge-only:
# they reuse saved text and load only ./Qwen3.5-0.8B.

set -euo pipefail

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

[[ -d ./Qwen3.5-0.8B ]] || {
    echo "ERROR: Missing local judge model directory: ./Qwen3.5-0.8B" >&2
    exit 2
}
[[ -f pubmed_xmlc_dataset.json ]] || {
    echo "ERROR: Missing pubmed_xmlc_dataset.json" >&2
    exit 2
}

source_exists() {
    local basename="$1"
    [[ -f "$basename" || -f "results/$basename" ]] && return 0
    find results -type f -name "$basename" -print -quit 2>/dev/null | grep -q .
}

STATEMENT_SOURCE="pydantic_statement_results_chunk${CHUNK_ID}.json"
INTERACTIVE_SOURCE="pydantic_interactive_results_chunk${CHUNK_ID}.json"

if ! source_exists "$STATEMENT_SOURCE"; then
    echo "ERROR: Saved statement source is missing: $STATEMENT_SOURCE" >&2
    echo "Run python3 inspect_saved_debate_sources.py before submitting." >&2
    exit 2
fi
if ! source_exists "$INTERACTIVE_SOURCE"; then
    echo "ERROR: Saved interactive source is missing: $INTERACTIVE_SOURCE" >&2
    echo "Run python3 inspect_saved_debate_sources.py before submitting." >&2
    exit 2
fi

COMMON_ARGS=(
    --chunk_id "$CHUNK_ID"
    --total_chunks "$TOTAL_CHUNKS"
)
if [[ "${TEST_MODE:-0}" == "1" ]]; then
    COMMON_ARGS+=(--test_mode)
fi

echo "Job ${SLURM_JOB_ID}; task ${CHUNK_ID}; judge-only asymmetric rerun"
echo "No baseline, 2B debater, or 4B program will be invoked."

echo "Phase 1/2: saved 2B statement arguments -> title-only 0.8B judge"
python3 -u asymmetric_statement.py "${COMMON_ARGS[@]}"

echo "Phase 2/2: saved 2B ABA transcript -> title-only 0.8B judge"
python3 -u asymmetric_interactive.py "${COMMON_ARGS[@]}"

echo "Both judge-only phases complete for chunk ${CHUNK_ID}."
