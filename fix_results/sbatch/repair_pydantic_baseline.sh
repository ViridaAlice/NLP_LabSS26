#!/bin/bash
#SBATCH --job-name=fix_pybase
#SBATCH --output=Chunks/logs/fix_pybase_%A_%a.log
#SBATCH --time=01:00:00
#SBATCH --signal=B:USR1@180
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=4
#SBATCH --mem=12G
#SBATCH --gres=gpu:1

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${PROJECT_ROOT}"
mkdir -p Chunks/logs Chunks/pydantic_baseline
module purge
module load Python
source NLPLab_env/bin/activate
export HF_HUB_OFFLINE=1
export OMP_NUM_THREADS="${SLURM_CPUS_PER_TASK}"
export PYTHONUNBUFFERED=1
python3 fix_results/repair_worker.py \
  --run pydantic_baseline \
  --chunk-id "${SLURM_ARRAY_TASK_ID}" \
  --total-chunks 1 \
  --max-runtime-minutes 54
