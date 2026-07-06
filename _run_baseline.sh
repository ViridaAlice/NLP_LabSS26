#!/bin/bash
#SBATCH --job-name=baseline_manual
#SBATCH --output=logs/baseline_%A_%a.txt
#SBATCH --time=01:00:00
#SBATCH --cpus-per-task=8
#SBATCH --mem=16G
#SBATCH --gres=gpu:1
#SBATCH --array=0-3          # 4 crash-proof chunks; resubmit to resume

# Baseline judge WITH the MeSH indexing manual.
# Each array task processes one chunk and resumes where it left off.

mkdir -p logs
module purge
module load Python
source NLPLab_env/bin/activate

export HF_HUB_OFFLINE=1
export OMP_NUM_THREADS=$SLURM_CPUS_PER_TASK

TOTAL_CHUNKS=$(( SLURM_ARRAY_TASK_MAX - SLURM_ARRAY_TASK_MIN + 1 ))

echo "Baseline (manual) chunk ${SLURM_ARRAY_TASK_ID}/${TOTAL_CHUNKS}"
python3 _pydantic_baseline.py \
    --chunk_id $SLURM_ARRAY_TASK_ID \
    --total_chunks $TOTAL_CHUNKS

echo "Job finished!"
