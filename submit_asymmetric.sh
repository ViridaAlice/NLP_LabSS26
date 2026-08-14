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

# Per chunk, phases run in this order:
#   1. title-only baseline (0.8B judge)
#   2. two independent statements (2B debaters, 0.8B judge)
#   3. interactive ABA debate (2B debaters, 0.8B judge)
# Every phase checkpoints after each record. Re-submit this same file after a
# timeout; completed records and completed phases are skipped automatically.

set -euo pipefail

cd "${SLURM_SUBMIT_DIR:-$PWD}"
mkdir -p logs results

module purge
module load Python/3.12.3-GCCcore-13.3.0
source NLPLab_env/bin/activate

export HF_HUB_OFFLINE=1
export OMP_NUM_THREADS="${SLURM_CPUS_PER_TASK:-4}"
export TOKENIZERS_PARALLELISM=false
export PYTHONUNBUFFERED=1

TOTAL_CHUNKS=4
COMMON_ARGS=(
    --chunk_id "${SLURM_ARRAY_TASK_ID}"
    --total_chunks "${TOTAL_CHUNKS}"
)

if [[ "${TEST_MODE:-0}" == "1" ]]; then
    COMMON_ARGS+=(--test_mode)
fi

echo "Job ${SLURM_JOB_ID}, task ${SLURM_ARRAY_TASK_ID}: asymmetric title-only pipeline"
echo "Phase 1/3: baseline"
python3 -u asymmetric_baseline.py "${COMMON_ARGS[@]}"

echo "Phase 2/3: statement"
python3 -u asymmetric_statement.py "${COMMON_ARGS[@]}"

echo "Phase 3/3: interactive ABA"
python3 -u asymmetric_interactive.py "${COMMON_ARGS[@]}"

echo "All asymmetric phases complete for chunk ${SLURM_ARRAY_TASK_ID}."
