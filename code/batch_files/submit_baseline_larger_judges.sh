#!/bin/bash
#SBATCH --job-name=base_large
#SBATCH --output=slurm-%x-%A_%a.out
#SBATCH --time=01:00:00
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=4
#SBATCH --mem=24G
#SBATCH --gres=gpu:1
#SBATCH --array=12-15%4
#SBATCH --requeue

# Four controlled baseline conditions, each split into four resumable chunks:
#   Qwen3.5-2B without manual, Qwen3.5-2B with manual,
#   Qwen3.5-4B without manual, Qwen3.5-4B with manual.
#
# Run from the project root. If any task reaches the one-hour limit, submit this
# same file again. Completed chunks are validated and skipped; partial chunks
# continue from their last atomically saved record.

set -Euo pipefail

cd "${SLURM_SUBMIT_DIR:?Submit this file with sbatch from the project root}"

module purge
module load Python/3.12.3-GCCcore-13.3.0
source NLPLab_env/bin/activate

export HF_HUB_OFFLINE=1
export TRANSFORMERS_OFFLINE=1
export TOKENIZERS_PARALLELISM=false
export OMP_NUM_THREADS="${SLURM_CPUS_PER_TASK:-4}"
export PYTHONUNBUFFERED=1
export PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True

TOTAL_CHUNKS=4
TASK_ID="${SLURM_ARRAY_TASK_ID:?This script must run as a Slurm array}"
COMBINATION=$(( TASK_ID / TOTAL_CHUNKS ))
CHUNK_ID=$(( TASK_ID % TOTAL_CHUNKS ))

find_reference() {
    local filename="$1"
    local candidate
    for candidate in "results/${filename}" "${filename}"; do
        if [[ -f "${candidate}" ]]; then
            printf '%s\n' "${candidate}"
            return 0
        fi
    done
    echo "ERROR: Could not find ${filename} in results/ or the project root." >&2
    return 1
}

case "${COMBINATION}" in
    0)
        MODEL="./Qwen3.5-2B"
        MODEL_LABEL="2B"
        MODE_FLAG="--no-manual"
        REFERENCE="$(find_reference baseline_nomanual_results_full.json)"
        ;;
    1)
        MODEL="./Qwen3.5-2B"
        MODEL_LABEL="2B"
        MODE_FLAG="--with-manual"
        REFERENCE="$(find_reference baseline_withmanual_results_full.json)"
        ;;
    2)
        MODEL="./Qwen3.5-4B"
        MODEL_LABEL="4B"
        MODE_FLAG="--no-manual"
        REFERENCE="$(find_reference baseline_nomanual_results_full.json)"
        ;;
    3)
        MODEL="./Qwen3.5-4B"
        MODEL_LABEL="4B"
        MODE_FLAG="--with-manual"
        REFERENCE="$(find_reference baseline_withmanual_results_full.json)"
        ;;
    *)
        echo "ERROR: Unexpected array task ${TASK_ID}." >&2
        exit 2
        ;;
esac

[[ -d "${MODEL}" ]] || {
    echo "ERROR: Local model directory does not exist: ${MODEL}" >&2
    exit 2
}
[[ -f pubmed_xmlc_dataset.json ]] || {
    echo "ERROR: pubmed_xmlc_dataset.json is missing from ${PWD}" >&2
    exit 2
}
if [[ "${MODE_FLAG}" == "--with-manual" && ! -f NLM_Indexing_manual.txt ]]; then
    echo "ERROR: NLM_Indexing_manual.txt is missing from ${PWD}" >&2
    exit 2
fi

mkdir -p results results/checkpoints_larger_baselines

echo "Job ${SLURM_JOB_ID}, array task ${TASK_ID}"
echo "Model=${MODEL}; mode=${MODE_FLAG}; chunk=${CHUNK_ID}/${TOTAL_CHUNKS}; reference=${REFERENCE}"

set +e
python3 debate_baseline_larger_judges.py \
    --judge-model "${MODEL}" \
    --model-label "${MODEL_LABEL}" \
    "${MODE_FLAG}" \
    --reference-file "${REFERENCE}" \
    --dataset-path pubmed_xmlc_dataset.json \
    --manual-path NLM_Indexing_manual.txt \
    --checkpoint-dir results/checkpoints_larger_baselines \
    --output-dir results \
    --chunk-id "${CHUNK_ID}" \
    --total-chunks "${TOTAL_CHUNKS}" \
    --max-runtime-minutes 55
STATUS=$?
set -e

if [[ ${STATUS} -eq 75 ]]; then
    echo "Task stopped safely before the Slurm limit. Re-submit this sbatch file to resume."
    exit 0
fi
if [[ ${STATUS} -ne 0 ]]; then
    echo "Task failed with exit status ${STATUS}; its last valid atomic checkpoint is preserved." >&2
    exit "${STATUS}"
fi

echo "Task ${TASK_ID} finished successfully."
