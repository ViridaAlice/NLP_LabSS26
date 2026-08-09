#!/bin/bash
#SBATCH --job-name=interactive_debate
#SBATCH --output=int_debate_log_%A_%a.txt
#SBATCH --array=0-20            # Launch 20 simultaneous chunks
#SBATCH --time=01:00:00        # Extended time for multi-turn generation
#SBATCH --ntasks=1             
#SBATCH --mem=12G              
#SBATCH --gres=gpu:1           

echo "Starting Interactive Debate Array Job ID: $SLURM_ARRAY_TASK_ID"

module purge
module load Python
source NLPLab_env/bin/activate

export HF_HUB_OFFLINE=1

# Change --test_mode to a full run when ready
python3 run_interactive_debate.py --chunk_id $SLURM_ARRAY_TASK_ID --total_chunks 20 

echo "Job $SLURM_ARRAY_TASK_ID finished!"
