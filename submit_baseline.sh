#!/bin/bash
#SBATCH --job-name=base_manual
#SBATCH --output=logs/base_manual_%A_%a.txt
#SBATCH --time=01:00:00
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=4
#SBATCH --mem=12G
#SBATCH --gres=gpu:1
#SBATCH --array=0-3          # 4 chunks; re-submitting resumes from checkpoints

# Baseline judge WITH the MeSH indexing manual.
# Crash-proof: each array task writes baseline_withmanual_results_chunk<ID>.json
# and resumes where it left off if the 1h limit is hit.

mkdir -p logs
module purge
module load Python
source NLPLab_env/bin/activate

export HF_HUB_OFFLINE=1
export OMP_NUM_THREADS=$SLURM_CPUS_PER_TASK

TOTAL_CHUNKS=4
python3 debate_baseline_judge.py \
    --chunk_id $SLURM_ARRAY_TASK_ID \
    --total_chunks $TOTAL_CHUNKS

echo "Baseline (with manual) chunk $SLURM_ARRAY_TASK_ID finished!"
