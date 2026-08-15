#!/usr/bin/env bash
set -Eeuo pipefail

# Archive ONLY the old asymmetric statement/interactive judge outputs so that
# they are recomputed from the saved pydantic_* 2B debates. The archive is kept
# outside results/, because check_baseline_runs.py recursively scans results/.
#
# This script does not match, move, edit, or delete:
#   * asymmetric_titleonly_baseline files
#   * pydantic_statement_results files
#   * pydantic_interactive_results files
#   * any 2B/4B larger-judge baseline output or checkpoint

cd "${1:-$PWD}"

if command -v squeue >/dev/null 2>&1; then
    active="$(squeue -h -u "${USER}" -o '%A|%j|%T' 2>/dev/null \
        | grep -E '\|asym_title\|(PENDING|RUNNING|CONFIGURING|COMPLETING|SUSPENDED)$' \
        || true)"
    if [[ -n "${active}" ]]; then
        echo "ERROR: An asymmetric job is still active:" >&2
        echo "${active}" >&2
        echo "Wait for it to finish or cancel it before archiving checkpoints." >&2
        exit 1
    fi
fi

shopt -s nullglob
files=(
    results/asymmetric_titleonly_statement_chunk*.json
    results/asymmetric_titleonly_interactive_aba_chunk*.json
)
shopt -u nullglob

if (( ${#files[@]} == 0 )); then
    echo "No old asymmetric statement/interactive production outputs were found."
    echo "Nothing was changed."
    exit 0
fi

timestamp="$(date +%Y%m%d_%H%M%S)"
archive_dir="asymmetric_recompute_archive/${timestamp}"
mkdir -p "${archive_dir}"

manifest="${archive_dir}/MANIFEST.txt"
{
    echo "Archived at: $(date --iso-8601=seconds 2>/dev/null || date)"
    echo "Reason: force clean recomputation of asymmetric statement and interactive judgments"
    echo "Files:"
} > "${manifest}"

for path in "${files[@]}"; do
    printf '  %s\n' "${path}" | tee -a "${manifest}"
    mv -- "${path}" "${archive_dir}/"
done

echo
echo "Archived ${#files[@]} file(s) to: ${archive_dir}"
echo "The archive is outside results/, so check_baseline_runs.py will not count it."
echo
echo "Not touched:"
echo "  results/asymmetric_titleonly_baseline_chunk*.json"
echo "  results/pydantic_statement_results_chunk*.json"
echo "  results/pydantic_interactive_results_chunk*.json"
echo "  results/*rejudge2B* and results/*rejudge4B*"
echo "  results/checkpoints_larger_baselines/*"
