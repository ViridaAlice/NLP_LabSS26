#!/bin/bash
#SBATCH --job-name=bab_label_swap
#SBATCH --output=logs/bab_label_swap_%A_%a.txt
#SBATCH --time=01:00:00
#SBATCH --signal=B:USR1@180
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=4
#SBATCH --mem=32G
#SBATCH --gres=gpu:1
#SBATCH --array=0-11

# Re-judges existing BAB debates after swapping only the displayed A/B labels.
#
# Source: B opening -> A rebuttal -> B closing
# Shown:  A opening -> B rebuttal -> A closing
#
# No debater model is loaded and no debate text is regenerated.
# Each array task writes a new, resumable chunk file. Once all 12 chunks are
# complete, the last finishing task also creates:
#   interactive_results_BAB_swapped_labels_full.json
#
# If the one-hour limit interrupts a task, submit this same script again.
# Completed records and completed chunks are skipped automatically.

set -euo pipefail

mkdir -p logs
module purge
module load Python
source NLPLab_env/bin/activate

export HF_HUB_OFFLINE=1
export OMP_NUM_THREADS="${SLURM_CPUS_PER_TASK}"
export PYTHONUNBUFFERED=1

TOTAL_CHUNKS=12

python3 judge_bab_swapped_labels.py \
    --input_results interactive_results_full.json \
    --output_prefix interactive_results_BAB_swapped_labels \
    --chunk_id "${SLURM_ARRAY_TASK_ID}" \
    --total_chunks "${TOTAL_CHUNKS}" \
    --max_runtime_minutes 54 \
    --max_retries 1 \
    --merge_when_complete

echo "BAB label-swap judge chunk ${SLURM_ARRAY_TASK_ID} stopped safely or finished."
