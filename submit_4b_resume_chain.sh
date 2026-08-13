#!/usr/bin/env bash
set -euo pipefail

# Queue sequential resume waves for only the Qwen3.5-4B array tasks.
# Assumes the existing task mapping is:
#   8-11  = 4B without manual
#   12-15 = 4B with manual
# Each new wave starts only after the preceding whole array has ended.
# Existing atomic checkpoints are reused by submit_baseline_larger_judges.sh.

WAVES="${1:-10}"
SUBMIT_SCRIPT="${SUBMIT_SCRIPT:-submit_baseline_larger_judges.sh}"
ARRAY_SPEC="${ARRAY_SPEC:-8-15%4}"
JOB_NAME="${JOB_NAME:-base_large}"
LOG_FILE="${LOG_FILE:-results/qwen35_4b_resume_chain_jobids.txt}"

case "$WAVES" in
    ''|*[!0-9]*)
        echo "ERROR: WAVES must be a positive integer." >&2
        exit 2
        ;;
esac
if [ "$WAVES" -lt 1 ]; then
    echo "ERROR: WAVES must be at least 1." >&2
    exit 2
fi

if ! command -v sbatch >/dev/null 2>&1; then
    echo "ERROR: sbatch is not available." >&2
    exit 2
fi
if [ ! -f "$SUBMIT_SCRIPT" ]; then
    echo "ERROR: Submission script not found: $SUBMIT_SCRIPT" >&2
    exit 2
fi

# Concurrent writers must never update the same checkpoint files. Refuse to
# start if an earlier base_large allocation is still pending or running.
active_jobs="$(squeue -h -u "$USER" -o '%A|%j|%T' 2>/dev/null | grep -E '\|base_large\|(PENDING|RUNNING|CONFIGURING|COMPLETING|SUSPENDED)$' || true)"
if [ -n "$active_jobs" ]; then
    echo "ERROR: An active ${JOB_NAME} job already exists:" >&2
    echo "$active_jobs" >&2
    echo "Wait for it to finish or cancel it before creating a resume chain." >&2
    exit 1
fi

mkdir -p "$(dirname "$LOG_FILE")"
{
    echo "# Created: $(date --iso-8601=seconds 2>/dev/null || date)"
    echo "# Array: $ARRAY_SPEC"
    echo "# Submission script: $SUBMIT_SCRIPT"
} >> "$LOG_FILE"

previous_job=""
for wave in $(seq 1 "$WAVES"); do
    args=(--parsable --array="$ARRAY_SPEC")
    if [ -n "$previous_job" ]; then
        args+=(--dependency="afterany:${previous_job}")
    fi

    response="$(sbatch "${args[@]}" "$SUBMIT_SCRIPT")"
    job_id="${response%%;*}"
    job_id="${job_id%%_*}"

    if ! printf '%s' "$job_id" | grep -Eq '^[0-9]+$'; then
        echo "ERROR: Could not parse sbatch response: $response" >&2
        exit 1
    fi

    printf 'wave=%s job_id=%s dependency=%s submitted=%s\n' \
        "$wave" "$job_id" "${previous_job:-none}" \
        "$(date --iso-8601=seconds 2>/dev/null || date)" | tee -a "$LOG_FILE"

    previous_job="$job_id"
done

echo
echo "Queued $WAVES sequential 4B resume waves."
echo "Last job ID: $previous_job"
echo "Job-ID record: $LOG_FILE"
echo
echo "Monitor with:"
echo "  squeue -u \"$USER\""
echo
echo "Cancel the complete chain if necessary with:"
echo "  awk -F'[ =]' '/^wave=/{print \$4}' \"$LOG_FILE\" | xargs -r scancel"
