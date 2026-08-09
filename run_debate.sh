#!/bin/bash
#SBATCH --job-name=ai_debate
#SBATCH --output=debate_log_%A_%a.txt
#SBATCH --array=0-9            # Launch 10 simultaneous jobs
#SBATCH --time=01:00:00        # A bit extra time since we are querying 3 models per article
#SBATCH --ntasks=1             # Number of CPU cores per job
#SBATCH --mem=12G              # Increased RAM slightly just to be safe
#SBATCH --gres=gpu:1           # Request 1 GPU per job

echo "Starting Array Job ID: $SLURM_ARRAY_TASK_ID"

module purge
module load Python
source NLPLab_env/bin/activate

export HF_HUB_OFFLINE=1

# First run with --test_mode. Once you verify it works, remove the flag!
python3 run_ai_debate.py --chunk_id $SLURM_ARRAY_TASK_ID --total_chunks 10 

echo "Job $SLURM_ARRAY_TASK_ID finished!"
