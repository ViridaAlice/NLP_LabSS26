#!/bin/bash
#SBATCH --job-name=baseline_nomanual
#SBATCH --output=logs/baseline_nomanual_%A_%a.txt
#SBATCH --time=01:00:00
#SBATCH --cpus-per-task=8
#SBATCH --mem=16G
#SBATCH --gres=gpu:1
#SBATCH --array=0-3

# Baseline judge WITHOUT the MeSH indexing manual (issue 5).
# Compare its output file against the run_baseline.sh output.

mkdir -p logs
module purge
module load Python
source NLPLab_env/bin/activate

export HF_HUB_OFFLINE=1
export OMP_NUM_THREADS=$SLURM_CPUS_PER_TASK

TOTAL_CHUNKS=$(( SLURM_ARRAY_TASK_MAX - SLURM_ARRAY_TASK_MIN + 1 ))

echo "Baseline (NO manual) chunk ${SLURM_ARRAY_TASK_ID}/${TOTAL_CHUNKS}"
python3 _pydantic_baseline.py \
    --no_manual \
    --chunk_id $SLURM_ARRAY_TASK_ID \
    --total_chunks $TOTAL_CHUNKS

echo "Job finished!"
