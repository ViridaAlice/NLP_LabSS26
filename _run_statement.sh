#!/bin/bash
#SBATCH --job-name=debate_statement
#SBATCH --output=logs/statement_%A_%a.txt
#SBATCH --time=01:00:00
#SBATCH --cpus-per-task=8
#SBATCH --mem=24G
#SBATCH --gres=gpu:1
#SBATCH --array=0-7          # more chunks: debate + double-judging is heavier

mkdir -p logs
module purge
module load Python
source NLPLab_env/bin/activate

export HF_HUB_OFFLINE=1
export OMP_NUM_THREADS=$SLURM_CPUS_PER_TASK

TOTAL_CHUNKS=$(( SLURM_ARRAY_TASK_MAX - SLURM_ARRAY_TASK_MIN + 1 ))

echo "Statement chunk ${SLURM_ARRAY_TASK_ID}/${TOTAL_CHUNKS}"
python3 _pydantic_statement.py \
    --chunk_id $SLURM_ARRAY_TASK_ID \
    --total_chunks $TOTAL_CHUNKS

echo "Job finished!"
