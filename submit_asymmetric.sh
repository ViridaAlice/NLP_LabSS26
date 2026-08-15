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
# read or write any 4B result/checkpoint. Every array task reads the same two
# complete source files, but asymmetric_common.py selects a disjoint quarter:
#
#   results/pydantic_statement_results_full.json
#   results/interactive_results_full_rejudge2B.json
#
# The saved 2B debater text is reused verbatim. Only ./Qwen3.5-0.8B is loaded.

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

STATEMENT_SOURCE="results/pydantic_statement_results_full.json"
INTERACTIVE_SOURCE="results/interactive_results_full_rejudge2B.json"

[[ -f "$STATEMENT_SOURCE" ]] || {
    echo "ERROR: Saved statement source is missing: $STATEMENT_SOURCE" >&2
    exit 2
}
[[ -f "$INTERACTIVE_SOURCE" ]] || {
    echo "ERROR: Saved interactive source is missing: $INTERACTIVE_SOURCE" >&2
    exit 2
}

COMMON_ARGS=(
    --chunk_id "$CHUNK_ID"
    --total_chunks "$TOTAL_CHUNKS"
)
if [[ "${TEST_MODE:-0}" == "1" ]]; then
    COMMON_ARGS+=(--test_mode)
fi

echo "Job ${SLURM_JOB_ID}; task ${CHUNK_ID}; judge-only asymmetric rerun"
echo "Statement source:   ${STATEMENT_SOURCE}"
echo "Interactive source: ${INTERACTIVE_SOURCE}"
echo "No baseline, debater model, or 4B program will be invoked."

echo "Phase 1/2: saved 2B statement arguments -> title-only 0.8B judge"
python3 -u asymmetric_statement.py \
    "${COMMON_ARGS[@]}" \
    --source_file "$STATEMENT_SOURCE"

echo "Phase 2/2: saved 2B ABA transcript -> title-only 0.8B judge"
python3 -u asymmetric_interactive.py \
    "${COMMON_ARGS[@]}" \
    --source_file "$INTERACTIVE_SOURCE"

echo "Both judge-only phases complete for chunk ${CHUNK_ID}."
