#!/bin/bash
#SBATCH --job-name=fix_unknowns
#SBATCH --output=retry_log.txt
#SBATCH --time=01:00:00        # Only takes a few minutes
#SBATCH --ntasks=1
#SBATCH --mem=8G
#SBATCH --gres=gpu:1

echo "Starting Retry Script on Bender..."

module purge
module load Python
source NLPLab_env/bin/activate
export HF_HUB_OFFLINE=1

python3 retry_unknowns.py

echo "Retries complete!"
