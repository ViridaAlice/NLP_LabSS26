#!/bin/bash
#SBATCH --job-name=rejudge_big
#SBATCH --output=logs/rejudge_%A_%a.txt
#SBATCH --time=01:00:00
#SBATCH --cpus-per-task=8
#SBATCH --mem=48G            # larger judge model needs more memory
#SBATCH --gres=gpu:1
#SBATCH --array=0-3

# Recycle the debates already stored in the output files and re-run ONLY the
# judge with a larger model (issue 3). Choose which file to recycle below.

mkdir -p logs
module purge
module load Python
source NLPLab_env/bin/activate

export HF_HUB_OFFLINE=1
export OMP_NUM_THREADS=$SLURM_CPUS_PER_TASK

# ---- Pick the source file to recycle ----
# INPUT_FILE=pydantic_statement_results_full.json
INPUT_FILE=pydantic_interactive_results_full.json
JUDGE_MODEL=./Qwen3.5-8B

TOTAL_CHUNKS=$(( SLURM_ARRAY_TASK_MAX - SLURM_ARRAY_TASK_MIN + 1 ))

echo "Re-judging ${INPUT_FILE} with ${JUDGE_MODEL} | chunk ${SLURM_ARRAY_TASK_ID}/${TOTAL_CHUNKS}"
python3 _rejudge.py \
    --input_file $INPUT_FILE \
    --judge_model $JUDGE_MODEL \
    --chunk_id $SLURM_ARRAY_TASK_ID \
    --total_chunks $TOTAL_CHUNKS

echo "Job finished!"
