#!/bin/bash
#SBATCH --job-name=stmt_debate
#SBATCH --output=logs/statement_%A_%a.txt
#SBATCH --time=01:00:00
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=4
#SBATCH --mem=32G           # loads both the 2B debater and the 0.8B judge
#SBATCH --gres=gpu:1
#SBATCH --array=0-3

# Statement round (two essays + judge). Writes statement_results_chunk<ID>.json.
# Crash-proof & resumable.

mkdir -p logs
module purge
module load Python
source NLPLab_env/bin/activate

export HF_HUB_OFFLINE=1
export OMP_NUM_THREADS=$SLURM_CPUS_PER_TASK

TOTAL_CHUNKS=4
python3 debate_statement_judge.py \
    --chunk_id $SLURM_ARRAY_TASK_ID \
    --total_chunks $TOTAL_CHUNKS

echo "Statement chunk $SLURM_ARRAY_TASK_ID finished!"
