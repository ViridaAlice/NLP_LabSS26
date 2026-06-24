#!/bin/bash
#SBATCH --job-name=fix_unknowns
#SBATCH --output=logs/fix_%A_%a.txt
#SBATCH --time=01:00:00        # 1-hour time limit
#SBATCH --ntasks=2
#SBATCH --mem=8G               # 8G is enough for just the Judge model
#SBATCH --gres=gpu:1           # 1 GPU per task

# ==============================================================================
# --- CONFIGURATION: SELECT WHICH FILE(S) TO FIX ---
# Set TARGET_TASK to:
#   0  -> Fix Baseline ("pydantic_baseline_results_full.json")
#   1  -> Fix Statement ("pydantic_statement_results_full.json")
#   2  -> Fix Interactive ("pydantic_interactive_results_full.json")
#
# If you want to run multiple files at once in parallel, use the --array line:
#   To run all three:      #SBATCH --array=0-2   and set TARGET_TASK=$SLURM_ARRAY_TASK_ID
#   To run only Statement: #SBATCH --array=1     and set TARGET_TASK=$SLURM_ARRAY_TASK_ID
# ==============================================================================
SBATCH --array=0-2

TARGET_TASK=$SLURM_ARRAY_TASK_ID
# ==============================================================================

echo "Starting Fix Unknowns Job on Bender..."
echo "Targeting Task ID: $TARGET_TASK"

module purge
module load Python
source NLPLab_env/bin/activate

export HF_HUB_OFFLINE=1

# Execute the python script targeting your chosen task ID
python3 pydantic_fix_unknowns.py --task_id $TARGET_TASK

echo "Job finished!"
