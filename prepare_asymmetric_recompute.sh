#!/usr/bin/env bash
set -euo pipefail

# Default: dry run. Use --apply to archive only the asymmetric statement and
# interactive target files. Baseline files, saved source debates, and all
# rejudge2B/rejudge4B files are outside the explicit patterns below.

usage() {
    echo "Usage: $0 [--apply]" >&2
}

APPLY=0
case "${1:-}" in
    "") ;;
    --apply) APPLY=1 ;;
    -h|--help)
        usage
        exit 0
        ;;
    *)
        usage
        exit 2
        ;;
esac
if (( $# > 1 )); then
    usage
    exit 2
fi

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd -- "$SCRIPT_DIR"

shopt -s nullglob
files=(
    results/asymmetric_titleonly_statement_chunk*.json
    results/asymmetric_titleonly_interactive_aba_chunk*.json
)
shopt -u nullglob

if (( ${#files[@]} == 0 )); then
    echo "No asymmetric statement/interactive target files were found."
    echo "Nothing to archive."
    exit 0
fi

if (( APPLY == 0 )); then
    echo "DRY RUN: the following files would be archived:"
    printf '  %s\n' "${files[@]}"
    echo
    echo "No files were changed. Apply with:"
    echo "  $0 --apply"
    exit 0
fi

stamp="$(date +%Y%m%d_%H%M%S)"
archive_dir="asymmetric_recompute_archive/${stamp}"
mkdir -p "$archive_dir"

for path in "${files[@]}"; do
    mv -- "$path" "$archive_dir/"
done

printf 'Archived %d file(s) to: %s\n' "${#files[@]}" "$archive_dir"
echo "The archive is outside results/, so check_baseline_runs.py will not count it."
echo
echo "Not touched:"
echo "  results/asymmetric_titleonly_baseline_chunk*.json"
echo "  saved pydantic statement/interactive source files"
echo "  results/*rejudge2B* and results/*rejudge4B*"
echo "  results/checkpoints_larger_baselines/*"
