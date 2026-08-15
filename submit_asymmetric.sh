#!/bin/bash
#SBATCH --job-name=asym_title
#SBATCH --output=logs/asymmetric_%A_%a.out
#SBATCH --error=logs/asymmetric_%A_%a.err
#SBATCH --time=01:00:00
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=4
#SBATCH --mem=32G
#SBATCH --gres=gpu:1
#SBATCH --array=0-7%4

# Judge-only asymmetric rerun.
#
# Array tasks 0-3: statement chunks 0-3, reading only
#   results/pydantic_statement_results_full.json
# Array tasks 4-7: interactive ABA chunks 0-3, reading only
#   results/interactive_results_full_rejudge2B.json
#
# This script intentionally does NOT invoke asymmetric_baseline.py, any 2B
# debater generation, or any 4B program.

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
ARRAY_TASK="${SLURM_ARRAY_TASK_ID:?This script must run as a Slurm array}"
STATEMENT_SOURCE="results/pydantic_statement_results_full.json"
INTERACTIVE_SOURCE="results/interactive_results_full_rejudge2B.json"

if (( ARRAY_TASK < 0 || ARRAY_TASK > 7 )); then
    echo "ERROR: Unexpected array task ${ARRAY_TASK}; expected 0-7." >&2
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

COMMON_ARGS=(--total_chunks "$TOTAL_CHUNKS")
if [[ "${TEST_MODE:-0}" == "1" ]]; then
    COMMON_ARGS+=(--test_mode)
fi

if (( ARRAY_TASK < 4 )); then
    CHUNK_ID="$ARRAY_TASK"
    [[ -f "$STATEMENT_SOURCE" ]] || {
        echo "ERROR: Missing exact statement source: $STATEMENT_SOURCE" >&2
        exit 2
    }

    echo "Job ${SLURM_JOB_ID}; task ${ARRAY_TASK}; statement chunk ${CHUNK_ID}/3"
    echo "Source: ${STATEMENT_SOURCE} (read-only)"
    echo "Only the 0.8B judge will be loaded; no debater will run."
    python3 -u asymmetric_statement.py \
        --chunk_id "$CHUNK_ID" \
        --source_file "$STATEMENT_SOURCE" \
        "${COMMON_ARGS[@]}"
else
    CHUNK_ID="$((ARRAY_TASK - 4))"
    [[ -f "$INTERACTIVE_SOURCE" ]] || {
        echo "ERROR: Missing exact interactive source: $INTERACTIVE_SOURCE" >&2
        exit 2
    }

    echo "Job ${SLURM_JOB_ID}; task ${ARRAY_TASK}; interactive chunk ${CHUNK_ID}/3"
    echo "Source: ${INTERACTIVE_SOURCE} (read-only)"
    echo "Only the 0.8B judge will be loaded; no debater will run."
    python3 -u asymmetric_interactive.py \
        --chunk_id "$CHUNK_ID" \
        --source_file "$INTERACTIVE_SOURCE" \
        "${COMMON_ARGS[@]}"
fi
