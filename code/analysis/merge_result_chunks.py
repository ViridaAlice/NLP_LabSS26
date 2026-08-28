#!/usr/bin/env python3
"""Merge evaluation-result chunks into *_full.json files.

The script searches:

1. The top level of the results directory.
2. The checkpoints_larger_baselines directory recursively.

For each possible output file, the candidate with the largest number of
records is selected. Modification time breaks ties between candidates.

An existing *_full.json is overwritten only when the selected candidate
contains more records.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable


CHUNK_PATTERN = re.compile(
    r"^(?P<before>.+)_chunk(?P<number>\d+)(?P<after>.*)\.json$"
)


@dataclass
class LoadedResults:
    path: Path
    metadata: dict[str, Any]
    results: list[Any]
    modified: float


@dataclass
class Candidate:
    target_name: str
    data: dict[str, Any]
    source_files: list[Path]
    modified: float
    description: str

    @property
    def record_count(self) -> int:
        return len(self.data["results"])


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Merge JSON result chunks, including chunks under "
            "checkpoints_larger_baselines."
        )
    )
    parser.add_argument(
        "--results-dir",
        type=Path,
        default=Path("results"),
        help="Results directory (default: results).",
    )
    parser.add_argument(
        "--checkpoint-dir",
        type=Path,
        default=Path("checkpoints_larger_baselines"),
        help=(
            "Checkpoint directory. Relative paths are resolved underneath "
            "--results-dir (default: checkpoints_larger_baselines)."
        ),
    )
    parser.add_argument(
        "--prefix",
        help=(
            "Only process output filenames beginning with this prefix, "
            "for example asymmetric_titleonly_baseline."
        ),
    )
    parser.add_argument(
        "--no-checkpoints",
        action="store_true",
        help="Do not inspect the checkpoint directory.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would happen without writing files.",
    )
    return parser.parse_args()


def load_results_file(path: Path) -> LoadedResults:
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)

    if isinstance(data, list):
        metadata: dict[str, Any] = {}
        results = data
    elif isinstance(data, dict) and isinstance(data.get("results"), list):
        raw_metadata = data.get("metadata", {})
        metadata = dict(raw_metadata) if isinstance(raw_metadata, dict) else {}
        results = data["results"]
    else:
        raise ValueError(
            "Expected a JSON list or an object containing a 'results' list"
        )

    return LoadedResults(
        path=path,
        metadata=metadata,
        results=results,
        modified=path.stat().st_mtime,
    )


def chunk_target(path: Path) -> tuple[str, int] | None:
    """Return the canonical full filename and chunk number."""

    match = CHUNK_PATTERN.match(path.name)
    if not match:
        return None

    target_name = (
        f"{match.group('before')}_full{match.group('after')}.json"
    )
    return target_name, int(match.group("number"))


def relative_display(path: Path, results_dir: Path) -> str:
    try:
        return path.resolve().relative_to(results_dir.resolve()).as_posix()
    except ValueError:
        return str(path)


def calculate_accuracy(results: Iterable[Any]) -> float | None:
    values: list[bool] = []

    for record in results:
        if not isinstance(record, dict):
            continue

        is_correct = record.get("is_correct")
        if isinstance(is_correct, bool):
            values.append(is_correct)

    if not values:
        return None

    return round(100.0 * sum(values) / len(values), 4)


def build_metadata(
    base_metadata: dict[str, Any],
    results: list[Any],
    source_files: list[Path],
    results_dir: Path,
) -> dict[str, Any]:
    metadata = dict(base_metadata)

    metadata["overall_accuracy"] = calculate_accuracy(results)
    metadata["merged_from"] = [
        relative_display(path, results_dir) for path in source_files
    ]
    metadata["merged_records"] = len(results)

    # Retain use_manual if it is available only at record level.
    if "use_manual" not in metadata:
        manual_values = {
            record["use_manual"]
            for record in results
            if isinstance(record, dict)
            and isinstance(record.get("use_manual"), bool)
        }

        if len(manual_values) == 1:
            metadata["use_manual"] = manual_values.pop()

    return metadata


def build_chunk_candidate(
    target_name: str,
    numbered_files: dict[int, list[Path]],
    results_dir: Path,
    description: str,
) -> Candidate | None:
    """Build one candidate, choosing the newest file per chunk number."""

    selected: list[tuple[int, Path]] = []

    for chunk_number, paths in numbered_files.items():
        newest = max(paths, key=lambda item: item.stat().st_mtime)
        selected.append((chunk_number, newest))

        if len(paths) > 1:
            ignored = [path for path in paths if path != newest]
            print(
                f"Notice: using newest chunk {chunk_number} for "
                f"{target_name}: {relative_display(newest, results_dir)}",
                file=sys.stderr,
            )
            for path in ignored:
                print(
                    f"  Ignoring older duplicate: "
                    f"{relative_display(path, results_dir)}",
                    file=sys.stderr,
                )

    selected.sort(key=lambda item: item[0])

    if not selected:
        return None

    chunk_numbers = [number for number, _ in selected]
    if len(chunk_numbers) > 1:
        missing = sorted(
            set(range(min(chunk_numbers), max(chunk_numbers) + 1))
            - set(chunk_numbers)
        )
        if missing:
            print(
                f"Warning: {target_name} is missing chunk number(s): "
                f"{', '.join(map(str, missing))}",
                file=sys.stderr,
            )

    loaded_parts: list[LoadedResults] = []

    for _, path in selected:
        try:
            loaded_parts.append(load_results_file(path))
        except (OSError, ValueError, json.JSONDecodeError) as error:
            print(
                f"Warning: could not read {path}: {error}",
                file=sys.stderr,
            )
            return None

    merged_results: list[Any] = []
    for part in loaded_parts:
        merged_results.extend(part.results)

    # The newest chunk's metadata is generally the most recent.
    newest_part = max(loaded_parts, key=lambda part: part.modified)
    source_files = [part.path for part in loaded_parts]

    metadata = build_metadata(
        base_metadata=newest_part.metadata,
        results=merged_results,
        source_files=source_files,
        results_dir=results_dir,
    )

    return Candidate(
        target_name=target_name,
        data={
            "metadata": metadata,
            "results": merged_results,
        },
        source_files=source_files,
        modified=max(part.modified for part in loaded_parts),
        description=description,
    )


def build_full_file_candidate(
    path: Path,
    results_dir: Path,
) -> Candidate | None:
    """Treat a *_full*.json inside the checkpoint directory as a candidate."""

    try:
        loaded = load_results_file(path)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(
            f"Warning: could not read checkpoint full file {path}: {error}",
            file=sys.stderr,
        )
        return None

    metadata = dict(loaded.metadata)
    metadata["overall_accuracy"] = calculate_accuracy(loaded.results)
    metadata["merged_records"] = len(loaded.results)
    metadata["promoted_from"] = relative_display(path, results_dir)

    return Candidate(
        target_name=path.name,
        data={
            "metadata": metadata,
            "results": loaded.results,
        },
        source_files=[path],
        modified=loaded.modified,
        description="checkpoint full file",
    )


def collect_chunk_groups(
    paths: Iterable[Path],
) -> dict[tuple[Path, str], dict[int, list[Path]]]:
    """Group chunks by parent directory and canonical output filename."""

    groups: dict[tuple[Path, str], dict[int, list[Path]]] = {}

    for path in paths:
        parsed = chunk_target(path)
        if parsed is None:
            continue

        target_name, chunk_number = parsed
        group_key = (path.parent, target_name)

        groups.setdefault(group_key, {}).setdefault(
            chunk_number, []
        ).append(path)

    return groups


def matches_prefix(target_name: str, prefix: str | None) -> bool:
    return prefix is None or target_name.startswith(prefix)


def collect_candidates(
    results_dir: Path,
    checkpoint_dir: Path | None,
    prefix: str | None,
) -> dict[str, list[Candidate]]:
    candidates: dict[str, list[Candidate]] = {}

    # Top-level chunks.
    top_level_json = [
        path
        for path in results_dir.glob("*.json")
        if path.is_file()
    ]

    top_level_groups = collect_chunk_groups(top_level_json)

    for (_, target_name), numbered_files in top_level_groups.items():
        if not matches_prefix(target_name, prefix):
            continue

        candidate = build_chunk_candidate(
            target_name=target_name,
            numbered_files=numbered_files,
            results_dir=results_dir,
            description="top-level chunks",
        )
        if candidate is not None:
            candidates.setdefault(target_name, []).append(candidate)

    if checkpoint_dir is None or not checkpoint_dir.exists():
        return candidates

    checkpoint_json = [
        path
        for path in checkpoint_dir.rglob("*.json")
        if path.is_file()
    ]

    checkpoint_groups = collect_chunk_groups(checkpoint_json)

    for (_, target_name), numbered_files in checkpoint_groups.items():
        if not matches_prefix(target_name, prefix):
            continue

        candidate = build_chunk_candidate(
            target_name=target_name,
            numbered_files=numbered_files,
            results_dir=results_dir,
            description="checkpoint chunks",
        )
        if candidate is not None:
            candidates.setdefault(target_name, []).append(candidate)

    # Also consider already-merged full files stored in checkpoints.
    for path in checkpoint_json:
        if chunk_target(path) is not None:
            continue

        if "_full" not in path.stem:
            continue

        if not matches_prefix(path.name, prefix):
            continue

        candidate = build_full_file_candidate(path, results_dir)
        if candidate is not None:
            candidates.setdefault(path.name, []).append(candidate)

    return candidates


def get_existing_record_count(path: Path) -> int | None:
    if not path.exists():
        return None

    try:
        return len(load_results_file(path).results)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(
            f"Warning: existing output {path} could not be read: {error}",
            file=sys.stderr,
        )
        return None


def write_json_atomic(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

    file_descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
        text=True,
    )

    try:
        with os.fdopen(file_descriptor, "w", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=False, indent=4)
            handle.write("\n")

        os.replace(temporary_name, path)
    except Exception:
        try:
            os.unlink(temporary_name)
        except OSError:
            pass
        raise


def main() -> int:
    args = parse_arguments()
    results_dir = args.results_dir.resolve()

    if not results_dir.is_dir():
        print(
            f"Error: results directory does not exist: {results_dir}",
            file=sys.stderr,
        )
        return 1

    checkpoint_dir: Path | None

    if args.no_checkpoints:
        checkpoint_dir = None
    elif args.checkpoint_dir.is_absolute():
        checkpoint_dir = args.checkpoint_dir
    else:
        checkpoint_dir = results_dir / args.checkpoint_dir

    if checkpoint_dir is not None and not checkpoint_dir.exists():
        print(
            f"Notice: checkpoint directory does not exist: "
            f"{checkpoint_dir}",
            file=sys.stderr,
        )

    candidates_by_target = collect_candidates(
        results_dir=results_dir,
        checkpoint_dir=checkpoint_dir,
        prefix=args.prefix,
    )

    if not candidates_by_target:
        print("No matching result chunks or checkpoint files found.")
        return 0

    created = 0
    overwritten = 0
    retained = 0

    for target_name in sorted(candidates_by_target):
        target_path = results_dir / target_name
        candidates = candidates_by_target[target_name]

        # Prefer completeness. If counts tie, prefer the newest candidate.
        selected = max(
            candidates,
            key=lambda candidate: (
                candidate.record_count,
                candidate.modified,
            ),
        )

        existing_count = get_existing_record_count(target_path)
        candidate_count = selected.record_count

        if target_path.exists() and existing_count is not None:
            if candidate_count <= existing_count:
                print(
                    f"KEEP {target_name}: existing={existing_count}, "
                    f"candidate={candidate_count} "
                    f"({selected.description})"
                )
                retained += 1
                continue

            action = "OVERWRITE"
            print(
                f"{action} {target_name}: {existing_count} -> "
                f"{candidate_count} records "
                f"({selected.description})"
            )
            overwritten += 1
        else:
            action = "CREATE"
            print(
                f"{action} {target_name}: {candidate_count} records "
                f"({selected.description})"
            )
            created += 1

        if not args.dry_run:
            try:
                write_json_atomic(target_path, selected.data)
            except OSError as error:
                print(
                    f"Error writing {target_path}: {error}",
                    file=sys.stderr,
                )
                return 1

    print(
        f"Done: created={created}, overwritten={overwritten}, "
        f"retained={retained}"
        + (" (dry run)" if args.dry_run else "")
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
