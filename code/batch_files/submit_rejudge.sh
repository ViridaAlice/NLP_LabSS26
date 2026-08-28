#!/bin/bash
#SBATCH --job-name=rejudge2B
#SBATCH --output=logs/rejudge2B_%A_%a.txt
#SBATCH --time=01:00:00
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=4
#SBATCH --mem=24G           # only the 2B judge is loaded here
#SBATCH --gres=gpu:1
#SBATCH --array=0-1         # task 0 = interactive, task 1 = statement

# Re-judge recycled debates with the LARGER 2B judge (issue #3).
# No debaters are re-run. Crash-proof & resumable.
#   array task 0 -> interactive_results_full.json
#   array task 1 -> statement_results_full.json

mkdir -p logs
module purge
module load Python
source NLPLab_env/bin/activate

export HF_HUB_OFFLINE=1
export OMP_NUM_THREADS=$SLURM_CPUS_PER_TASK

if [ "$SLURM_ARRAY_TASK_ID" -eq 0 ]; then
    python3 debate_rejudge_large.py --mode interactive --source interactive_results_full.json
else
    python3 debate_rejudge_large.py --mode statement  --source statement_results_full.json
fi

echo "Rejudge task $SLURM_ARRAY_TASK_ID finished!"
