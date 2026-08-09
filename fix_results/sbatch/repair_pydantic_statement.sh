#!/bin/bash
#SBATCH --job-name=fix_pystmt
#SBATCH --output=Chunks/logs/fix_pystmt_%A_%a.log
#SBATCH --time=01:00:00
#SBATCH --signal=B:USR1@180
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=4
#SBATCH --mem=32G
#SBATCH --gres=gpu:1

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${PROJECT_ROOT}"
mkdir -p Chunks/logs Chunks/pydantic_statement
module purge
module load Python
source NLPLab_env/bin/activate
export HF_HUB_OFFLINE=1
export OMP_NUM_THREADS="${SLURM_CPUS_PER_TASK}"
export PYTHONUNBUFFERED=1
python3 fix_results/repair_worker.py \
  --run pydantic_statement \
  --chunk-id "${SLURM_ARRAY_TASK_ID}" \
  --total-chunks 24 \
  --max-runtime-minutes 54
