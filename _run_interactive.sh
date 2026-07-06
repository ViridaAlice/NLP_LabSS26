#!/bin/bash
#SBATCH --job-name=debate_interactive
#SBATCH --output=logs/interactive_%A_%a.txt
#SBATCH --time=01:00:00
#SBATCH --cpus-per-task=8
#SBATCH --mem=24G
#SBATCH --gres=gpu:1
#SBATCH --array=0-11         # two full debates + two judgings per item -> more chunks

mkdir -p logs
module purge
module load Python
source NLPLab_env/bin/activate

export HF_HUB_OFFLINE=1
export OMP_NUM_THREADS=$SLURM_CPUS_PER_TASK

TOTAL_CHUNKS=$(( SLURM_ARRAY_TASK_MAX - SLURM_ARRAY_TASK_MIN + 1 ))

echo "Interactive (ABA+BAB) chunk ${SLURM_ARRAY_TASK_ID}/${TOTAL_CHUNKS}"
python3 _pydantic_interactive.py \
    --chunk_id $SLURM_ARRAY_TASK_ID \
    --total_chunks $TOTAL_CHUNKS

echo "Job finished!"
