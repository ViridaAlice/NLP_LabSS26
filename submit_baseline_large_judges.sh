#!/bin/bash
#SBATCH --job-name=base_large
#SBATCH --output=baseline_large_%A_%a.log
#SBATCH --open-mode=append
#SBATCH --time=01:00:00
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=4
#SBATCH --mem=32G
#SBATCH --gres=gpu:1
#SBATCH --array=0-3
#SBATCH --requeue
#SBATCH --signal=B:USR1@180

# Four exactly paired reruns:
#   task 0: Qwen3.5-2B, no manual
#   task 1: Qwen3.5-2B, with manual
#   task 2: Qwen3.5-4B, no manual
#   task 3: Qwen3.5-4B, with manual
#
# Every task writes one full, atomically checkpointed JSON. At the one-hour
# boundary, SLURM sends USR1 and this script requeues the same array task.

set -uo pipefail

PROJECT_DIR="${SLURM_SUBMIT_DIR:-$PWD}"
cd "$PROJECT_DIR" || exit 1

module purge
module load Python

if [[ ! -f NLPLab_env/bin/activate ]]; then
    echo "ERROR: $PROJECT_DIR/NLPLab_env/bin/activate not found" >&2
    exit 1
fi
# shellcheck disable=SC1091
source NLPLab_env/bin/activate

export HF_HUB_OFFLINE=1
export TRANSFORMERS_OFFLINE=1
export TOKENIZERS_PARALLELISM=false
export OMP_NUM_THREADS="${SLURM_CPUS_PER_TASK:-4}"
export MKL_NUM_THREADS="${SLURM_CPUS_PER_TASK:-4}"
export PYTHONUNBUFFERED=1

TASK_ID="${SLURM_ARRAY_TASK_ID:?This file must be submitted as a SLURM array job}"

case "$TASK_ID" in
    0)
        MODEL_ID="./Qwen3.5-2B"
        MODEL_LABEL="Qwen3.5-2B"
        REFERENCE="results/baseline_nomanual_results_full.json"
        OUTPUT="results/baseline_nomanual_results_full_rejudge2B.json"
        MANUAL_FLAG="--no-manual"
        ;;
    1)
        MODEL_ID="./Qwen3.5-2B"
        MODEL_LABEL="Qwen3.5-2B"
        REFERENCE="results/baseline_withmanual_results_full.json"
        OUTPUT="results/baseline_withmanual_results_full_rejudge2B.json"
        MANUAL_FLAG="--with-manual"
        ;;
    2)
        MODEL_ID="./Qwen3.5-4B"
        MODEL_LABEL="Qwen3.5-4B"
        REFERENCE="results/baseline_nomanual_results_full.json"
        OUTPUT="results/baseline_nomanual_results_full_rejudge4B.json"
        MANUAL_FLAG="--no-manual"
        ;;
    3)
        MODEL_ID="./Qwen3.5-4B"
        MODEL_LABEL="Qwen3.5-4B"
        REFERENCE="results/baseline_withmanual_results_full.json"
        OUTPUT="results/baseline_withmanual_results_full_rejudge4B.json"
        MANUAL_FLAG="--with-manual"
        ;;
    *)
        echo "ERROR: unsupported array task $TASK_ID" >&2
        exit 2
        ;;
esac

for required in \
    rerun_baseline_large_judges.py \
    debate_baseline_judge.py \
    debate_utils.py \
    pubmed_xmlc_dataset.json \
    "$REFERENCE" \
    "$MODEL_ID"; do
    if [[ ! -e "$required" ]]; then
        echo "ERROR: required path not found: $required" >&2
        exit 1
    fi
done

if [[ "$MANUAL_FLAG" == "--with-manual" && ! -f NLM_Indexing_manual.txt ]]; then
    echo "ERROR: NLM_Indexing_manual.txt not found" >&2
    exit 1
fi

CHILD_PID=""
REQUEUE_STARTED=0

requeue_current_task() {
    # Avoid running the handler twice if SLURM sends more than one signal.
    if [[ "$REQUEUE_STARTED" -eq 1 ]]; then
        return
    fi
    REQUEUE_STARTED=1
    trap - USR1

    echo "$(date -Is) USR1 received; requesting checkpoint stop and requeue."
    if [[ -n "$CHILD_PID" ]] && kill -0 "$CHILD_PID" 2>/dev/null; then
        kill -USR1 "$CHILD_PID" 2>/dev/null || true
    fi

    ARRAY_TASK_JOB_ID="${SLURM_ARRAY_JOB_ID}_${SLURM_ARRAY_TASK_ID}"
    if command -v scontrol >/dev/null 2>&1 && \
       scontrol requeue "$ARRAY_TASK_JOB_ID"; then
        echo "Requeue requested for $ARRAY_TASK_JOB_ID"
        exit 0
    fi

    echo "WARNING: automatic requeue failed. The atomic checkpoint is safe." >&2
    echo "Resubmit this array task; it will resume without duplicating records." >&2
    if [[ -n "$CHILD_PID" ]] && kill -0 "$CHILD_PID" 2>/dev/null; then
        kill -TERM "$CHILD_PID" 2>/dev/null || true
    fi
    exit 75
}

terminate_child() {
    trap - TERM INT
    echo "Termination requested; forwarding signal to Python." >&2
    if [[ -n "$CHILD_PID" ]] && kill -0 "$CHILD_PID" 2>/dev/null; then
        kill -TERM "$CHILD_PID" 2>/dev/null || true
        wait "$CHILD_PID" 2>/dev/null || true
    fi
    exit 143
}

trap requeue_current_task USR1
trap terminate_child TERM INT

echo "$(date -Is) starting task=$TASK_ID model=$MODEL_LABEL manual_flag=$MANUAL_FLAG"
echo "reference=$REFERENCE"
echo "output=$OUTPUT"

python3 rerun_baseline_large_judges.py \
    --model-id "$MODEL_ID" \
    --model-label "$MODEL_LABEL" \
    --reference-file "$REFERENCE" \
    --output-file "$OUTPUT" \
    --dataset-path pubmed_xmlc_dataset.json \
    --manual-path NLM_Indexing_manual.txt \
    "$MANUAL_FLAG" &
CHILD_PID=$!

# wait can be interrupted by a shell signal, so continue waiting while the
# process still exists. Disable errexit behavior explicitly around wait.
while true; do
    wait "$CHILD_PID"
    RC=$?
    if kill -0 "$CHILD_PID" 2>/dev/null; then
        continue
    fi
    break
done

trap - USR1 TERM INT

if [[ "$RC" -eq 75 ]]; then
    echo "Python requested a graceful requeue."
    ARRAY_TASK_JOB_ID="${SLURM_ARRAY_JOB_ID}_${SLURM_ARRAY_TASK_ID}"
    if command -v scontrol >/dev/null 2>&1 && \
       scontrol requeue "$ARRAY_TASK_JOB_ID"; then
        exit 0
    fi
    echo "Automatic requeue failed; resubmit safely." >&2
    exit 75
fi

if [[ "$RC" -ne 0 ]]; then
    echo "ERROR: Python exited with status $RC. Checkpoint was preserved." >&2
    exit "$RC"
fi

echo "$(date -Is) completed task=$TASK_ID output=$OUTPUT"
exit 0
