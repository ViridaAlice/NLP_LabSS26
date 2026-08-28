#!/bin/bash
#SBATCH --job-name=base_nomanual
#SBATCH --output=logs/base_nomanual_%A_%a.txt
#SBATCH --time=01:00:00
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=4
#SBATCH --mem=12G
#SBATCH --gres=gpu:1
#SBATCH --array=0-3

# Baseline judge WITHOUT the MeSH indexing manual (issue #5, for comparison).
# Writes baseline_nomanual_results_chunk<ID>.json -> separate from the with-manual run.

mkdir -p logs
module purge
module load Python
source NLPLab_env/bin/activate

export HF_HUB_OFFLINE=1
export OMP_NUM_THREADS=$SLURM_CPUS_PER_TASK

TOTAL_CHUNKS=4
python3 debate_baseline_judge.py \
    --no_manual \
    --chunk_id $SLURM_ARRAY_TASK_ID \
    --total_chunks $TOTAL_CHUNKS

echo "Baseline (no manual) chunk $SLURM_ARRAY_TASK_ID finished!"
