#!/bin/bash
#SBATCH --job-name=inter_debate
#SBATCH --output=logs/interactive_%A_%a.txt
#SBATCH --time=01:00:00
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=4
#SBATCH --mem=32G
#SBATCH --gres=gpu:1
#SBATCH --array=0-3

# Interactive 3-turn debate, judged in BOTH orders (ABA + BAB, issue #2).
# Writes interactive_results_chunk<ID>.json. Crash-proof & resumable.

mkdir -p logs
module purge
module load Python
source NLPLab_env/bin/activate

export HF_HUB_OFFLINE=1
export OMP_NUM_THREADS=$SLURM_CPUS_PER_TASK

TOTAL_CHUNKS=4
python3 debate_interactive_judge.py \
    --chunk_id $SLURM_ARRAY_TASK_ID \
    --total_chunks $TOTAL_CHUNKS

echo "Interactive chunk $SLURM_ARRAY_TASK_ID finished!"
