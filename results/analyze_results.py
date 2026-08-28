#!/usr/bin/env python3
"""
Partial implementation of the complete PubMed/MeSH result analysis.

Place this file in ./results and eventually run it from that directory:

    python3 analyze_results.py

STATUS: SECTIONS 1 THROUGH 7 IMPLEMENTED
------------------------------------
The command-line/run-context, file-inventory, source-provenance, and record-
normalization layers are implemented. Sections 8 through 17 intentionally
remain structural outlines containing comments and ``pass`` statements.

Planned report order:
1. Inventory, integrity, provenance, and schema audit.
2. Legacy baseline -> statement -> interactive comparison.
3. Baseline without manual vs. with manual.
4. Pydantic runs vs. earlier/later counterparts.
5. Original 0.8B judge vs. rejudged 2B judge, followed by descriptive
   2B-vs-Pydantic comparisons.
6. Interactive ABA vs. BAB vs. BAB with swapped displayed labels.
7. Cross-experiment synthesis, expectations, and limitations.

The implementation reads result files only. It does not alter, rerun, or
overwrite any experiment result JSON file.
"""

from __future__ import annotations

import argparse
import ast
import re
import unicodedata
from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
from importlib import metadata as importlib_metadata
import json
from pathlib import Path
import platform
import sys
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple
import warnings


JSONDict = Dict[str, Any]
Row = Dict[str, Any]
Table = List[Dict[str, Any]]

EXPECTED_TOTAL_RECORDS = 3_000
EXPECTED_STAGE_COUNTS = {
    "Round 1: True Tag": 1_000,
    "Round 2: Unrelated Tag": 1_000,
    "Round 3: Similar Tag": 1_000,
}
VALID_BINARY_LABELS = {"Yes", "No"}
PREDICTION_PATHS = (
    "prediction",
    "model_prediction",
    "judge_ABA.prediction",
    "judge_BAB.prediction",
    "judge_BAB_swapped_labels.prediction",
)
CANONICAL_SWAPPED_BAB_FILE = "interactive_results_BAB_swapped_labels_full.json"
KNOWN_DUPLICATE_SWAPPED_BAB_FILE = "interactive_results_BAB_swapped_full.json"
DEFAULT_OUTPUT_DIRECTORY = "analysis_output"

KNOWN_SOURCE_SCRIPTS = (
    "debate_baseline_judge.py",
    "debate_interactive_judge.py",
    "debate_rejudge_large.py",
    "debate_statement_judge.py",
    "debate_utils.py",
    "judge_bab_swapped_labels.py",
    "judge_baseline.py",
    "pydantic_baseline.py",
    "pydantic_interactive.py",
    "pydantic_statement.py",
    "run_ai_debate.py",
    "run_ai_debate2.py",
    "run_interactive_debate.py",
)

# Internal sentinel used to distinguish an absent dotted path from a path whose
# stored JSON value is explicitly null.
MISSING = object()

# load_all_result_payloads keeps non-fatal load failures here so that
# build_file_inventory can still represent malformed/unreadable physical files.
# The list is reset on every call.
RESULT_LOAD_FAILURES: Table = []


# =============================================================================
# 1. Command line, paths, and run context
# =============================================================================


def _positive_integer(value: str) -> int:
    """Argparse converter accepting integers greater than zero."""
    try:
        converted = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"expected an integer, got {value!r}") from exc
    if converted <= 0:
        raise argparse.ArgumentTypeError("value must be greater than zero")
    return converted


def _resolve_from(base: Path, value: Path) -> Path:
    """Resolve a user path against *base* without requiring it to exist."""
    expanded = value.expanduser()
    if not expanded.is_absolute():
        expanded = base / expanded
    return expanded.resolve()


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    """Parse command-line options without touching the filesystem."""
    parser = argparse.ArgumentParser(
        description=(
            "Audit and compare PubMed/MeSH experiment result JSON files. "
            "The script is intended to be executed from inside ./results."
        )
    )
    parser.add_argument(
        "--results-dir",
        type=Path,
        default=Path("."),
        help="Directory containing result JSON files (default: current directory).",
    )
    parser.add_argument(
        "--source-dir",
        type=Path,
        default=None,
        help=(
            "Directory containing generation scripts. By default, this is the "
            "parent of the resolved results directory."
        ),
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path(DEFAULT_OUTPUT_DIRECTORY),
        help=f"Analysis output directory (default: ./{DEFAULT_OUTPUT_DIRECTORY}).",
    )
    parser.add_argument(
        "--bootstrap-samples",
        type=_positive_integer,
        default=10_000,
        help="Number of clustered bootstrap samples to use later (default: 10000).",
    )
    parser.add_argument(
        "--random-seed",
        type=int,
        default=42,
        help="Random seed for reproducible resampling and plots (default: 42).",
    )
    parser.add_argument(
        "--no-plots",
        action="store_true",
        help="Skip plot creation when the later reporting sections are implemented.",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Treat integrity/load warnings as fatal where supported.",
    )
    parser.add_argument(
        "--include-unverified-legacy",
        action="store_true",
        help=(
            "Include unverified legacy files in descriptive output. This will not "
            "make them eligible for controlled/primary comparisons."
        ),
    )
    return parser.parse_args(argv)


def build_run_context(args: argparse.Namespace) -> JSONDict:
    """Resolve run paths and record reproducibility settings."""
    cwd = Path.cwd().resolve()
    results_dir = _resolve_from(cwd, Path(args.results_dir))

    if args.source_dir is None:
        source_dir = results_dir.parent.resolve()
    else:
        source_dir = _resolve_from(cwd, Path(args.source_dir))

    output_dir = _resolve_from(cwd, Path(args.output_dir))

    package_versions: Dict[str, Optional[str]] = {}
    for package_name in ("numpy", "pandas", "scipy", "matplotlib"):
        try:
            package_versions[package_name] = importlib_metadata.version(package_name)
        except importlib_metadata.PackageNotFoundError:
            package_versions[package_name] = None

    context: JSONDict = {
        "started_at_utc": datetime.now(timezone.utc).isoformat(),
        "working_directory": cwd,
        "script_path": Path(__file__).resolve(),
        "results_directory": results_dir,
        "source_directory": source_dir,
        "output_directory": output_dir,
        "plots_directory": output_dir / "plots",
        "bootstrap_samples": int(args.bootstrap_samples),
        "random_seed": int(args.random_seed),
        "create_plots": not bool(args.no_plots),
        "strict": bool(args.strict),
        "include_unverified_legacy": bool(args.include_unverified_legacy),
        "python_version": platform.python_version(),
        "python_implementation": platform.python_implementation(),
        "platform": platform.platform(),
        "package_versions": package_versions,
        "executed_from_results_directory": cwd == results_dir,
        "output_is_results_directory": output_dir == results_dir,
        "output_is_inside_results_directory": results_dir in output_dir.parents,
    }
    return context


def validate_execution_location(context: Mapping[str, Any]) -> None:
    """Validate the expected results-directory layout without modifying it."""
    results_dir = Path(context["results_directory"])
    strict = bool(context.get("strict", False))

    if not results_dir.exists():
        raise FileNotFoundError(f"Results directory does not exist: {results_dir}")
    if not results_dir.is_dir():
        raise NotADirectoryError(f"Results path is not a directory: {results_dir}")

    if Path.cwd().resolve() != results_dir.resolve():
        warnings.warn(
            "analyze_results.py is intended to be executed from inside the results "
            f"directory. Current directory: {Path.cwd().resolve()}; resolved "
            f"results directory: {results_dir}",
            RuntimeWarning,
            stacklevel=2,
        )

    readme_path = results_dir / "README.md"
    if not readme_path.is_file():
        message = f"Expected results documentation is missing: {readme_path}"
        if strict:
            raise FileNotFoundError(message)
        warnings.warn(message, RuntimeWarning, stacklevel=2)

    json_files = sorted(results_dir.glob("*.json"))
    if not json_files:
        raise FileNotFoundError(
            f"No top-level result JSON files were found in {results_dir}"
        )


def prepare_output_directories(context: Mapping[str, Any]) -> JSONDict:
    """Create output directories and return all planned artifact paths."""
    results_dir = Path(context["results_directory"]).resolve()
    output_dir = Path(context["output_directory"]).resolve()

    if output_dir == results_dir:
        raise ValueError(
            "The output directory cannot be the results directory itself; doing so "
            "would mix generated analysis JSON with experiment result JSON files."
        )

    existing_result_jsons = {
        path.resolve() for path in results_dir.glob("*.json") if path.is_file()
    }
    if output_dir in existing_result_jsons:
        raise ValueError(
            f"The requested output directory is an existing result JSON file: {output_dir}"
        )
    if output_dir.exists() and not output_dir.is_dir():
        raise NotADirectoryError(
            f"The requested output directory is an existing file: {output_dir}"
        )

    output_dir.mkdir(parents=True, exist_ok=True)
    plots_dir = output_dir / "plots"
    plots_dir.mkdir(parents=True, exist_ok=True)

    return {
        "output_directory": output_dir,
        "plots_directory": plots_dir,
        "analysis_report": output_dir / "analysis_report.md",
        "analysis_data": output_dir / "analysis_data.json",
        "file_inventory": output_dir / "file_inventory.csv",
        "condition_metrics": output_dir / "condition_metrics.csv",
        "stage_metrics": output_dir / "stage_metrics.csv",
        "bias_metrics": output_dir / "bias_metrics.csv",
        "pairwise_comparisons": output_dir / "pairwise_comparisons.csv",
        "logprob_metrics": output_dir / "logprob_metrics.csv",
        "prediction_patterns": output_dir / "prediction_patterns.csv",
        "integrity_findings": output_dir / "integrity_findings.csv",
        "provenance": output_dir / "provenance.csv",
    }


# =============================================================================
# 2. File discovery, loading, hashing, and schema inventory
# =============================================================================


def discover_result_json_files(context: Mapping[str, Any]) -> List[Path]:
    """Return deterministic top-level result JSON paths."""
    results_dir = Path(context["results_directory"]).resolve()
    output_dir = Path(context["output_directory"]).resolve()

    discovered: List[Path] = []
    for candidate in results_dir.glob("*.json"):
        resolved = candidate.resolve()
        if not candidate.is_file():
            continue
        # This normally cannot match because output_dir is required to be a
        # directory distinct from results_dir, but retain the guard for custom
        # layouts and symlinks.
        if resolved == output_dir or output_dir in resolved.parents:
            continue
        discovered.append(resolved)

    return sorted(discovered, key=lambda path: (path.name.casefold(), path.name))


def load_json_file(path: Path) -> JSONDict:
    """Load one UTF-8 JSON object and add filename context to failures."""
    try:
        with path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"Malformed JSON in {path} at line {exc.lineno}, column {exc.colno}: "
            f"{exc.msg}"
        ) from exc
    except OSError as exc:
        raise OSError(f"Could not read JSON file {path}: {exc}") from exc

    if not isinstance(payload, dict):
        raise TypeError(
            f"Expected the top level of {path} to be a JSON object, "
            f"found {type(payload).__name__}"
        )
    return payload


def load_all_result_payloads(
    paths: Sequence[Path],
    strict: bool = False,
) -> Dict[Path, JSONDict]:
    """Load every result once, retaining non-fatal failures for the inventory."""
    RESULT_LOAD_FAILURES.clear()
    payloads: Dict[Path, JSONDict] = {}

    for original_path in paths:
        path = original_path.resolve()
        try:
            payloads[path] = load_json_file(path)
        except (OSError, TypeError, ValueError) as exc:
            RESULT_LOAD_FAILURES.append(
                {
                    "path": path,
                    "filename": path.name,
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                }
            )

    if RESULT_LOAD_FAILURES:
        joined = "\n".join(
            f"- {failure['filename']}: {failure['error']}"
            for failure in RESULT_LOAD_FAILURES
        )
        message = (
            f"Failed to load {len(RESULT_LOAD_FAILURES)} of {len(paths)} JSON files:\n"
            f"{joined}"
        )
        if strict:
            raise RuntimeError(message)
        warnings.warn(message, RuntimeWarning, stacklevel=2)

    if not payloads:
        raise RuntimeError("No valid result JSON payloads could be loaded.")

    return payloads


def compute_sha256(path: Path) -> str:
    """Compute a byte-level SHA-256 digest without loading the file at once."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def normalized_results_digest(payload: Mapping[str, Any]) -> str:
    """Hash a canonical serialization of only the top-level results array."""
    if "results" not in payload:
        raise KeyError("Top-level key 'results' is missing")
    results = payload["results"]
    if not isinstance(results, list):
        raise TypeError(
            f"Top-level 'results' must be a list, found {type(results).__name__}"
        )
    canonical = json.dumps(
        results,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def get_nested_value(data: Mapping[str, Any], dotted_path: str) -> Any:
    """Traverse mapping components separated by dots."""
    current: Any = data
    for component in dotted_path.split("."):
        if not isinstance(current, Mapping) or component not in current:
            return MISSING
        current = current[component]
    return current


def _walk_mapping_paths(
    value: Mapping[str, Any],
    prefix: str = "",
) -> Iterable[Tuple[str, Any]]:
    """Yield all mapping paths recursively; JSON lists remain leaf values."""
    for raw_key, child in value.items():
        key = str(raw_key)
        path = f"{prefix}.{key}" if prefix else key
        yield path, child
        if isinstance(child, Mapping):
            yield from _walk_mapping_paths(child, path)


def detect_prediction_paths(records: Sequence[Mapping[str, Any]]) -> List[str]:
    """Find populated standard and unexpected prediction fields."""
    discovered = set()

    for record in records:
        for standard_path in PREDICTION_PATHS:
            value = get_nested_value(record, standard_path)
            if value is not MISSING and value is not None:
                discovered.add(standard_path)

        for path, value in _walk_mapping_paths(record):
            terminal = path.rsplit(".", 1)[-1].casefold()
            if (
                terminal in {"prediction", "model_prediction"}
                or terminal.endswith("_prediction")
            ) and value is not None:
                discovered.add(path)

    standard_order = [path for path in PREDICTION_PATHS if path in discovered]
    unexpected = sorted(
        discovered.difference(PREDICTION_PATHS), key=lambda item: item.casefold()
    )
    return standard_order + unexpected


def _json_type_name(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, str):
        return "string"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, list):
        return "array"
    if isinstance(value, Mapping):
        return "object"
    return type(value).__name__


def inspect_record_schema(records: Sequence[Mapping[str, Any]]) -> JSONDict:
    """Inventory top-level and nested record shapes and experiment indicators."""
    top_level_counts: Counter[str] = Counter()
    nested_path_counts: Counter[str] = Counter()
    path_types: Dict[str, Counter[str]] = defaultdict(Counter)
    shape_counts: Counter[Tuple[str, ...]] = Counter()

    for record in records:
        shape = tuple(sorted(str(key) for key in record.keys()))
        shape_counts[shape] += 1
        for raw_key, value in record.items():
            key = str(raw_key)
            top_level_counts[key] += 1
            path_types[key][_json_type_name(value)] += 1
        for path, value in _walk_mapping_paths(record):
            nested_path_counts[path] += 1
            path_types[path][_json_type_name(value)] += 1

    all_paths = set(nested_path_counts)
    terminal_fields = {path.rsplit(".", 1)[-1] for path in all_paths}
    prediction_paths = detect_prediction_paths(records)

    interactive_turn_fields = {
        "a_turn1",
        "b_turn1",
        "a_turn2",
        "b_opening",
        "a_rebuttal",
        "b_closing",
    }
    statement_fields = {
        "pro_argument",
        "con_argument",
        "arg_a",
        "arg_b",
        "pro_first",
        "pro_is_a",
    }
    side_mapping_fields = {
        "pro_first",
        "pro_is_a",
        "a_is_pro",
        "pro_is_debater_a",
        "a_side",
        "b_side",
        "presented_a_side",
        "presented_b_side",
    }
    raw_output_fields = {
        "judge_output",
        "full_model_output",
        "model_output",
        "raw_output",
    }
    argument_fields = statement_fields | interactive_turn_fields | {
        "debate_ABA",
        "debate_BAB",
        "debate_BAB_swapped_labels",
    }

    robust_interactive = any(
        path.startswith("judge_ABA.")
        or path.startswith("judge_BAB.")
        or path.startswith("judge_BAB_swapped_labels.")
        for path in all_paths
    )
    legacy_interactive = (
        {"a_turn1", "b_turn1", "a_turn2"}.issubset(terminal_fields)
        and not robust_interactive
    )
    statement_like = bool(statement_fields.intersection(terminal_fields)) and not (
        robust_interactive or legacy_interactive
    )

    shape_variants = [
        {"fields": list(fields), "record_count": count}
        for fields, count in sorted(
            shape_counts.items(), key=lambda item: (-item[1], item[0])
        )
    ]

    return {
        "record_count_inspected": len(records),
        "top_level_fields": sorted(top_level_counts),
        "top_level_field_presence": dict(sorted(top_level_counts.items())),
        "nested_paths": sorted(all_paths),
        "nested_path_presence": dict(sorted(nested_path_counts.items())),
        "path_types": {
            path: dict(sorted(type_counts.items()))
            for path, type_counts in sorted(path_types.items())
        },
        "record_shape_count": len(shape_counts),
        "record_shape_variants": shape_variants,
        "schema_varies_within_file": len(shape_counts) > 1,
        "prediction_paths": prediction_paths,
        "indicators": {
            "robust_interactive": robust_interactive,
            "legacy_interactive": legacy_interactive,
            "statement_like": statement_like,
            "baseline_like": bool(prediction_paths)
            and not robust_interactive
            and not legacy_interactive
            and not statement_like,
            "swapped_labels": any(
                path.startswith("judge_BAB_swapped_labels.")
                or "swapped" in path.casefold()
                for path in all_paths
            ),
            "has_confidence": "confidence" in terminal_fields
            or any(path.endswith(".confidence") for path in all_paths),
            "has_fallback": "needed_fallback" in terminal_fields,
            "has_arguments": bool(argument_fields.intersection(terminal_fields)),
            "has_interactive_turns": bool(
                interactive_turn_fields.intersection(terminal_fields)
            ),
            "has_side_mapping": bool(side_mapping_fields.intersection(terminal_fields)),
            "has_abstract": "abstract" in terminal_fields,
            "has_assigned_tags": "assigned_tags" in terminal_fields,
            "has_raw_output": bool(raw_output_fields.intersection(terminal_fields)),
            "has_top_level_prediction": "prediction" in top_level_counts,
            "has_model_prediction": "model_prediction" in top_level_counts,
            "has_full_model_output": "full_model_output" in terminal_fields,
        },
    }


def infer_file_family(
    path: Path,
    payload: Mapping[str, Any],
    schema: Mapping[str, Any],
) -> str:
    """Infer baseline/statement/interactive, preferring schema over filename."""
    indicators = schema.get("indicators", {})

    if indicators.get("robust_interactive") or indicators.get("legacy_interactive"):
        return "interactive"
    if indicators.get("statement_like"):
        return "statement"
    if indicators.get("baseline_like"):
        return "baseline"

    # Filename fallback is supporting evidence only for files whose records do not
    # expose enough schema information, such as empty or failed files.
    filename = path.name.casefold()
    if "interactive" in filename:
        return "interactive"
    if "statement" in filename:
        return "statement"
    if "baseline" in filename:
        return "baseline"
    return "unknown"


def _metadata_as_searchable_text(payload: Mapping[str, Any]) -> str:
    metadata = payload.get("metadata", {})
    try:
        return json.dumps(metadata, ensure_ascii=False, sort_keys=True).casefold()
    except (TypeError, ValueError):
        return str(metadata).casefold()


def infer_file_generation(
    path: Path,
    payload: Mapping[str, Any],
    schema: Mapping[str, Any],
) -> str:
    """Classify the broad implementation generation."""
    filename = path.name.casefold()
    metadata_text = _metadata_as_searchable_text(payload)
    indicators = schema.get("indicators", {})

    if indicators.get("swapped_labels") or "swapped" in filename:
        return "swapped_labels"
    if "rejudge2b" in filename or "rejudge" in metadata_text and "2b" in metadata_text:
        return "rejudge_2B"
    if filename.startswith("pydantic_"):
        return "older_pydantic"
    if indicators.get("has_confidence") or indicators.get("has_fallback"):
        return "robust_0.8B"
    if indicators.get("has_top_level_prediction") and not indicators.get(
        "has_model_prediction"
    ):
        return "robust_0.8B"
    if filename.endswith("_merged.json") or indicators.get("has_model_prediction"):
        return "legacy"
    return "unresolved"


def _find_first_mapping_key(
    value: Any,
    candidate_keys: Sequence[str],
    prefix: str = "metadata",
) -> Tuple[Any, Optional[str]]:
    """Find the first case-insensitive key in nested metadata."""
    candidates = {key.casefold() for key in candidate_keys}
    if isinstance(value, Mapping):
        for raw_key, child in value.items():
            key = str(raw_key)
            child_path = f"{prefix}.{key}" if prefix else key
            if key.casefold() in candidates:
                return child, child_path
        for raw_key, child in value.items():
            key = str(raw_key)
            child_path = f"{prefix}.{key}" if prefix else key
            found, found_path = _find_first_mapping_key(
                child, candidate_keys, child_path
            )
            if found_path is not None:
                return found, found_path
    elif isinstance(value, list):
        for index, child in enumerate(value):
            found, found_path = _find_first_mapping_key(
                child, candidate_keys, f"{prefix}[{index}]"
            )
            if found_path is not None:
                return found, found_path
    return MISSING, None


def _known_script_for(family: str, generation: str) -> Optional[str]:
    if generation == "swapped_labels":
        return "judge_bab_swapped_labels.py"
    if generation == "rejudge_2B":
        return "debate_rejudge_large.py"
    if generation == "older_pydantic":
        return {
            "baseline": "pydantic_baseline.py",
            "statement": "pydantic_statement.py",
            "interactive": "pydantic_interactive.py",
        }.get(family)
    if generation == "robust_0.8B":
        return {
            "baseline": "debate_baseline_judge.py",
            "statement": "debate_statement_judge.py",
            "interactive": "debate_interactive_judge.py",
        }.get(family)
    if generation == "legacy":
        return {
            "baseline": "judge_baseline.py",
            "statement": "run_ai_debate2.py",
            "interactive": "run_interactive_debate.py",
        }.get(family)
    return None


def infer_file_provenance(
    path: Path,
    payload: Mapping[str, Any],
    schema: Mapping[str, Any],
) -> JSONDict:
    """Infer provenance while labelling metadata evidence separately."""
    family = infer_file_family(path, payload, schema)
    generation = infer_file_generation(path, payload, schema)
    indicators = schema.get("indicators", {})
    filename = path.name.casefold()
    metadata = payload.get("metadata", {})

    script = _known_script_for(family, generation)
    statuses: Dict[str, str] = {}
    evidence: List[str] = []

    if script is None:
        statuses["generating_script"] = "unknown"
    else:
        statuses["generating_script"] = "inferred_from_filename_and_schema"
        evidence.append(f"Likely script inferred as {script} from file generation/family.")

    judge_model, judge_model_path = _find_first_mapping_key(
        metadata,
        ("judge_model", "judge_model_id", "judge_model_name"),
    )
    if judge_model_path is not None and isinstance(judge_model, (str, int, float)):
        judge_model = str(judge_model)
        statuses["judge_model"] = "verified_from_embedded_metadata"
        evidence.append(f"Judge model read from {judge_model_path}.")
    else:
        judge_model = "Qwen3.5-2B" if generation == "rejudge_2B" else "Qwen3.5-0.8B"
        statuses["judge_model"] = "inferred_from_known_file_generation"

    debater_model, debater_model_path = _find_first_mapping_key(
        metadata,
        ("debater_model", "debater_model_id", "debater_model_name"),
    )
    if family == "baseline":
        debater_model = None
        statuses["debater_model"] = "not_applicable"
    elif debater_model_path is not None and isinstance(
        debater_model, (str, int, float)
    ):
        debater_model = str(debater_model)
        statuses["debater_model"] = "verified_from_embedded_metadata"
        evidence.append(f"Debater model read from {debater_model_path}.")
    elif generation in {
        "legacy",
        "older_pydantic",
        "robust_0.8B",
        "rejudge_2B",
        "swapped_labels",
    }:
        debater_model = "Qwen3.5-2B"
        statuses["debater_model"] = "inferred_from_known_file_generation"
    else:
        debater_model = None
        statuses["debater_model"] = "unknown"

    manual_in_judge_prompt: Any = None
    assigned_tags_in_judge_prompt: Any = None
    assigned_tags_in_debater_prompt: Any = None

    if family == "baseline":
        assigned_tags_in_judge_prompt = True
        if "nomanual" in filename:
            manual_in_judge_prompt = False
        elif "withmanual" in filename:
            manual_in_judge_prompt = True
        elif generation in {"older_pydantic", "legacy"}:
            manual_in_judge_prompt = True
    elif family == "statement":
        if generation in {"robust_0.8B", "rejudge_2B"}:
            manual_in_judge_prompt = False
            assigned_tags_in_judge_prompt = False
            assigned_tags_in_debater_prompt = False
        elif generation == "older_pydantic":
            manual_in_judge_prompt = False
            assigned_tags_in_judge_prompt = False
            assigned_tags_in_debater_prompt = True
        elif generation == "legacy":
            manual_in_judge_prompt = True
            assigned_tags_in_judge_prompt = True
            assigned_tags_in_debater_prompt = True
    elif family == "interactive":
        if generation in {"robust_0.8B", "rejudge_2B", "swapped_labels"}:
            manual_in_judge_prompt = False
            assigned_tags_in_judge_prompt = False
            assigned_tags_in_debater_prompt = False
        elif generation == "legacy":
            manual_in_judge_prompt = True
            assigned_tags_in_judge_prompt = True
            assigned_tags_in_debater_prompt = True
        # The older Pydantic interactive prompt inputs remain unknown until the
        # source script is inspected in section 3.

    for attribute, value in (
        ("manual_in_judge_prompt", manual_in_judge_prompt),
        ("assigned_tags_in_judge_prompt", assigned_tags_in_judge_prompt),
        ("assigned_tags_in_debater_prompt", assigned_tags_in_debater_prompt),
    ):
        statuses[attribute] = (
            "unknown"
            if value is None
            else "inferred_from_known_script_mapping_pending_source_verification"
        )

    if generation in {"robust_0.8B", "rejudge_2B", "swapped_labels"}:
        parser_type = "structured Yes/No output with log-probability fallback"
        fallback_behavior = "log-probability fallback available"
    elif generation == "older_pydantic":
        parser_type = "Pydantic JSON parsing with retries"
        fallback_behavior = "no guaranteed log-probability fallback"
    elif generation == "legacy":
        parser_type = "free-text answer parsing with retries"
        fallback_behavior = "no log-probability fallback"
    else:
        parser_type = None
        fallback_behavior = None
    statuses["parser_type"] = (
        "unknown" if parser_type is None else "inferred_from_schema_and_generation"
    )
    statuses["fallback_behavior"] = (
        "unknown"
        if fallback_behavior is None
        else "inferred_from_schema_and_generation"
    )

    if family == "interactive":
        if generation == "swapped_labels":
            debate_orders = ["BAB_swapped_labels"]
        elif indicators.get("robust_interactive"):
            debate_orders = [
                order
                for order, prefix in (
                    ("ABA", "judge_ABA."),
                    ("BAB", "judge_BAB."),
                    ("BAB_swapped_labels", "judge_BAB_swapped_labels."),
                )
                if any(
                    path.startswith(prefix)
                    for path in schema.get("prediction_paths", [])
                )
            ]
        else:
            debate_orders = ["ABA"]
    elif family == "statement":
        debate_orders = ["independent_statements"]
    else:
        debate_orders = []

    confidence_available = bool(indicators.get("has_confidence"))
    fallback_field_available = bool(indicators.get("has_fallback"))
    statuses["confidence_available"] = "observed_in_record_schema"
    statuses["fallback_field_available"] = "observed_in_record_schema"

    return {
        "family": family,
        "generation": generation,
        "generating_script": script,
        "judge_model": judge_model,
        "debater_model": debater_model,
        "manual_in_judge_prompt": manual_in_judge_prompt,
        "assigned_tags_in_judge_prompt": assigned_tags_in_judge_prompt,
        "assigned_tags_in_debater_prompt": assigned_tags_in_debater_prompt,
        "parser_type": parser_type,
        "fallback_behavior": fallback_behavior,
        "confidence_available": confidence_available,
        "fallback_field_available": fallback_field_available,
        "debate_orders": debate_orders,
        "attribute_status": statuses,
        "evidence": evidence,
        "verification_note": (
            "Prompt-input and model claims inferred from names/schema remain "
            "provisional until section 3 reconciles them with source scripts or "
            "explicit embedded metadata."
        ),
    }


def _audit_stage(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    casefold_map = {stage.casefold(): stage for stage in EXPECTED_STAGE_COUNTS}
    return casefold_map.get(text.casefold(), text)


def _audit_pmid(value: Any) -> Optional[str]:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, float):
        if not value.is_integer():
            return str(value)
        return str(int(value))
    text = str(value).strip()
    return text or None


def _audit_label(value: Any) -> str:
    if value is MISSING or value is None:
        return "missing"
    if not isinstance(value, str):
        return "invalid"
    normalized = value.strip().casefold()
    if normalized == "yes":
        return "Yes"
    if normalized == "no":
        return "No"
    if normalized in {"unknown", "unresolved"}:
        return "Unknown"
    if not normalized:
        return "missing"
    return "invalid"


def _truth_for_audit(record: Mapping[str, Any]) -> str:
    stored = _audit_label(record.get("ground_truth", MISSING))
    if stored in VALID_BINARY_LABELS:
        return stored
    stage = _audit_stage(record.get("stage"))
    if stage == "Round 1: True Tag":
        return "Yes"
    if stage in {"Round 2: Unrelated Tag", "Round 3: Similar Tag"}:
        return "No"
    return "invalid"


def _parent_mapping_for_path(
    record: Mapping[str, Any], dotted_path: str
) -> Optional[Mapping[str, Any]]:
    if "." not in dotted_path:
        return record
    parent_path = dotted_path.rsplit(".", 1)[0]
    value = get_nested_value(record, parent_path)
    return value if isinstance(value, Mapping) else None


def audit_one_file(path: Path, payload: Mapping[str, Any]) -> JSONDict:
    """Audit one physical result file without trusting cached metadata metrics."""
    raw_results = payload.get("results", MISSING)
    results_array_valid = isinstance(raw_results, list)
    raw_records = raw_results if results_array_valid else []
    valid_records = [record for record in raw_records if isinstance(record, Mapping)]
    invalid_record_entries = len(raw_records) - len(valid_records)

    schema = inspect_record_schema(valid_records)
    family = infer_file_family(path, payload, schema)
    generation = infer_file_generation(path, payload, schema)
    provenance = infer_file_provenance(path, payload, schema)

    stage_counts: Counter[str] = Counter()
    valid_keys: List[Tuple[str, str]] = []
    missing_key_fields: Counter[str] = Counter()
    ground_truth_stage_conflicts = 0

    for record in valid_records:
        stage = _audit_stage(record.get("stage"))
        pmid = _audit_pmid(record.get("pmid"))
        candidate = record.get("candidate_tag", MISSING)
        stored_truth = _audit_label(record.get("ground_truth", MISSING))

        if stage is None:
            missing_key_fields["stage"] += 1
            stage_counts["<missing>"] += 1
        else:
            stage_counts[stage] += 1
        if pmid is None:
            missing_key_fields["pmid"] += 1
        if candidate is MISSING or candidate is None or not str(candidate).strip():
            missing_key_fields["candidate_tag"] += 1
        if stored_truth not in VALID_BINARY_LABELS:
            missing_key_fields["ground_truth_or_invalid"] += 1

        if stage is not None and pmid is not None:
            valid_keys.append((stage, pmid))

        expected_truth = (
            "Yes"
            if stage == "Round 1: True Tag"
            else "No"
            if stage in {
                "Round 2: Unrelated Tag",
                "Round 3: Similar Tag",
            }
            else None
        )
        if (
            expected_truth is not None
            and stored_truth in VALID_BINARY_LABELS
            and stored_truth != expected_truth
        ):
            ground_truth_stage_conflicts += 1

    key_counter = Counter(valid_keys)
    duplicate_key_count = sum(count - 1 for count in key_counter.values() if count > 1)
    duplicate_key_groups = sum(1 for count in key_counter.values() if count > 1)
    duplicate_key_examples = [
        {"stage": stage, "pmid": pmid, "count": count}
        for (stage, pmid), count in sorted(key_counter.items())
        if count > 1
    ][:20]

    invalid_stage_count = sum(
        count
        for stage, count in stage_counts.items()
        if stage not in EXPECTED_STAGE_COUNTS
    )
    ordered_stage_counts = {
        stage: stage_counts.get(stage, 0) for stage in EXPECTED_STAGE_COUNTS
    }
    for stage in sorted(set(stage_counts).difference(EXPECTED_STAGE_COUNTS)):
        ordered_stage_counts[stage] = stage_counts[stage]

    prediction_counts: Dict[str, JSONDict] = {}
    cached_correctness_mismatches: Dict[str, int] = {}
    cached_correctness_present: Dict[str, int] = {}

    for prediction_path in schema.get("prediction_paths", []):
        counts: Counter[str] = Counter()
        mismatch_count = 0
        cached_count = 0

        for record in valid_records:
            category = _audit_label(get_nested_value(record, prediction_path))
            counts[category] += 1

            parent = _parent_mapping_for_path(record, prediction_path)
            cached = parent.get("is_correct", MISSING) if parent is not None else MISSING
            if isinstance(cached, bool):
                cached_count += 1
                truth = _truth_for_audit(record)
                recomputed = (
                    category in VALID_BINARY_LABELS
                    and truth in VALID_BINARY_LABELS
                    and category == truth
                )
                if cached != recomputed:
                    mismatch_count += 1

        valid_prediction_count = counts["Yes"] + counts["No"]
        unresolved_count = counts["Unknown"] + counts["missing"] + counts["invalid"]
        prediction_counts[prediction_path] = {
            "Yes": counts["Yes"],
            "No": counts["No"],
            "Unknown": counts["Unknown"],
            "missing": counts["missing"],
            "invalid": counts["invalid"],
            "valid_binary": valid_prediction_count,
            "unresolved": unresolved_count,
            "valid_binary_rate": (
                valid_prediction_count / len(valid_records) if valid_records else None
            ),
        }
        cached_correctness_mismatches[prediction_path] = mismatch_count
        cached_correctness_present[prediction_path] = cached_count

    file_errors: List[str] = []
    try:
        byte_hash = compute_sha256(path)
    except OSError as exc:
        byte_hash = None
        file_errors.append(f"SHA-256 failed: {exc}")

    try:
        normalized_digest = normalized_results_digest(payload)
    except (KeyError, TypeError, ValueError) as exc:
        normalized_digest = None
        file_errors.append(f"Normalized results digest failed: {exc}")

    try:
        stat = path.stat()
        file_size_bytes: Optional[int] = stat.st_size
        modified_at_utc: Optional[str] = datetime.fromtimestamp(
            stat.st_mtime, tz=timezone.utc
        ).isoformat()
    except OSError as exc:
        file_size_bytes = None
        modified_at_utc = None
        file_errors.append(f"File stat failed: {exc}")

    unique_record_count = len(key_counter)
    record_complete = unique_record_count == EXPECTED_TOTAL_RECORDS
    expected_stage_distribution = all(
        stage_counts.get(stage, 0) == expected
        for stage, expected in EXPECTED_STAGE_COUNTS.items()
    )
    unknown_prediction_count = sum(
        counts["Unknown"] for counts in prediction_counts.values()
    )
    missing_prediction_count = sum(
        counts["missing"] for counts in prediction_counts.values()
    )
    invalid_prediction_count = sum(
        counts["invalid"] for counts in prediction_counts.values()
    )

    audit_issues = list(file_errors)
    if not results_array_valid:
        audit_issues.append("Top-level 'results' is missing or is not an array.")
    if invalid_record_entries:
        audit_issues.append(
            f"{invalid_record_entries} results-array entries are not JSON objects."
        )
    if not record_complete:
        audit_issues.append(
            f"Expected {EXPECTED_TOTAL_RECORDS} unique (stage, pmid) keys, "
            f"found {unique_record_count}."
        )
    if duplicate_key_count:
        audit_issues.append(
            f"Found {duplicate_key_count} duplicate records across "
            f"{duplicate_key_groups} (stage, pmid) keys."
        )
    if invalid_stage_count:
        audit_issues.append(f"Found {invalid_stage_count} records with invalid stages.")
    if ground_truth_stage_conflicts:
        audit_issues.append(
            f"Found {ground_truth_stage_conflicts} stored ground truths conflicting "
            "with stage-derived expectations."
        )
    if not prediction_counts:
        audit_issues.append("No populated prediction path was detected.")

    return {
        "path": path.resolve(),
        "filename": path.name,
        "load_status": "loaded",
        "file_size_bytes": file_size_bytes,
        "modified_at_utc": modified_at_utc,
        "sha256": byte_hash,
        "normalized_results_sha256": normalized_digest,
        "top_level_results_is_array": results_array_valid,
        "total_results_entries": len(raw_records),
        "valid_record_objects": len(valid_records),
        "invalid_record_entries": invalid_record_entries,
        "unique_stage_pmid_records": unique_record_count,
        "duplicate_record_count": duplicate_key_count,
        "duplicate_key_groups": duplicate_key_groups,
        "duplicate_key_examples": duplicate_key_examples,
        "record_complete": record_complete,
        "clean_3000_record_set": (
            record_complete
            and len(raw_records) == EXPECTED_TOTAL_RECORDS
            and duplicate_key_count == 0
            and invalid_record_entries == 0
        ),
        "expected_stage_distribution": expected_stage_distribution,
        "stage_counts": ordered_stage_counts,
        "invalid_stage_count": invalid_stage_count,
        "missing_key_field_counts": dict(sorted(missing_key_fields.items())),
        "ground_truth_stage_conflicts": ground_truth_stage_conflicts,
        "prediction_paths": schema.get("prediction_paths", []),
        "prediction_counts": prediction_counts,
        "unknown_prediction_count": unknown_prediction_count,
        "missing_prediction_count": missing_prediction_count,
        "invalid_prediction_count": invalid_prediction_count,
        "cached_is_correct_present": cached_correctness_present,
        "cached_is_correct_mismatches": cached_correctness_mismatches,
        "family": family,
        "generation": generation,
        "schema": schema,
        "provenance": provenance,
        "audit_issue_count": len(audit_issues),
        "audit_issues": audit_issues,
    }


def _failed_load_inventory_row(failure: Mapping[str, Any]) -> JSONDict:
    path = Path(failure["path"]).resolve()
    try:
        size = path.stat().st_size
    except OSError:
        size = None
    try:
        byte_hash = compute_sha256(path)
    except OSError:
        byte_hash = None

    empty_schema = inspect_record_schema([])
    family = infer_file_family(path, {}, empty_schema)
    generation = infer_file_generation(path, {}, empty_schema)
    provenance = infer_file_provenance(path, {}, empty_schema)
    return {
        "path": path,
        "filename": path.name,
        "load_status": "failed",
        "load_error_type": failure.get("error_type"),
        "load_error": failure.get("error"),
        "file_size_bytes": size,
        "modified_at_utc": None,
        "sha256": byte_hash,
        "normalized_results_sha256": None,
        "top_level_results_is_array": False,
        "total_results_entries": None,
        "valid_record_objects": 0,
        "invalid_record_entries": None,
        "unique_stage_pmid_records": 0,
        "duplicate_record_count": None,
        "duplicate_key_groups": None,
        "duplicate_key_examples": [],
        "record_complete": False,
        "clean_3000_record_set": False,
        "expected_stage_distribution": False,
        "stage_counts": {},
        "invalid_stage_count": None,
        "missing_key_field_counts": {},
        "ground_truth_stage_conflicts": None,
        "prediction_paths": [],
        "prediction_counts": {},
        "unknown_prediction_count": None,
        "missing_prediction_count": None,
        "invalid_prediction_count": None,
        "cached_is_correct_present": {},
        "cached_is_correct_mismatches": {},
        "family": family,
        "generation": generation,
        "schema": empty_schema,
        "provenance": provenance,
        "audit_issue_count": 1,
        "audit_issues": [str(failure.get("error"))],
    }


def build_file_inventory(payloads: Mapping[Path, Mapping[str, Any]]) -> Table:
    """Build one inventory row per physical discovered JSON file."""
    inventory = [
        audit_one_file(path, payload)
        for path, payload in sorted(
            payloads.items(), key=lambda item: (item[0].name.casefold(), item[0].name)
        )
    ]
    inventory.extend(_failed_load_inventory_row(item) for item in RESULT_LOAD_FAILURES)
    return sorted(
        inventory,
        key=lambda row: (str(row["filename"]).casefold(), str(row["filename"])),
    )


def detect_normalized_duplicate_files(
    inventory: Sequence[Mapping[str, Any]],
) -> Table:
    """Group files with byte-equivalent canonical results arrays."""
    digest_groups: Dict[str, List[Mapping[str, Any]]] = defaultdict(list)
    by_filename = {str(row.get("filename")): row for row in inventory}

    for row in inventory:
        digest = row.get("normalized_results_sha256")
        if row.get("load_status") == "loaded" and isinstance(digest, str) and digest:
            digest_groups[digest].append(row)

    groups: Table = []
    for digest, members in sorted(digest_groups.items()):
        if len(members) < 2:
            continue
        sorted_members = sorted(
            members,
            key=lambda row: (
                str(row.get("filename", "")).casefold(),
                str(row.get("filename", "")),
            ),
        )
        filenames = [str(member["filename"]) for member in sorted_members]
        known_pair = {
            CANONICAL_SWAPPED_BAB_FILE,
            KNOWN_DUPLICATE_SWAPPED_BAB_FILE,
        }.issubset(filenames)
        if CANONICAL_SWAPPED_BAB_FILE in filenames:
            canonical = next(
                member
                for member in sorted_members
                if member["filename"] == CANONICAL_SWAPPED_BAB_FILE
            )
        else:
            canonical = sorted_members[0]

        groups.append(
            {
                "normalized_results_sha256": digest,
                "is_duplicate_group": True,
                "status": "expected_known_duplicate" if known_pair else "duplicate",
                "expected_known_swapped_pair": known_pair,
                "file_count": len(sorted_members),
                "filenames": filenames,
                "paths": [member["path"] for member in sorted_members],
                "canonical_filename": canonical["filename"],
                "canonical_path": canonical["path"],
                "excluded_duplicate_filenames": [
                    name for name in filenames if name != canonical["filename"]
                ],
            }
        )

    known_left = by_filename.get(CANONICAL_SWAPPED_BAB_FILE)
    known_right = by_filename.get(KNOWN_DUPLICATE_SWAPPED_BAB_FILE)
    if known_left is not None and known_right is not None:
        left_digest = known_left.get("normalized_results_sha256")
        right_digest = known_right.get("normalized_results_sha256")
        if not left_digest or left_digest != right_digest:
            groups.append(
                {
                    "normalized_results_sha256": None,
                    "is_duplicate_group": False,
                    "status": "known_swapped_pair_mismatch",
                    "expected_known_swapped_pair": True,
                    "file_count": 2,
                    "filenames": [
                        CANONICAL_SWAPPED_BAB_FILE,
                        KNOWN_DUPLICATE_SWAPPED_BAB_FILE,
                    ],
                    "paths": [known_left["path"], known_right["path"]],
                    "canonical_filename": None,
                    "canonical_path": None,
                    "excluded_duplicate_filenames": [],
                    "left_digest": left_digest,
                    "right_digest": right_digest,
                }
            )

    return sorted(
        groups,
        key=lambda group: (
            0 if group.get("status") == "known_swapped_pair_mismatch" else 1,
            str(group.get("canonical_filename") or "").casefold(),
            str(group.get("normalized_results_sha256") or ""),
        ),
    )


def choose_canonical_analysis_files(
    inventory: Sequence[Mapping[str, Any]],
    duplicate_groups: Sequence[Mapping[str, Any]],
) -> List[Path]:
    """Keep one physical representative of every normalized result array."""
    excluded_paths = set()
    for group in duplicate_groups:
        if not group.get("is_duplicate_group"):
            continue
        canonical_path = Path(group["canonical_path"]).resolve()
        for raw_path in group.get("paths", []):
            path = Path(raw_path).resolve()
            if path != canonical_path:
                excluded_paths.add(path)

    selected = []
    for row in inventory:
        if row.get("load_status") != "loaded":
            continue
        path = Path(row["path"]).resolve()
        if path not in excluded_paths:
            selected.append(path)

    return sorted(selected, key=lambda path: (path.name.casefold(), path.name))


def _expectation_finding(
    severity: str,
    check: str,
    filename: Optional[str],
    expected: Any,
    observed: Any,
    passed: bool,
    message: str,
) -> JSONDict:
    return {
        "severity": "info" if passed else severity,
        "check": check,
        "filename": filename,
        "expected": expected,
        "observed": observed,
        "passed": passed,
        "message": message,
    }


def validate_known_audit_expectations(
    inventory: Sequence[Mapping[str, Any]],
) -> Table:
    """Compare the current inventory with the documented audit expectations."""
    findings: Table = []
    by_filename = {str(row.get("filename")): row for row in inventory}

    # Every currently present *_full.json is checked. Unknown predictions do not
    # invalidate record completeness; only the unique-key count controls this check.
    for row in inventory:
        filename = str(row.get("filename", ""))
        if not filename.endswith("_full.json"):
            continue
        observed = row.get("unique_stage_pmid_records")
        passed = row.get("load_status") == "loaded" and observed == EXPECTED_TOTAL_RECORDS
        findings.append(
            _expectation_finding(
                "error",
                "full_file_unique_record_count",
                filename,
                EXPECTED_TOTAL_RECORDS,
                observed,
                passed,
                (
                    f"{filename} has the expected 3,000 unique (stage, pmid) records."
                    if passed
                    else f"{filename} does not have the expected 3,000 unique records."
                ),
            )
        )

    pydantic_statement_name = "pydantic_statement_results_full.json"
    pydantic_statement = by_filename.get(pydantic_statement_name)
    if pydantic_statement is not None:
        path_counts = pydantic_statement.get("prediction_counts", {})
        model_counts = path_counts.get("model_prediction", {})
        observed_unknowns = model_counts.get(
            "Unknown", pydantic_statement.get("unknown_prediction_count")
        )
        passed = observed_unknowns == 129
        findings.append(
            _expectation_finding(
                "warning",
                "pydantic_statement_unknown_count",
                pydantic_statement_name,
                129,
                observed_unknowns,
                passed,
                (
                    "The documented 129 Unknown predictions are present."
                    if passed
                    else "The Unknown count differs from the documented audit."
                ),
            )
        )
    else:
        findings.append(
            _expectation_finding(
                "warning",
                "pydantic_statement_presence",
                pydantic_statement_name,
                "file present",
                "file absent",
                False,
                "The file needed to verify the documented 129 Unknowns is absent.",
            )
        )

    # The README states that all other audited full files have no Unknown outputs.
    # Apply that expectation to every currently present full file while preserving
    # record completeness as a separate concept.
    for row in inventory:
        filename = str(row.get("filename", ""))
        if not filename.endswith("_full.json") or filename == pydantic_statement_name:
            continue
        observed_unknowns = row.get("unknown_prediction_count")
        passed = observed_unknowns == 0
        findings.append(
            _expectation_finding(
                "warning",
                "other_full_file_unknown_count",
                filename,
                0,
                observed_unknowns,
                passed,
                (
                    f"{filename} has no Unknown predictions."
                    if passed
                    else f"{filename} contains Unknown predictions not noted in the prior audit."
                ),
            )
        )

    left = by_filename.get(CANONICAL_SWAPPED_BAB_FILE)
    right = by_filename.get(KNOWN_DUPLICATE_SWAPPED_BAB_FILE)
    if left is None or right is None:
        missing = [
            name
            for name, row in (
                (CANONICAL_SWAPPED_BAB_FILE, left),
                (KNOWN_DUPLICATE_SWAPPED_BAB_FILE, right),
            )
            if row is None
        ]
        findings.append(
            _expectation_finding(
                "warning",
                "known_swapped_bab_duplicate_presence",
                None,
                "both swapped-BAB files present",
                {"missing": missing},
                False,
                "The documented swapped-BAB duplicate pair cannot be fully verified.",
            )
        )
    else:
        left_digest = left.get("normalized_results_sha256")
        right_digest = right.get("normalized_results_sha256")
        passed = bool(left_digest) and left_digest == right_digest
        findings.append(
            _expectation_finding(
                "error",
                "known_swapped_bab_normalized_duplicate",
                None,
                "identical normalized results arrays",
                {
                    CANONICAL_SWAPPED_BAB_FILE: left_digest,
                    KNOWN_DUPLICATE_SWAPPED_BAB_FILE: right_digest,
                },
                passed,
                (
                    "The two swapped-BAB files have identical normalized results arrays."
                    if passed
                    else "The two swapped-BAB files no longer have identical results arrays."
                ),
            )
        )

    return findings


# =============================================================================
# 3. Optional source-script inspection and provenance verification
# =============================================================================


def discover_source_scripts(context: Mapping[str, Any]) -> Dict[str, Path]:
    # Resolve every known script name deterministically. Missing scripts are kept
    # as their expected direct path so the inspection table can report them.
    source_dir = Path(context["source_directory"]).resolve()
    output_dir = Path(context["output_directory"]).resolve()
    scripts: Dict[str, Path] = {}

    indexed_candidates: Dict[str, List[Path]] = defaultdict(list)
    if source_dir.is_dir():
        try:
            for candidate in source_dir.rglob("*.py"):
                try:
                    resolved = candidate.resolve()
                except OSError:
                    continue
                if output_dir == resolved or output_dir in resolved.parents:
                    continue
                if any(
                    part in {".git", ".venv", "venv", "__pycache__", ".mypy_cache"}
                    for part in resolved.parts
                ):
                    continue
                if candidate.name in KNOWN_SOURCE_SCRIPTS:
                    indexed_candidates[candidate.name].append(resolved)
        except OSError as exc:
            warnings.warn(
                f"Could not recursively inspect source directory {source_dir}: {exc}",
                RuntimeWarning,
                stacklevel=2,
            )

    for script_name in KNOWN_SOURCE_SCRIPTS:
        direct = (source_dir / script_name).resolve()
        candidates = indexed_candidates.get(script_name, [])
        if direct.is_file():
            selected = direct
        elif candidates:
            selected = min(
                candidates,
                key=lambda path: (
                    len(path.relative_to(source_dir).parts)
                    if source_dir in path.parents
                    else len(path.parts),
                    str(path).casefold(),
                    str(path),
                ),
            )
            if len(candidates) > 1:
                warnings.warn(
                    f"Multiple copies of {script_name} were found; using {selected}",
                    RuntimeWarning,
                    stacklevel=2,
                )
        else:
            selected = direct
        scripts[script_name] = selected

    return scripts


def _compact_source_snippet(text: str, limit: int = 240) -> str:
    compact = re.sub(r"\s+", " ", text).strip()
    return compact if len(compact) <= limit else compact[: limit - 1] + "…"


def _ast_target_names(node: ast.AST) -> List[str]:
    names: List[str] = []
    if isinstance(node, ast.Name):
        names.append(node.id)
    elif isinstance(node, (ast.Tuple, ast.List)):
        for element in node.elts:
            names.extend(_ast_target_names(element))
    elif isinstance(node, ast.Attribute):
        parts: List[str] = []
        current: Any = node
        while isinstance(current, ast.Attribute):
            parts.append(current.attr)
            current = current.value
        if isinstance(current, ast.Name):
            parts.append(current.id)
        names.append(".".join(reversed(parts)))
    return names


def _call_name(node: ast.Call) -> str:
    function = node.func
    if isinstance(function, ast.Name):
        return function.id
    if isinstance(function, ast.Attribute):
        parts = [function.attr]
        current: Any = function.value
        while isinstance(current, ast.Attribute):
            parts.append(current.attr)
            current = current.value
        if isinstance(current, ast.Name):
            parts.append(current.id)
        return ".".join(reversed(parts))
    return "<dynamic>"


def _literal_text(node: ast.AST) -> str:
    pieces: List[str] = []
    for child in ast.walk(node):
        if isinstance(child, ast.Constant) and isinstance(child.value, str):
            pieces.append(child.value)
    return " ".join(pieces)


def _collect_prompt_segments(tree: ast.AST, source: str) -> Table:
    # Collect likely prompt construction expressions without executing the script.
    # Function/target names help distinguish judge prompts from debater prompts.
    segments: Table = []
    seen: set[Tuple[int, str]] = set()

    class PromptVisitor(ast.NodeVisitor):
        def __init__(self) -> None:
            self.function_stack: List[str] = []

        def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
            self.function_stack.append(node.name)
            self.generic_visit(node)
            self.function_stack.pop()

        def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
            self.function_stack.append(node.name)
            self.generic_visit(node)
            self.function_stack.pop()

        def _record(self, node: ast.AST, descriptor: str) -> None:
            segment = ast.get_source_segment(source, node) or _literal_text(node)
            if not segment:
                return
            literal = _literal_text(node).casefold()
            descriptor_folded = descriptor.casefold()
            promptish = any(
                token in descriptor_folded
                for token in ("prompt", "message", "conversation", "chat", "input_text")
            ) or (
                "abstract" in literal
                and any(token in literal for token in ("candidate", "mesh", "tag", "debater"))
            )
            if not promptish:
                return

            line = int(getattr(node, "lineno", 0) or 0)
            dedupe_key = (line, _compact_source_snippet(segment, 120))
            if dedupe_key in seen:
                return
            seen.add(dedupe_key)

            role_text = f"{' '.join(self.function_stack)} {descriptor} {literal}".casefold()
            if any(token in role_text for token in ("judge", "verdict", "decision")):
                role = "judge"
            elif any(
                token in role_text
                for token in ("debater", "argument", "opening", "rebut", "pro_prompt", "con_prompt")
            ):
                role = "debater"
            else:
                role = "common_or_unknown"

            segments.append(
                {
                    "line": line,
                    "function": self.function_stack[-1] if self.function_stack else None,
                    "descriptor": descriptor,
                    "role": role,
                    "source": segment,
                    "snippet": _compact_source_snippet(segment),
                }
            )

        def visit_Assign(self, node: ast.Assign) -> None:
            targets: List[str] = []
            for target in node.targets:
                targets.extend(_ast_target_names(target))
            self._record(node.value, " ".join(targets))
            self.generic_visit(node)

        def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
            if node.value is not None:
                self._record(node.value, " ".join(_ast_target_names(node.target)))
            self.generic_visit(node)

        def visit_Call(self, node: ast.Call) -> None:
            call = _call_name(node)
            for keyword in node.keywords:
                if keyword.arg and keyword.arg.casefold() in {
                    "prompt",
                    "messages",
                    "message",
                    "conversation",
                    "input_text",
                }:
                    self._record(keyword.value, f"{call}.{keyword.arg}")
            self.generic_visit(node)

        def visit_JoinedStr(self, node: ast.JoinedStr) -> None:
            self._record(node, "f-string")
            self.generic_visit(node)

    PromptVisitor().visit(tree)
    return sorted(segments, key=lambda row: (row["line"], row["descriptor"]))


def _unique_preserving_order(values: Iterable[Any]) -> List[Any]:
    unique: List[Any] = []
    seen = set()
    for value in values:
        marker = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
        if marker not in seen:
            seen.add(marker)
            unique.append(value)
    return unique


def _prompt_feature_value(
    prompt_segments: Sequence[Mapping[str, Any]],
    pattern: str,
    role: str,
    referenced_anywhere: bool,
) -> Optional[bool]:
    role_segments = [
        segment
        for segment in prompt_segments
        if segment.get("role") in {role, "common_or_unknown"}
    ]
    if any(re.search(pattern, str(segment.get("source", "")), re.IGNORECASE) for segment in role_segments):
        return True
    if role_segments or not referenced_anywhere:
        return False
    return None


def inspect_source_script_features(script_paths: Mapping[str, Path]) -> Table:
    # Static inspection deliberately avoids importing or executing experiment code.
    rows: Table = []
    model_pattern = re.compile(
        r"(?:[A-Za-z0-9_.-]+/)?Qwen[A-Za-z0-9_.-]*\d+(?:\.\d+)?B(?:-[A-Za-z0-9_.-]+)?",
        re.IGNORECASE,
    )
    manual_pattern = r"\b(?:nlm[_a-z]*manual|indexing[_a-z]*manual|manual_text|manual_content|manual)\b"
    assigned_pattern = r"\b(?:assigned_tags|assigned_mesh|existing_tags|remaining_tags)\b"

    for script_name, raw_path in sorted(script_paths.items()):
        path = Path(raw_path).resolve()
        base: JSONDict = {
            "script_name": script_name,
            "path": path,
            "present": path.is_file(),
            "readable": False,
            "ast_parsed": False,
            "inspection_status": "missing",
            "error": None,
        }
        if not path.is_file():
            rows.append(base)
            continue

        try:
            source = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            base.update(
                {
                    "inspection_status": "unreadable",
                    "error": f"{type(exc).__name__}: {exc}",
                }
            )
            rows.append(base)
            continue

        base["readable"] = True
        base["sha256"] = compute_sha256(path)
        base["line_count"] = source.count("\n") + (1 if source else 0)
        try:
            tree = ast.parse(source, filename=str(path))
            base["ast_parsed"] = True
            base["inspection_status"] = "inspected"
        except SyntaxError as exc:
            tree = None
            base["inspection_status"] = "text_only_syntax_error"
            base["error"] = f"SyntaxError at line {exc.lineno}: {exc.msg}"

        prompt_segments = _collect_prompt_segments(tree, source) if tree is not None else []
        manual_referenced = bool(re.search(manual_pattern, source, re.IGNORECASE))
        assigned_referenced = bool(re.search(assigned_pattern, source, re.IGNORECASE))

        model_ids = _unique_preserving_order(match.group(0) for match in model_pattern.finditer(source))
        judge_models: List[str] = []
        debater_models: List[str] = []
        model_evidence: Table = []
        source_lines = source.splitlines()
        for match in model_pattern.finditer(source):
            line_number = source.count("\n", 0, match.start()) + 1
            start = max(0, line_number - 2)
            end = min(len(source_lines), line_number + 1)
            context_text = " ".join(source_lines[start:end])
            folded = context_text.casefold()
            model_id = match.group(0)
            role = "unknown"
            if any(token in folded for token in ("judge", "rejudge")):
                judge_models.append(model_id)
                role = "judge"
            if any(token in folded for token in ("debat", "pro_model", "con_model", "expert")):
                debater_models.append(model_id)
                role = "debater" if role == "unknown" else "judge_and_debater_context"
            model_evidence.append(
                {
                    "line": line_number,
                    "model_id": model_id,
                    "role": role,
                    "snippet": _compact_source_snippet(context_text),
                }
            )

        output_targets: List[str] = []
        if tree is not None:
            for node in ast.walk(tree):
                if isinstance(node, ast.Constant) and isinstance(node.value, str):
                    value = node.value.strip()
                    if (
                        value.casefold().endswith(".json")
                        and "result" in value.casefold()
                    ) or (
                        "result" in value.casefold()
                        and any(token in value for token in ("_results", "results_"))
                    ):
                        output_targets.append(value)
        output_targets.extend(
            match.group(1)
            for match in re.finditer(
                r"[\"']([^\"']*result[^\"']*\.json)[\"']",
                source,
                re.IGNORECASE,
            )
        )

        retry_counts: List[int] = []
        for match in re.finditer(
            r"(?:max_?retries|retry_?count|num_?retries)\s*=\s*(\d+)",
            source,
            re.IGNORECASE,
        ):
            retry_counts.append(int(match.group(1)))
        for line in source_lines:
            if re.search(r"retry|attempt", line, re.IGNORECASE):
                match = re.search(r"range\(\s*(\d+)\s*\)", line)
                if match:
                    retry_counts.append(int(match.group(1)))

        call_names: List[str] = []
        if tree is not None:
            call_names = _unique_preserving_order(
                _call_name(node)
                for node in ast.walk(tree)
                if isinstance(node, ast.Call)
            )
        confidence_calls = [
            call
            for call in call_names
            if any(token in call.casefold() for token in ("logprob", "confidence", "score_binary", "score_label"))
        ]
        fallback_calls = [
            call
            for call in call_names
            if "fallback" in call.casefold()
        ]

        issue_pattern = bool(
            re.search(
                r"arg1\s*,\s*arg2\s*=\s*\(\s*a_turn1\s*,\s*b_turn1\s*\)\s*"
                r"if\s+pro_is_a\s+else\s*\(\s*b_turn1\s*,\s*a_turn1\s*\)",
                source,
                re.IGNORECASE | re.DOTALL,
            )
        )
        reuses_pydantic_aba = bool(
            re.search(r"pydantic_interactive", source, re.IGNORECASE)
            and re.search(r"\bABA\b|a_turn1|reuse", source, re.IGNORECASE)
        )

        evidence: Table = []
        for feature, pattern in (
            ("manual_reference", manual_pattern),
            ("assigned_tags_reference", assigned_pattern),
            ("confidence_or_logprob", r"logprob|confidence"),
            ("fallback", r"needed_fallback|fallback"),
            ("pydantic", r"pydantic|BaseModel"),
        ):
            for match in list(re.finditer(pattern, source, re.IGNORECASE))[:5]:
                line_number = source.count("\n", 0, match.start()) + 1
                line = source_lines[line_number - 1] if line_number <= len(source_lines) else ""
                evidence.append(
                    {
                        "feature": feature,
                        "line": line_number,
                        "snippet": _compact_source_snippet(line),
                    }
                )

        manual_in_judge = _prompt_feature_value(
            prompt_segments, manual_pattern, "judge", manual_referenced
        )
        manual_in_debater = _prompt_feature_value(
            prompt_segments, manual_pattern, "debater", manual_referenced
        )
        tags_in_judge = _prompt_feature_value(
            prompt_segments, assigned_pattern, "judge", assigned_referenced
        )
        tags_in_debater = _prompt_feature_value(
            prompt_segments, assigned_pattern, "debater", assigned_referenced
        )

        base.update(
            {
                "model_ids": model_ids,
                "judge_model_ids": _unique_preserving_order(judge_models),
                "debater_model_ids": _unique_preserving_order(debater_models),
                "model_evidence": model_evidence,
                "output_targets": _unique_preserving_order(output_targets),
                "retry_counts": sorted(set(retry_counts)),
                "call_names": call_names,
                "confidence_calls": confidence_calls,
                "fallback_calls": fallback_calls,
                "uses_logprob_or_confidence": bool(
                    confidence_calls or re.search(r"log.?prob|confidence", source, re.IGNORECASE)
                ),
                "uses_fallback": bool(
                    fallback_calls or re.search(r"needed_fallback|fallback", source, re.IGNORECASE)
                ),
                "uses_pydantic": bool(re.search(r"pydantic|BaseModel", source, re.IGNORECASE)),
                "manual_referenced": manual_referenced,
                "manual_in_judge_prompt": manual_in_judge,
                "manual_in_debater_prompt": manual_in_debater,
                "assigned_tags_referenced": assigned_referenced,
                "assigned_tags_in_judge_prompt": tags_in_judge,
                "assigned_tags_in_debater_prompt": tags_in_debater,
                "manual_loaded_but_not_in_any_detected_prompt": bool(
                    manual_referenced
                    and manual_in_judge is False
                    and manual_in_debater is False
                ),
                "assigned_tags_stored_or_loaded_but_not_in_any_detected_prompt": bool(
                    assigned_referenced
                    and tags_in_judge is False
                    and tags_in_debater is False
                ),
                "prompt_segments": prompt_segments,
                "prompt_segment_count": len(prompt_segments),
                "pydantic_interactive_transcript_issue_pattern": issue_pattern,
                "reuses_pydantic_aba_source": reuses_pydantic_aba,
                "evidence": evidence,
            }
        )
        rows.append(base)

    return rows


def _canonical_model_name(value: Any) -> Optional[str]:
    text = normalize_text(value)
    if text is None:
        return None
    return text.rsplit("/", 1)[-1].casefold()


def _select_script_model(
    feature: Mapping[str, Any],
    role: str,
    expected: Any,
) -> Tuple[Any, Optional[str]]:
    role_key = "judge_model_ids" if role == "judge" else "debater_model_ids"
    candidates = list(feature.get(role_key, []) or [])
    if not candidates:
        all_models = list(feature.get("model_ids", []) or [])
        if len(all_models) == 1:
            candidates = all_models
    expected_name = _canonical_model_name(expected)
    if expected_name is not None:
        for candidate in candidates:
            if _canonical_model_name(candidate) == expected_name:
                return candidate, "matched_expected_model_in_source"
    if len(candidates) == 1:
        return candidates[0], "single_role_model_in_source"
    if candidates:
        return candidates, "multiple_role_models_in_source"
    return None, None


def _reconcile_attribute(
    inferred: Any,
    source_value: Any,
    source_available: bool,
    comparable: bool = True,
) -> Tuple[Any, str]:
    if not source_available or source_value is None:
        return inferred, "inferred_or_unknown_no_source_evidence"
    if inferred is None:
        return source_value, "verified_from_source_script"
    if comparable and inferred != source_value:
        return source_value, "conflicting_source_overrode_inference"
    return source_value, "verified_from_source_script"


def reconcile_result_and_script_provenance(
    inventory: Sequence[Mapping[str, Any]],
    script_features: Sequence[Mapping[str, Any]],
) -> Table:
    # Produce one reconciled provenance row per physical result file. The inventory
    # row is enriched in memory so section 4 can use verified prompt/model facts.
    features_by_name = {
        str(row.get("script_name")): row for row in script_features
    }
    reconciled_rows: Table = []

    for inventory_row in inventory:
        inferred = dict(inventory_row.get("provenance", {}) or {})
        script_name = inferred.get("generating_script")
        feature = features_by_name.get(str(script_name)) if script_name else None
        source_available = bool(
            feature
            and feature.get("present")
            and feature.get("readable")
        )
        statuses = dict(inferred.get("attribute_status", {}) or {})
        conflicts: List[str] = []

        judge_source, judge_evidence = (
            _select_script_model(feature, "judge", inferred.get("judge_model"))
            if feature
            else (None, None)
        )
        debater_source, debater_evidence = (
            _select_script_model(feature, "debater", inferred.get("debater_model"))
            if feature
            else (None, None)
        )

        judge_value, judge_status = _reconcile_attribute(
            inferred.get("judge_model"), judge_source, source_available
        )
        debater_value, debater_status = _reconcile_attribute(
            inferred.get("debater_model"),
            debater_source,
            source_available and inferred.get("family") != "baseline",
        )
        if "conflicting" in judge_status:
            conflicts.append("judge_model")
        if "conflicting" in debater_status:
            conflicts.append("debater_model")
        statuses["judge_model"] = judge_status
        statuses["debater_model"] = (
            "not_applicable" if inferred.get("family") == "baseline" else debater_status
        )

        script_values = {
            "manual_in_judge_prompt": (
                feature.get("manual_in_judge_prompt") if feature else None
            ),
            "assigned_tags_in_judge_prompt": (
                feature.get("assigned_tags_in_judge_prompt") if feature else None
            ),
            "assigned_tags_in_debater_prompt": (
                feature.get("assigned_tags_in_debater_prompt") if feature else None
            ),
        }
        reconciled_values: Dict[str, Any] = {}
        for attribute, script_value in script_values.items():
            value, status = _reconcile_attribute(
                inferred.get(attribute), script_value, source_available
            )
            reconciled_values[attribute] = value
            statuses[attribute] = status
            if "conflicting" in status:
                conflicts.append(attribute)

        confidence_value, confidence_status = _reconcile_attribute(
            inferred.get("confidence_available"),
            feature.get("uses_logprob_or_confidence") if feature else None,
            source_available,
        )
        fallback_value, fallback_status = _reconcile_attribute(
            inferred.get("fallback_field_available"),
            feature.get("uses_fallback") if feature else None,
            source_available,
        )
        statuses["confidence_available"] = confidence_status
        statuses["fallback_field_available"] = fallback_status

        reconciled: JSONDict = {
            **inferred,
            **reconciled_values,
            "judge_model": judge_value,
            "debater_model": None if inferred.get("family") == "baseline" else debater_value,
            "confidence_available": confidence_value,
            "fallback_field_available": fallback_value,
            "attribute_status": statuses,
            "source_script_path": feature.get("path") if feature else None,
            "source_script_present": bool(feature and feature.get("present")),
            "source_script_inspection_status": (
                feature.get("inspection_status") if feature else "not_mapped"
            ),
            "source_model_evidence": {
                "judge": judge_evidence,
                "debater": debater_evidence,
            },
            "source_output_targets": feature.get("output_targets", []) if feature else [],
            "source_retry_counts": feature.get("retry_counts", []) if feature else [],
            "source_prompt_segments": feature.get("prompt_segments", []) if feature else [],
            "source_evidence": feature.get("evidence", []) if feature else [],
            "script_feature_flags": {
                "uses_pydantic": feature.get("uses_pydantic") if feature else None,
                "uses_logprob_or_confidence": (
                    feature.get("uses_logprob_or_confidence") if feature else None
                ),
                "uses_fallback": feature.get("uses_fallback") if feature else None,
                "manual_referenced": feature.get("manual_referenced") if feature else None,
                "assigned_tags_referenced": (
                    feature.get("assigned_tags_referenced") if feature else None
                ),
                "pydantic_interactive_transcript_issue_pattern": (
                    feature.get("pydantic_interactive_transcript_issue_pattern")
                    if feature
                    else None
                ),
                "reuses_pydantic_aba_source": (
                    feature.get("reuses_pydantic_aba_source") if feature else None
                ),
            },
            "conflicting_attributes": sorted(set(conflicts)),
            "provenance_status": (
                "conflicting"
                if conflicts
                else "verified_from_source_script"
                if source_available
                else "inferred_without_source_script"
            ),
        }

        output_row = {
            "filename": inventory_row.get("filename"),
            "path": inventory_row.get("path"),
            **reconciled,
        }
        reconciled_rows.append(output_row)
        if isinstance(inventory_row, dict):
            inventory_row["reconciled_provenance"] = reconciled

    return sorted(
        reconciled_rows,
        key=lambda row: (str(row.get("filename", "")).casefold(), str(row.get("filename", ""))),
    )


def identify_known_prompt_and_transcript_issues(
    provenance: Sequence[Mapping[str, Any]],
) -> Table:
    issues: Table = []

    for row in provenance:
        filename = str(row.get("filename", ""))
        family = row.get("family")
        generation = row.get("generation")
        flags = row.get("script_feature_flags", {}) or {}

        if family == "interactive" and generation == "older_pydantic":
            detected = flags.get("pydantic_interactive_transcript_issue_pattern")
            issues.append(
                {
                    "issue_id": "pydantic_interactive_transcript_mapping",
                    "severity": "warning",
                    "filename": filename,
                    "verification": (
                        "verified_from_source_pattern" if detected else "documented_risk_not_verified"
                    ),
                    "evidence": (
                        "The source contains the conditional arg1/arg2 construction that "
                        "reorders A/B opening text when A is CON."
                        if detected
                        else "The known risk could not be confirmed from the available source script."
                    ),
                    "analysis_effect": (
                        "Split by A-is-PRO versus A-is-CON and do not interpret the difference "
                        "as a clean position effect."
                    ),
                }
            )

        if (
            family == "interactive"
            and generation == "robust_0.8B"
            and flags.get("reuses_pydantic_aba_source")
        ):
            issues.append(
                {
                    "issue_id": "robust_aba_reuses_pydantic_turns",
                    "severity": "info",
                    "filename": filename,
                    "verification": "verified_from_source_pattern",
                    "evidence": "The robust interactive script references the older Pydantic ABA source.",
                    "analysis_effect": (
                        "The ABA argument text may be reused while the judge transcript construction "
                        "and judgment are new; verify text identity record by record."
                    ),
                }
            )

        for attribute, subject in (
            ("manual_in_judge_prompt", "NLM manual"),
            ("assigned_tags_in_judge_prompt", "assigned tags"),
        ):
            if row.get(attribute) is False and family in {"statement", "interactive"}:
                issues.append(
                    {
                        "issue_id": f"{family}_{attribute}_omitted",
                        "severity": "info",
                        "filename": filename,
                        "verification": row.get("attribute_status", {}).get(attribute),
                        "evidence": f"{subject} is not inserted into the detected judge prompt.",
                        "analysis_effect": (
                            "Do not infer actual model input from fields merely stored in the JSON record."
                        ),
                    }
                )

    by_family: Dict[str, set[str]] = defaultdict(set)
    for row in provenance:
        family = str(row.get("family", "unknown"))
        generation = str(row.get("generation", "unknown"))
        by_family[family].add(generation)
    for family, generations in sorted(by_family.items()):
        if family in {"baseline", "statement", "interactive"} and len(generations) > 1:
            issues.append(
                {
                    "issue_id": f"{family}_cross_generation_multifactor_comparison",
                    "severity": "warning",
                    "filename": None,
                    "verification": "derived_from_provenance_inventory",
                    "evidence": f"Observed generations: {', '.join(sorted(generations))}.",
                    "analysis_effect": (
                        "Legacy, older-Pydantic, robust, and rejudged conditions may differ in "
                        "prompts, available inputs, parser/retries, fallback, model, or content."
                    ),
                }
            )

    return issues


# =============================================================================
# 4. Record normalization into one condition-row schema
# =============================================================================


def normalize_text(value: Any) -> Optional[str]:
    if value is MISSING or value is None:
        return None
    if isinstance(value, str):
        text = value.strip()
        return text or None
    if isinstance(value, (Mapping, list, tuple)):
        try:
            text = json.dumps(value, ensure_ascii=False, sort_keys=True)
        except (TypeError, ValueError):
            text = str(value)
    else:
        text = str(value)
    text = text.strip()
    return text or None


def normalize_label(value: Any) -> str:
    if value is MISSING or value is None:
        return "Missing"
    if not isinstance(value, str):
        return "Invalid"
    folded = value.strip().casefold()
    if folded in {"yes", "y", "true"}:
        return "Yes"
    if folded in {"no", "n", "false"}:
        return "No"
    if folded in {"unknown", "unresolved", "parse_error", "parse error"}:
        return "Unknown"
    if not folded:
        return "Missing"
    return "Invalid"


def normalize_stage(value: Any) -> Optional[str]:
    text = normalize_text(value)
    if text is None:
        return None
    folded = re.sub(r"\s+", " ", text).strip().casefold()
    exact = {stage.casefold(): stage for stage in EXPECTED_STAGE_COUNTS}
    if folded in exact:
        return exact[folded]
    if re.search(r"\bround\s*1\b|\btrue\s*tag\b|\bpositive\b", folded):
        return "Round 1: True Tag"
    if re.search(r"\bround\s*2\b|\bunrelated\s*tag\b|\brandom\s*(?:negative|tag)\b", folded):
        return "Round 2: Unrelated Tag"
    if re.search(r"\bround\s*3\b|\bsimilar\s*tag\b|\bhard\s*negative\b", folded):
        return "Round 3: Similar Tag"
    return f"Unresolved stage: {text}"


def normalize_pmid(value: Any) -> Optional[str]:
    if value is MISSING or value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if value.is_integer():
            return str(int(value))
        return format(value, ".15g")
    text = str(value).strip()
    return text or None


def normalize_candidate_tag(value: Any) -> Optional[str]:
    text = normalize_text(value)
    if text is None:
        return None
    normalized = unicodedata.normalize("NFKC", text)
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return normalized.casefold() or None


def make_stage_pmid_key(row: Mapping[str, Any]) -> Tuple[Any, Any]:
    return row.get("stage"), row.get("pmid")


def make_exact_match_key(row: Mapping[str, Any]) -> Tuple[Any, Any, Any, Any]:
    candidate = row.get("candidate_tag_normalized")
    if candidate is None:
        candidate = normalize_candidate_tag(row.get("candidate_tag"))
    return (
        row.get("stage"),
        row.get("pmid"),
        candidate,
        row.get("ground_truth"),
    )


def infer_ground_truth(record: Mapping[str, Any], stage: Optional[str]) -> str:
    stored = normalize_label(record.get("ground_truth", MISSING))
    if stored in VALID_BINARY_LABELS:
        return stored
    if stage == "Round 1: True Tag":
        return "Yes"
    if stage in {"Round 2: Unrelated Tag", "Round 3: Similar Tag"}:
        return "No"
    return stored


def _normalize_boolean(value: Any) -> Optional[bool]:
    if value is MISSING or value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and value in {0, 1}:
        return bool(value)
    if isinstance(value, str):
        folded = value.strip().casefold()
        if folded in {"true", "yes", "1", "y"}:
            return True
        if folded in {"false", "no", "0", "n"}:
            return False
    return None


def _normalize_side(value: Any) -> Optional[str]:
    text = normalize_text(value)
    if text is None:
        return None
    folded = re.sub(r"[^a-z]+", " ", text.casefold()).strip()
    if folded in {"pro", "yes", "for", "belongs", "positive"} or folded.startswith("pro "):
        return "PRO"
    if folded in {"con", "contra", "no", "against", "does not belong", "negative"} or folded.startswith("con "):
        return "CON"
    return None


def _condition_containers(record: Mapping[str, Any], condition_id: str) -> List[Mapping[str, Any]]:
    folded = condition_id.casefold()
    if "swapped" in folded:
        keys = ("debate_BAB_swapped_labels", "debate_BAB_swapped", "bab_swapped_labels")
    elif ".bab" in folded or folded.endswith("_bab") or "condition_bab" in folded:
        keys = ("debate_BAB", "bab_debate", "BAB")
    elif ".aba" in folded or folded.endswith("_aba") or "interactive" in folded:
        keys = ("debate_ABA", "aba_debate", "ABA")
    else:
        keys = ()

    containers: List[Mapping[str, Any]] = []
    for key in keys:
        value = record.get(key, MISSING)
        if isinstance(value, Mapping):
            containers.append(value)
    containers.append(record)

    expanded: List[Mapping[str, Any]] = []
    seen_ids = set()
    for container in containers:
        for candidate in (
            container,
            container.get("side_mapping") if isinstance(container.get("side_mapping"), Mapping) else None,
            container.get("mapping") if isinstance(container.get("mapping"), Mapping) else None,
        ):
            if isinstance(candidate, Mapping) and id(candidate) not in seen_ids:
                seen_ids.add(id(candidate))
                expanded.append(candidate)
    return expanded


def _first_container_value(
    containers: Sequence[Mapping[str, Any]],
    names: Sequence[str],
) -> Any:
    for container in containers:
        for name in names:
            if name in container and container[name] is not None:
                return container[name]
    return MISSING


def infer_side_mapping(record: Mapping[str, Any], condition_id: str) -> JSONDict:
    containers = _condition_containers(record, condition_id)
    folded = condition_id.casefold()
    swapped = "swapped" in folded

    original_a = _normalize_side(
        _first_container_value(containers, ("a_side", "debater_a_side", "original_a_side"))
    )
    original_b = _normalize_side(
        _first_container_value(containers, ("b_side", "debater_b_side", "original_b_side"))
    )
    pro_is_a = _normalize_boolean(
        _first_container_value(
            containers,
            ("pro_is_a", "a_is_pro", "pro_is_debater_a", "debater_a_is_pro"),
        )
    )
    if pro_is_a is None:
        # Older statement/interactive schemas commonly use pro_first to mean that
        # the first displayed debater, A, owns the PRO side.
        pro_is_a = _normalize_boolean(
            _first_container_value(containers, ("pro_first",))
        )

    if original_a is None and pro_is_a is not None:
        original_a = "PRO" if pro_is_a else "CON"
    if original_b is None and original_a in {"PRO", "CON"}:
        original_b = "CON" if original_a == "PRO" else "PRO"
    if original_a is None and original_b in {"PRO", "CON"}:
        original_a = "CON" if original_b == "PRO" else "PRO"

    presented_a = _normalize_side(
        _first_container_value(
            containers,
            ("presented_a_side", "displayed_a_side", "swapped_a_side"),
        )
    )
    presented_b = _normalize_side(
        _first_container_value(
            containers,
            ("presented_b_side", "displayed_b_side", "swapped_b_side"),
        )
    )
    if swapped:
        if presented_a is None:
            presented_a = original_b
        if presented_b is None:
            presented_b = original_a
    else:
        presented_a = presented_a or original_a
        presented_b = presented_b or original_b

    if presented_a is None and presented_b in {"PRO", "CON"}:
        presented_a = "CON" if presented_b == "PRO" else "PRO"
    if presented_b is None and presented_a in {"PRO", "CON"}:
        presented_b = "CON" if presented_a == "PRO" else "PRO"

    pro_label = "A" if presented_a == "PRO" else "B" if presented_b == "PRO" else None
    con_label = "A" if presented_a == "CON" else "B" if presented_b == "CON" else None

    if "statement" in folded or ".aba" in folded or "swapped" in folded:
        first_label = "A"
    elif ".bab" in folded:
        first_label = "B"
    else:
        first_label = "A" if "interactive" in folded else None
    first_side = presented_a if first_label == "A" else presented_b if first_label == "B" else None

    return {
        "original_a_side": original_a,
        "original_b_side": original_b,
        "displayed_a_side": presented_a,
        "displayed_b_side": presented_b,
        "a_side": presented_a,
        "b_side": presented_b,
        "pro_is_a_original": original_a == "PRO" if original_a else None,
        "pro_is_displayed_a": presented_a == "PRO" if presented_a else None,
        "pro_displayed_label": pro_label,
        "con_displayed_label": con_label,
        "pro_is_first": first_side == "PRO" if first_side else None,
        "side_mapping_available": bool(presented_a and presented_b),
        "labels_swapped": swapped,
    }


def infer_turn_structure(record: Mapping[str, Any], condition_id: str) -> JSONDict:
    folded = condition_id.casefold()
    mapping = infer_side_mapping(record, condition_id)

    if "baseline" in folded:
        labels: List[str] = []
        structure = "no_debaters"
    elif "statement" in folded:
        labels = ["A", "B"]
        structure = "independent_statements_A_then_B"
    elif ".bab" in folded and "swapped" not in folded:
        labels = ["B", "A", "B"]
        structure = "BAB"
    else:
        labels = ["A", "B", "A"]
        structure = "BAB_content_with_swapped_display_labels" if "swapped" in folded else "ABA"

    def side_for(label: Optional[str]) -> Optional[str]:
        if label == "A":
            return mapping.get("displayed_a_side")
        if label == "B":
            return mapping.get("displayed_b_side")
        return None

    first_label = labels[0] if labels else None
    last_label = labels[-1] if labels else None
    two_turn_label = None
    if len(labels) == 3:
        counts = Counter(labels)
        two_turn_label = next((label for label, count in counts.items() if count == 2), None)

    if "statement" in folded:
        confounding = "Displayed A is also the first essay; label and position cannot be separated."
    elif labels and len(labels) == 3:
        confounding = (
            "The opening speaker is also the closing and two-turn speaker; first, last, and turn-count effects are confounded."
        )
    else:
        confounding = None

    return {
        "turn_structure": structure,
        "speaker_sequence": labels,
        "first_speaker_label": first_label,
        "middle_speaker_label": labels[1] if len(labels) == 3 else None,
        "last_speaker_label": last_label,
        "two_turn_speaker_label": two_turn_label,
        "first_speaker_side": side_for(first_label),
        "last_speaker_side": side_for(last_label),
        "two_turn_speaker_side": side_for(two_turn_label),
        "pro_is_first": side_for(first_label) == "PRO" if first_label else None,
        "pro_is_last": side_for(last_label) == "PRO" if last_label else None,
        "pro_has_two_turns": side_for(two_turn_label) == "PRO" if two_turn_label else None,
        "position_effects_confounded": bool(confounding),
        "position_confounding_note": confounding,
    }


def _first_text(
    containers: Sequence[Mapping[str, Any]],
    names: Sequence[str],
) -> Optional[str]:
    return normalize_text(_first_container_value(containers, names))


def extract_argument_texts(record: Mapping[str, Any], condition_id: str) -> JSONDict:
    folded = condition_id.casefold()
    containers = _condition_containers(record, condition_id)
    mapping = infer_side_mapping(record, condition_id)
    ordered_turns: List[JSONDict] = []

    arg_a: Optional[str] = None
    arg_b: Optional[str] = None
    pro_argument: Optional[str] = None
    con_argument: Optional[str] = None

    if "statement" in folded:
        pro_argument = _first_text(containers, ("pro_argument", "pro_statement", "argument_pro"))
        con_argument = _first_text(containers, ("con_argument", "con_statement", "argument_con"))
        arg_a = _first_text(containers, ("arg_a", "argument_a", "a_argument"))
        arg_b = _first_text(containers, ("arg_b", "argument_b", "b_argument"))
        if arg_a is None:
            arg_a = pro_argument if mapping.get("displayed_a_side") == "PRO" else con_argument
        if arg_b is None:
            arg_b = pro_argument if mapping.get("displayed_b_side") == "PRO" else con_argument
        if pro_argument is None:
            pro_argument = arg_a if mapping.get("displayed_a_side") == "PRO" else arg_b
        if con_argument is None:
            con_argument = arg_a if mapping.get("displayed_a_side") == "CON" else arg_b
        for index, (label, text) in enumerate((("A", arg_a), ("B", arg_b)), start=1):
            if text is not None:
                ordered_turns.append(
                    {
                        "turn": index,
                        "label": label,
                        "side": mapping.get(f"displayed_{label.casefold()}_side"),
                        "text": text,
                    }
                )
    elif "interactive" in folded:
        if "swapped" in folded:
            turn_specs = (
                ("A", ("a_opening", "a_turn1", "b_opening_original", "b_opening")),
                ("B", ("b_rebuttal", "b_turn1", "a_rebuttal_original", "a_rebuttal")),
                ("A", ("a_closing", "a_turn2", "b_closing_original", "b_closing")),
            )
        elif ".bab" in folded:
            turn_specs = (
                ("B", ("b_opening", "b_turn1", "bab_b_opening")),
                ("A", ("a_rebuttal", "a_turn1", "bab_a_rebuttal")),
                ("B", ("b_closing", "b_turn2", "bab_b_closing")),
            )
        else:
            turn_specs = (
                ("A", ("a_turn1", "a_opening", "aba_a_opening")),
                ("B", ("b_turn1", "b_rebuttal", "aba_b_rebuttal")),
                ("A", ("a_turn2", "a_closing", "aba_a_closing")),
            )

        for index, (label, aliases) in enumerate(turn_specs, start=1):
            text = _first_text(containers, aliases)
            if text is not None:
                ordered_turns.append(
                    {
                        "turn": index,
                        "label": label,
                        "side": mapping.get(f"displayed_{label.casefold()}_side"),
                        "text": text,
                    }
                )

        if not ordered_turns:
            turns_value = _first_container_value(containers, ("turns", "debate_turns"))
            if isinstance(turns_value, list):
                for index, turn in enumerate(turns_value, start=1):
                    if isinstance(turn, Mapping):
                        label = normalize_text(turn.get("speaker") or turn.get("label"))
                        label = label.upper() if label and label.upper() in {"A", "B"} else None
                        text = normalize_text(turn.get("text") or turn.get("argument") or turn.get("content"))
                        if text is not None:
                            ordered_turns.append(
                                {
                                    "turn": index,
                                    "label": label,
                                    "side": mapping.get(f"displayed_{label.casefold()}_side") if label else None,
                                    "text": text,
                                }
                            )

        a_texts = [turn["text"] for turn in ordered_turns if turn.get("label") == "A"]
        b_texts = [turn["text"] for turn in ordered_turns if turn.get("label") == "B"]
        arg_a = "\n\n".join(a_texts) if a_texts else None
        arg_b = "\n\n".join(b_texts) if b_texts else None
        pro_argument = arg_a if mapping.get("displayed_a_side") == "PRO" else arg_b
        con_argument = arg_a if mapping.get("displayed_a_side") == "CON" else arg_b

    transcript = _first_text(containers, ("transcript", "debate_transcript", "formatted_transcript"))
    if transcript is None and ordered_turns:
        transcript = "\n\n".join(
            f"Debater {turn.get('label')}: {turn['text']}" for turn in ordered_turns
        )

    return {
        "arg_a": arg_a,
        "arg_b": arg_b,
        "a_argument_text": arg_a,
        "b_argument_text": arg_b,
        "pro_argument": pro_argument,
        "con_argument": con_argument,
        "pro_argument_text": pro_argument,
        "con_argument_text": con_argument,
        "ordered_turns": ordered_turns,
        "transcript": transcript,
        "argument_text_available": bool(arg_a or arg_b or pro_argument or con_argument or ordered_turns),
    }


def _as_probability(value: Any) -> Optional[float]:
    if isinstance(value, bool) or value is None or value is MISSING:
        return None
    try:
        converted = float(value)
    except (TypeError, ValueError):
        return None
    if 0.0 <= converted <= 1.0:
        return converted
    return None


def _as_number(value: Any) -> Optional[float]:
    if isinstance(value, bool) or value is None or value is MISSING:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _normalize_logprob_pair(value: Any, left: str, right: str) -> Optional[JSONDict]:
    if not isinstance(value, Mapping):
        return None
    casefolded = {str(key).casefold(): item for key, item in value.items()}
    left_value = _as_number(casefolded.get(left.casefold()))
    right_value = _as_number(casefolded.get(right.casefold()))
    if left_value is None and right_value is None:
        return None
    return {left: left_value, right: right_value}


def extract_confidence_fields(judgment: Mapping[str, Any]) -> JSONDict:
    confidence_value = judgment.get("confidence", MISSING)
    confidence = confidence_value if isinstance(confidence_value, Mapping) else judgment

    verdict_logprob = _normalize_logprob_pair(
        confidence.get("verdict_logprob", MISSING), "Yes", "No"
    )
    boolean_logprob = _normalize_logprob_pair(
        confidence.get("boolean_logprob", MISSING), "true", "false"
    )
    debater_logprob = _normalize_logprob_pair(
        confidence.get("debater_logprob", MISSING), "A", "B"
    )

    verdict_probability = _as_probability(
        confidence.get("verdict_prob_belongs", confidence.get("prob_yes", MISSING))
    )
    boolean_probability = _as_probability(
        confidence.get("boolean_prob_true", confidence.get("prob_true", MISSING))
    )
    debater_probability = _as_probability(
        confidence.get("debater_prob_A_right", confidence.get("prob_a_right", MISSING))
    )
    fallback = _normalize_boolean(judgment.get("needed_fallback", MISSING))

    return {
        "verdict_prob_belongs": verdict_probability,
        "boolean_prob_true": boolean_probability,
        "debater_prob_A_right": debater_probability,
        "verdict_logprob": verdict_logprob,
        "boolean_logprob": boolean_logprob,
        "debater_logprob": debater_logprob,
        "needed_fallback": fallback,
        "confidence_available": any(
            value is not None
            for value in (
                verdict_probability,
                boolean_probability,
                debater_probability,
                verdict_logprob,
                boolean_logprob,
                debater_logprob,
            )
        ),
        "confidence_provenance": (
            "teacher-forced follow-up label scoring; not the probability of the original explanation"
        ),
    }


def _stage_expected_truth(stage: Optional[str]) -> Optional[str]:
    if stage == "Round 1: True Tag":
        return "Yes"
    if stage in {"Round 2: Unrelated Tag", "Round 3: Similar Tag"}:
        return "No"
    return None


def _condition_variant(condition_id: str) -> Optional[str]:
    folded = condition_id.casefold()
    if "swapped" in folded:
        return "BAB_swapped_labels"
    if folded.endswith(".aba"):
        return "ABA"
    if folded.endswith(".bab"):
        return "BAB"
    if "statement" in folded:
        return "independent_statements"
    return None


def _argument_digest(arguments: Mapping[str, Any]) -> Optional[str]:
    ordered = arguments.get("ordered_turns") or []
    material = {
        "arg_a": arguments.get("arg_a"),
        "arg_b": arguments.get("arg_b"),
        "pro_argument": arguments.get("pro_argument"),
        "con_argument": arguments.get("con_argument"),
        "ordered_turns": [
            {
                "turn": turn.get("turn"),
                "label": turn.get("label"),
                "side": turn.get("side"),
                "text": turn.get("text"),
            }
            for turn in ordered
            if isinstance(turn, Mapping)
        ],
    }
    if not any(
        value for key, value in material.items() if key != "ordered_turns"
    ) and not material["ordered_turns"]:
        return None
    encoded = json.dumps(material, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def build_normalized_row(
    source_path: Path,
    file_info: Mapping[str, Any],
    record: Mapping[str, Any],
    condition_id: str,
    prediction_path: str,
    judgment: Mapping[str, Any],
) -> Row:
    raw_stage = record.get("stage", MISSING)
    stage = normalize_stage(raw_stage)
    pmid = normalize_pmid(record.get("pmid", MISSING))
    candidate_display = normalize_text(record.get("candidate_tag", MISSING))
    if candidate_display is not None:
        candidate_display = re.sub(r"\s+", " ", candidate_display).strip()
    candidate_normalized = normalize_candidate_tag(candidate_display)

    stored_truth = normalize_label(record.get("ground_truth", MISSING))
    truth = infer_ground_truth(record, stage)
    expected_truth = _stage_expected_truth(stage)
    truth_conflict = bool(
        stored_truth in VALID_BINARY_LABELS
        and expected_truth in VALID_BINARY_LABELS
        and stored_truth != expected_truth
    )

    raw_prediction = get_nested_value(record, prediction_path)
    if raw_prediction is MISSING and prediction_path.rsplit(".", 1)[-1] in judgment:
        raw_prediction = judgment[prediction_path.rsplit(".", 1)[-1]]
    prediction = normalize_label(raw_prediction)
    prediction_valid = prediction in VALID_BINARY_LABELS
    truth_valid = truth in VALID_BINARY_LABELS
    binary_correct = prediction == truth if prediction_valid and truth_valid else None

    provenance = (
        file_info.get("reconciled_provenance")
        or file_info.get("provenance")
        or {}
    )
    side_mapping = infer_side_mapping(record, condition_id)
    turn_structure = infer_turn_structure(record, condition_id)
    arguments = extract_argument_texts(record, condition_id)
    confidence = extract_confidence_fields(judgment)
    if confidence.get("needed_fallback") is None:
        confidence["needed_fallback"] = _normalize_boolean(
            record.get("needed_fallback", MISSING)
        )

    stored_correct = judgment.get("is_correct", record.get("is_correct", MISSING))
    stored_correct = stored_correct if isinstance(stored_correct, bool) else None
    abstract = normalize_text(record.get("abstract", MISSING))
    raw_output = _first_container_value(
        (judgment, record),
        ("judge_output", "full_model_output", "model_output", "raw_output"),
    )

    row: Row = {
        "source_file": source_path.name,
        "source_path": source_path.resolve(),
        "source_record_index": record.get("__source_record_index"),
        "family": file_info.get("family"),
        "generation": file_info.get("generation"),
        "condition_id": condition_id,
        "condition_variant": _condition_variant(condition_id),
        "prediction_path": prediction_path,
        "stage_raw": None if raw_stage is MISSING else raw_stage,
        "stage": stage,
        "pmid": pmid,
        "candidate_tag": candidate_display,
        "candidate_tag_normalized": candidate_normalized,
        "ground_truth_stored": stored_truth,
        "ground_truth": truth,
        "ground_truth_source": "stored" if stored_truth in VALID_BINARY_LABELS else "stage_inferred",
        "ground_truth_stage_expected": expected_truth,
        "ground_truth_stage_conflict": truth_conflict,
        "raw_prediction": None if raw_prediction is MISSING else raw_prediction,
        "prediction": prediction,
        "prediction_valid": prediction_valid,
        "truth_valid": truth_valid,
        "binary_correct": binary_correct,
        "strict_correct": bool(binary_correct),
        "stored_is_correct": stored_correct,
        "stored_is_correct_mismatch": (
            stored_correct != bool(binary_correct) if stored_correct is not None else None
        ),
        "judge_model": provenance.get("judge_model"),
        "debater_model": provenance.get("debater_model"),
        "manual_in_judge_prompt": provenance.get("manual_in_judge_prompt"),
        "assigned_tags_in_judge_prompt": provenance.get("assigned_tags_in_judge_prompt"),
        "assigned_tags_in_debater_prompt": provenance.get("assigned_tags_in_debater_prompt"),
        "parser_type": provenance.get("parser_type"),
        "fallback_behavior": provenance.get("fallback_behavior"),
        "provenance_status": provenance.get("provenance_status", "inferred"),
        "abstract": abstract,
        "assigned_tags": record.get("assigned_tags") if "assigned_tags" in record else None,
        "raw_judge_output": None if raw_output is MISSING else raw_output,
        "argument_content_sha256": _argument_digest(arguments),
    }
    row.update(side_mapping)
    row.update(turn_structure)
    row.update(arguments)
    row.update(confidence)
    row["loose_key"] = make_stage_pmid_key(row)
    row["exact_match_key"] = make_exact_match_key(row)
    return row


def _condition_id_for(
    source_path: Path,
    file_info: Mapping[str, Any],
    variant: Optional[str] = None,
) -> str:
    family = str(file_info.get("family") or "unknown")
    generation = str(file_info.get("generation") or "unresolved")
    filename = source_path.name.casefold()

    if family == "baseline":
        if "nomanual" in filename:
            return "baseline.robust_0.8B.no_manual"
        if "withmanual" in filename:
            return "baseline.robust_0.8B.with_manual"
        if generation == "older_pydantic":
            return "baseline.older_pydantic_0.8B"
        if generation == "legacy":
            return "baseline.legacy_0.8B"
        return f"baseline.{re.sub(r'[^a-z0-9]+', '_', generation.casefold()).strip('_')}"

    if family == "statement":
        if generation == "rejudge_2B":
            return "statement.rejudge_2B"
        if generation == "robust_0.8B":
            return "statement.robust_0.8B"
        if generation == "older_pydantic":
            return "statement.older_pydantic_0.8B"
        if generation == "legacy":
            return "statement.legacy_0.8B"
        return f"statement.{re.sub(r'[^a-z0-9]+', '_', generation.casefold()).strip('_')}"

    if family == "interactive":
        if generation == "rejudge_2B":
            prefix = "interactive.rejudge_2B"
        elif generation == "robust_0.8B":
            prefix = "interactive.robust_0.8B"
        elif generation == "swapped_labels":
            prefix = "interactive.robust_0.8B"
        elif generation == "older_pydantic":
            prefix = "interactive.older_pydantic_0.8B"
        elif generation == "legacy":
            prefix = "interactive.legacy_0.8B"
        else:
            token = re.sub(r"[^a-z0-9]+", "_", generation.casefold()).strip("_")
            prefix = f"interactive.{token}"
        return f"{prefix}.{variant or 'ABA'}"

    token = re.sub(r"[^a-z0-9]+", "_", source_path.stem.casefold()).strip("_")
    return f"unknown.{token}.{variant}" if variant else f"unknown.{token}"


def _preferred_top_level_prediction_path(
    record: Mapping[str, Any],
    file_info: Mapping[str, Any],
) -> str:
    generation = file_info.get("generation")
    preferred = (
        ("prediction", "model_prediction")
        if generation in {"robust_0.8B", "rejudge_2B", "swapped_labels"}
        else ("model_prediction", "prediction")
    )
    for path in preferred:
        if path in record:
            return path
    detected = file_info.get("prediction_paths", []) or []
    for path in detected:
        if "." not in str(path):
            return str(path)
    return preferred[0]


def normalize_baseline_record(
    source_path: Path,
    file_info: Mapping[str, Any],
    record: Mapping[str, Any],
) -> List[Row]:
    prediction_path = _preferred_top_level_prediction_path(record, file_info)
    condition_id = _condition_id_for(source_path, file_info)
    return [
        build_normalized_row(
            source_path,
            file_info,
            record,
            condition_id,
            prediction_path,
            record,
        )
    ]


def normalize_statement_record(
    source_path: Path,
    file_info: Mapping[str, Any],
    record: Mapping[str, Any],
) -> List[Row]:
    prediction_path = _preferred_top_level_prediction_path(record, file_info)
    condition_id = _condition_id_for(source_path, file_info)
    return [
        build_normalized_row(
            source_path,
            file_info,
            record,
            condition_id,
            prediction_path,
            record,
        )
    ]


def normalize_legacy_interactive_record(
    source_path: Path,
    file_info: Mapping[str, Any],
    record: Mapping[str, Any],
) -> List[Row]:
    prediction_path = _preferred_top_level_prediction_path(record, file_info)
    condition_id = _condition_id_for(source_path, file_info, "ABA")
    return [
        build_normalized_row(
            source_path,
            file_info,
            record,
            condition_id,
            prediction_path,
            record,
        )
    ]


def normalize_robust_interactive_record(
    source_path: Path,
    file_info: Mapping[str, Any],
    record: Mapping[str, Any],
) -> List[Row]:
    generation = file_info.get("generation")
    if generation == "swapped_labels" or "swapped" in source_path.name.casefold():
        specifications = (
            ("BAB_swapped_labels", "judge_BAB_swapped_labels.prediction"),
        )
    else:
        specifications = (
            ("ABA", "judge_ABA.prediction"),
            ("BAB", "judge_BAB.prediction"),
        )

    rows: List[Row] = []
    for variant, prediction_path in specifications:
        parent_path = prediction_path.rsplit(".", 1)[0]
        judgment_value = get_nested_value(record, parent_path)
        if not isinstance(judgment_value, Mapping):
            # A wholly absent nested judgment is not an unresolved prediction; it is
            # an unavailable condition and should not create 3,000 synthetic Missing rows.
            continue
        condition_id = _condition_id_for(source_path, file_info, variant)
        rows.append(
            build_normalized_row(
                source_path,
                file_info,
                record,
                condition_id,
                prediction_path,
                judgment_value,
            )
        )
    return rows


def normalize_one_file(
    source_path: Path,
    payload: Mapping[str, Any],
    file_info: Mapping[str, Any],
) -> List[Row]:
    raw_records = payload.get("results", [])
    if not isinstance(raw_records, list):
        return []

    family = file_info.get("family")
    indicators = file_info.get("schema", {}).get("indicators", {})
    normalized: List[Row] = []
    for index, raw_record in enumerate(raw_records):
        if not isinstance(raw_record, Mapping):
            continue
        record = dict(raw_record)
        record["__source_record_index"] = index
        if family == "baseline":
            normalized.extend(normalize_baseline_record(source_path, file_info, record))
        elif family == "statement":
            normalized.extend(normalize_statement_record(source_path, file_info, record))
        elif family == "interactive" and (
            indicators.get("robust_interactive")
            or file_info.get("generation") in {"rejudge_2B", "swapped_labels"}
        ):
            normalized.extend(
                normalize_robust_interactive_record(source_path, file_info, record)
            )
        elif family == "interactive":
            normalized.extend(
                normalize_legacy_interactive_record(source_path, file_info, record)
            )
    return normalized


def normalize_all_files(
    payloads: Mapping[Path, Mapping[str, Any]],
    inventory: Sequence[Mapping[str, Any]],
    canonical_paths: Sequence[Path],
) -> Tuple[List[Row], Table]:
    rows: List[Row] = []
    findings: Table = []
    payload_by_path = {Path(path).resolve(): payload for path, payload in payloads.items()}
    inventory_by_path = {
        Path(item["path"]).resolve(): item
        for item in inventory
        if item.get("path") is not None
    }

    for raw_path in canonical_paths:
        path = Path(raw_path).resolve()
        payload = payload_by_path.get(path)
        file_info = inventory_by_path.get(path)
        if payload is None or file_info is None:
            findings.append(
                {
                    "severity": "error",
                    "filename": path.name,
                    "status": "excluded",
                    "reason": "Missing loaded payload or inventory row.",
                    "normalized_rows": 0,
                }
            )
            continue
        if file_info.get("family") == "unknown":
            findings.append(
                {
                    "severity": "warning",
                    "filename": path.name,
                    "status": "excluded",
                    "reason": "Unsupported or unresolved experiment family.",
                    "normalized_rows": 0,
                }
            )
            continue

        try:
            file_rows = normalize_one_file(path, payload, file_info)
        except Exception as exc:
            findings.append(
                {
                    "severity": "error",
                    "filename": path.name,
                    "status": "excluded",
                    "reason": f"Normalization failed: {type(exc).__name__}: {exc}",
                    "normalized_rows": 0,
                }
            )
            continue

        rows.extend(file_rows)
        source_record_count = file_info.get("valid_record_objects", 0)
        findings.append(
            {
                "severity": "info" if file_rows else "warning",
                "filename": path.name,
                "status": "normalized" if file_rows else "excluded",
                "reason": None if file_rows else "No supported prediction condition was found.",
                "source_records": source_record_count,
                "normalized_rows": len(file_rows),
                "condition_ids": sorted({row["condition_id"] for row in file_rows}),
            }
        )

    # A shared condition ID from distinct non-duplicate files would accidentally pool
    # experiments. Report it now so later integrity logic can block comparisons.
    condition_sources: Dict[str, set[str]] = defaultdict(set)
    for row in rows:
        condition_sources[str(row["condition_id"])].add(str(row["source_file"]))
    for condition_id, sources in sorted(condition_sources.items()):
        if len(sources) > 1:
            findings.append(
                {
                    "severity": "warning",
                    "filename": None,
                    "status": "condition_id_collision",
                    "reason": (
                        "Multiple source files map to one condition ID; verify they are chunks "
                        "or rename the condition before pooling."
                    ),
                    "condition_ids": [condition_id],
                    "source_files": sorted(sources),
                }
            )

    return rows, findings


def _consistent_catalog_value(rows: Sequence[Mapping[str, Any]], key: str) -> Any:
    values = _unique_preserving_order(
        row.get(key) for row in rows if row.get(key) is not None
    )
    if not values:
        return None
    return values[0] if len(values) == 1 else values


def _condition_display_name(condition_id: str) -> str:
    replacements = {
        "baseline.robust_0.8B.no_manual": "Baseline 0.8B — no manual",
        "baseline.robust_0.8B.with_manual": "Baseline 0.8B — with manual",
        "baseline.older_pydantic_0.8B": "Baseline 0.8B — older Pydantic",
        "baseline.legacy_0.8B": "Baseline 0.8B — legacy",
        "statement.robust_0.8B": "Statement — 0.8B judge",
        "statement.rejudge_2B": "Statement — rejudged by 2B",
        "statement.older_pydantic_0.8B": "Statement — older Pydantic",
        "statement.legacy_0.8B": "Statement — legacy",
        "interactive.robust_0.8B.ABA": "Interactive ABA — 0.8B judge",
        "interactive.robust_0.8B.BAB": "Interactive BAB — 0.8B judge",
        "interactive.robust_0.8B.BAB_swapped_labels": "Interactive BAB — displayed labels swapped",
        "interactive.rejudge_2B.ABA": "Interactive ABA — rejudged by 2B",
        "interactive.rejudge_2B.BAB": "Interactive BAB — rejudged by 2B",
        "interactive.older_pydantic_0.8B.ABA": "Interactive ABA — older Pydantic",
        "interactive.legacy_0.8B.ABA": "Interactive ABA — legacy",
    }
    return replacements.get(condition_id, condition_id.replace(".", " — "))


def build_condition_catalog(rows: Sequence[Mapping[str, Any]]) -> Table:
    grouped: Dict[str, List[Mapping[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[str(row.get("condition_id"))].append(row)

    catalog: Table = []
    for condition_id, condition_rows in sorted(grouped.items()):
        source_files = sorted({str(row.get("source_file")) for row in condition_rows})
        prediction_paths = sorted({str(row.get("prediction_path")) for row in condition_rows})
        exact_keys = {make_exact_match_key(row) for row in condition_rows}
        loose_keys = {make_stage_pmid_key(row) for row in condition_rows}
        valid_predictions = sum(
            1 for row in condition_rows if row.get("prediction") in VALID_BINARY_LABELS
        )
        unresolved_counts = Counter(
            str(row.get("prediction"))
            for row in condition_rows
            if row.get("prediction") not in VALID_BINARY_LABELS
        )
        confidence_count = sum(
            1 for row in condition_rows if row.get("confidence_available")
        )
        side_mapping_count = sum(
            1 for row in condition_rows if row.get("side_mapping_available")
        )
        argument_count = sum(
            1 for row in condition_rows if row.get("argument_text_available")
        )

        family = _consistent_catalog_value(condition_rows, "family")
        generation = _consistent_catalog_value(condition_rows, "generation")
        variant = _consistent_catalog_value(condition_rows, "condition_variant")
        limitations: List[str] = []
        if generation in {"legacy", "older_pydantic"}:
            limitations.append(
                "Cross-generation comparisons change multiple implementation factors."
            )
        if variant in {"ABA", "BAB"}:
            limitations.append(
                "The opening speaker is also the closing/two-turn speaker within this order."
            )
        if variant in {"ABA", "BAB"} and generation == "robust_0.8B":
            limitations.append(
                "ABA and BAB transcripts were generated separately; their difference is not a pure order effect."
            )
        if variant == "BAB_swapped_labels":
            limitations.append(
                "Treat as a clean label test only after byte-level content/order verification."
            )
        if side_mapping_count < len(condition_rows) and family in {"statement", "interactive"}:
            limitations.append("Side mapping is unavailable for some records.")
        if len(source_files) > 1:
            limitations.append("Condition pools more than one source file; verify provenance/chunking.")

        catalog.append(
            {
                "condition_id": condition_id,
                "display_name": _condition_display_name(condition_id),
                "family": family,
                "generation": generation,
                "variant": variant,
                "source_files": source_files,
                "prediction_paths": prediction_paths,
                "row_count": len(condition_rows),
                "unique_stage_pmid_count": len(loose_keys),
                "unique_exact_key_count": len(exact_keys),
                "valid_prediction_count": valid_predictions,
                "valid_prediction_rate": valid_predictions / len(condition_rows) if condition_rows else None,
                "unknown_prediction_count": unresolved_counts.get("Unknown", 0),
                "missing_prediction_count": unresolved_counts.get("Missing", 0),
                "invalid_prediction_count": unresolved_counts.get("Invalid", 0),
                "judge_model": _consistent_catalog_value(condition_rows, "judge_model"),
                "debater_model": _consistent_catalog_value(condition_rows, "debater_model"),
                "manual_in_judge_prompt": _consistent_catalog_value(
                    condition_rows, "manual_in_judge_prompt"
                ),
                "assigned_tags_in_judge_prompt": _consistent_catalog_value(
                    condition_rows, "assigned_tags_in_judge_prompt"
                ),
                "assigned_tags_in_debater_prompt": _consistent_catalog_value(
                    condition_rows, "assigned_tags_in_debater_prompt"
                ),
                "parser_type": _consistent_catalog_value(condition_rows, "parser_type"),
                "fallback_behavior": _consistent_catalog_value(
                    condition_rows, "fallback_behavior"
                ),
                "confidence_available": confidence_count > 0,
                "confidence_coverage": confidence_count / len(condition_rows) if condition_rows else None,
                "fallback_field_available": any(
                    row.get("needed_fallback") is not None for row in condition_rows
                ),
                "side_mapping_coverage": side_mapping_count / len(condition_rows) if condition_rows else None,
                "argument_text_coverage": argument_count / len(condition_rows) if condition_rows else None,
                "provenance_status": _consistent_catalog_value(
                    condition_rows, "provenance_status"
                ),
                "limitations": _unique_preserving_order(limitations),
            }
        )

    return catalog


# =============================================================================
# =============================================================================
# 5. Integrity checks after normalization
# =============================================================================


def _rows_grouped_by_condition(
    rows: Sequence[Mapping[str, Any]],
) -> Dict[str, List[Mapping[str, Any]]]:
    grouped: Dict[str, List[Mapping[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[str(row.get("condition_id") or "<missing condition>")].append(row)
    return grouped


def _key_as_record(key: Tuple[Any, ...]) -> JSONDict:
    names = ("stage", "pmid", "candidate_tag_normalized", "ground_truth")
    return {
        names[index] if index < len(names) else f"field_{index}": value
        for index, value in enumerate(key)
    }


def _build_key_index(
    rows: Sequence[Mapping[str, Any]],
    key_function: Any,
) -> Dict[Tuple[Any, ...], List[Mapping[str, Any]]]:
    index: Dict[Tuple[Any, ...], List[Mapping[str, Any]]] = defaultdict(list)
    for row in rows:
        raw_key = key_function(row)
        key = raw_key if isinstance(raw_key, tuple) else (raw_key,)
        index[key].append(row)
    return dict(index)


def _pair_exact_unique_rows(
    left_rows: Sequence[Mapping[str, Any]],
    right_rows: Sequence[Mapping[str, Any]],
) -> JSONDict:
    left_index = _build_key_index(left_rows, make_exact_match_key)
    right_index = _build_key_index(right_rows, make_exact_match_key)
    shared_keys = sorted(
        set(left_index).intersection(right_index),
        key=lambda value: repr(value),
    )
    pairs: List[Tuple[Mapping[str, Any], Mapping[str, Any]]] = []
    ambiguous_keys: List[Tuple[Any, ...]] = []
    for key in shared_keys:
        if len(left_index[key]) == 1 and len(right_index[key]) == 1:
            pairs.append((left_index[key][0], right_index[key][0]))
        else:
            ambiguous_keys.append(key)

    left_duplicate_keys = [key for key, values in left_index.items() if len(values) > 1]
    right_duplicate_keys = [key for key, values in right_index.items() if len(values) > 1]
    return {
        "pairs": pairs,
        "pair_count": len(pairs),
        "shared_exact_key_count": len(shared_keys),
        "ambiguous_shared_key_count": len(ambiguous_keys),
        "ambiguous_shared_keys": [_key_as_record(key) for key in ambiguous_keys[:20]],
        "left_duplicate_key_count": len(left_duplicate_keys),
        "right_duplicate_key_count": len(right_duplicate_keys),
        "left_unmatched_unique_key_count": len(set(left_index).difference(right_index)),
        "right_unmatched_unique_key_count": len(set(right_index).difference(left_index)),
    }


def _rows_for_condition(
    rows: Sequence[Mapping[str, Any]], condition_id: str
) -> List[Mapping[str, Any]]:
    return [row for row in rows if row.get("condition_id") == condition_id]


def _content_verification_summary(
    comparison_id: str,
    left_condition: str,
    right_condition: str,
    paired: Mapping[str, Any],
    verification_rows: Sequence[Mapping[str, Any]],
) -> JSONDict:
    verified = [row for row in verification_rows if row.get("content_verified") is True]
    mismatched = [row for row in verification_rows if row.get("content_verified") is False]
    unavailable = [row for row in verification_rows if row.get("content_verified") is None]
    pair_count = int(paired.get("pair_count", 0))
    if pair_count == 0:
        status = "unavailable"
    elif len(verified) == pair_count:
        status = "controlled"
    elif verified:
        status = "partially_controlled"
    else:
        status = "not_controlled"

    mismatch_counts: Counter[str] = Counter()
    for row in verification_rows:
        for field in row.get("mismatched_fields", []):
            mismatch_counts[str(field)] += 1

    return {
        "check": comparison_id,
        "left_condition": left_condition,
        "right_condition": right_condition,
        "comparison_status": status,
        "exact_pair_count": pair_count,
        "content_verified_pair_count": len(verified),
        "content_mismatch_pair_count": len(mismatched),
        "content_unavailable_pair_count": len(unavailable),
        "content_verified_rate": safe_divide(len(verified), pair_count),
        "mismatch_counts": dict(sorted(mismatch_counts.items())),
        "verified_exact_keys": [row["exact_key"] for row in verified],
        "mismatch_examples": mismatched[:20],
        "unavailable_examples": unavailable[:20],
        "pairing": {
            key: value
            for key, value in paired.items()
            if key != "pairs"
        },
    }


def validate_condition_keys(rows: Sequence[Mapping[str, Any]]) -> Table:
    findings: Table = []
    for condition_id, condition_rows in sorted(_rows_grouped_by_condition(rows).items()):
        loose_counter = Counter(make_stage_pmid_key(row) for row in condition_rows)
        exact_counter = Counter(make_exact_match_key(row) for row in condition_rows)
        duplicate_loose = {key: count for key, count in loose_counter.items() if count > 1}
        duplicate_exact = {key: count for key, count in exact_counter.items() if count > 1}

        missing_stage = sum(row.get("stage") is None for row in condition_rows)
        missing_pmid = sum(row.get("pmid") is None for row in condition_rows)
        missing_candidate = sum(
            row.get("candidate_tag_normalized") is None for row in condition_rows
        )
        missing_truth = sum(
            row.get("ground_truth") not in VALID_BINARY_LABELS for row in condition_rows
        )

        stage_unique_counts: Dict[str, int] = {}
        for stage in EXPECTED_STAGE_COUNTS:
            stage_unique_counts[stage] = len(
                {
                    make_stage_pmid_key(row)
                    for row in condition_rows
                    if row.get("stage") == stage and row.get("pmid") is not None
                }
            )
        unexpected_stages = Counter(
            str(row.get("stage"))
            for row in condition_rows
            if row.get("stage") not in EXPECTED_STAGE_COUNTS
        )
        missing_expected = {
            stage: max(0, expected - stage_unique_counts.get(stage, 0))
            for stage, expected in EXPECTED_STAGE_COUNTS.items()
        }
        excess_expected = {
            stage: max(0, stage_unique_counts.get(stage, 0) - expected)
            for stage, expected in EXPECTED_STAGE_COUNTS.items()
        }

        key_fields_complete = not any(
            (missing_stage, missing_pmid, missing_candidate, missing_truth)
        )
        complete = (
            len(loose_counter) == EXPECTED_TOTAL_RECORDS
            and all(value == 0 for value in missing_expected.values())
            and not unexpected_stages
        )
        no_duplicates = not duplicate_loose and not duplicate_exact
        if not key_fields_complete or duplicate_exact:
            severity = "error"
        elif not complete or duplicate_loose:
            severity = "warning"
        else:
            severity = "info"

        findings.append(
            {
                "check": "condition_keys",
                "severity": severity,
                "condition_id": condition_id,
                "row_count": len(condition_rows),
                "unique_stage_pmid_count": len(loose_counter),
                "unique_exact_key_count": len(exact_counter),
                "duplicate_stage_pmid_key_count": len(duplicate_loose),
                "duplicate_stage_pmid_excess_rows": sum(
                    count - 1 for count in duplicate_loose.values()
                ),
                "duplicate_exact_key_count": len(duplicate_exact),
                "duplicate_exact_key_excess_rows": sum(
                    count - 1 for count in duplicate_exact.values()
                ),
                "duplicate_stage_pmid_examples": [
                    {**_key_as_record(key), "count": count}
                    for key, count in sorted(duplicate_loose.items(), key=lambda item: repr(item[0]))[:20]
                ],
                "duplicate_exact_key_examples": [
                    {**_key_as_record(key), "count": count}
                    for key, count in sorted(duplicate_exact.items(), key=lambda item: repr(item[0]))[:20]
                ],
                "missing_stage_count": missing_stage,
                "missing_pmid_count": missing_pmid,
                "missing_candidate_count": missing_candidate,
                "missing_or_invalid_truth_count": missing_truth,
                "stage_unique_counts": stage_unique_counts,
                "missing_expected_stage_records": missing_expected,
                "excess_expected_stage_records": excess_expected,
                "unexpected_stage_counts": dict(sorted(unexpected_stages.items())),
                "key_fields_complete": key_fields_complete,
                "record_complete": complete,
                "duplicates_absent": no_duplicates,
                "eligible_for_unambiguous_pairing": key_fields_complete and not duplicate_exact,
            }
        )
    return findings


def validate_ground_truth_consistency(rows: Sequence[Mapping[str, Any]]) -> Table:
    findings: Table = []
    grouped = _rows_grouped_by_condition(rows)
    for condition_id, condition_rows in sorted(grouped.items()):
        invalid_truth = [
            row for row in condition_rows if row.get("ground_truth") not in VALID_BINARY_LABELS
        ]
        stage_conflicts = [
            row for row in condition_rows if row.get("ground_truth_stage_conflict") is True
        ]
        inferred_truth = [
            row for row in condition_rows if row.get("ground_truth_source") == "stage_inferred"
        ]
        findings.append(
            {
                "check": "ground_truth_within_condition",
                "severity": "error" if invalid_truth or stage_conflicts else "info",
                "condition_id": condition_id,
                "row_count": len(condition_rows),
                "invalid_truth_count": len(invalid_truth),
                "stage_truth_conflict_count": len(stage_conflicts),
                "stage_inferred_truth_count": len(inferred_truth),
                "conflict_examples": [
                    {
                        "stage": row.get("stage"),
                        "pmid": row.get("pmid"),
                        "candidate_tag": row.get("candidate_tag"),
                        "stored_truth": row.get("ground_truth_stored"),
                        "expected_truth": row.get("ground_truth_stage_expected"),
                    }
                    for row in stage_conflicts[:20]
                ],
            }
        )

    by_candidate: Dict[Tuple[Any, Any, Any], List[Mapping[str, Any]]] = defaultdict(list)
    for row in rows:
        key = (
            row.get("stage"),
            row.get("pmid"),
            row.get("candidate_tag_normalized"),
        )
        if all(value is not None for value in key):
            by_candidate[key].append(row)

    conflicts: List[JSONDict] = []
    for key, matching_rows in by_candidate.items():
        truths = sorted(
            {
                str(row.get("ground_truth"))
                for row in matching_rows
                if row.get("ground_truth") is not None
            }
        )
        if len(truths) > 1:
            conflicts.append(
                {
                    "stage": key[0],
                    "pmid": key[1],
                    "candidate_tag_normalized": key[2],
                    "truths": truths,
                    "conditions": sorted(
                        {str(row.get("condition_id")) for row in matching_rows}
                    ),
                }
            )

    findings.append(
        {
            "check": "ground_truth_across_conditions",
            "severity": "error" if conflicts else "info",
            "condition_id": None,
            "candidate_keys_compared": len(by_candidate),
            "conflicting_candidate_key_count": len(conflicts),
            "conflict_examples": conflicts[:50],
        }
    )
    return findings


def validate_candidate_consistency(rows: Sequence[Mapping[str, Any]]) -> Table:
    grouped = _rows_grouped_by_condition(rows)
    condition_ids = sorted(grouped)
    comparisons: Table = []

    for left_index_position, left_condition in enumerate(condition_ids):
        left_rows = grouped[left_condition]
        left_index = _build_key_index(left_rows, make_stage_pmid_key)
        for right_condition in condition_ids[left_index_position + 1 :]:
            right_rows = grouped[right_condition]
            right_index = _build_key_index(right_rows, make_stage_pmid_key)
            overlap = sorted(
                set(left_index).intersection(right_index), key=lambda value: repr(value)
            )

            candidate_matches = 0
            truth_matches = 0
            exact_matches = 0
            candidate_mismatches = 0
            truth_mismatches = 0
            missing_candidates = 0
            ambiguous = 0
            positive_candidate_mismatches = 0
            mismatch_examples: List[JSONDict] = []
            exact_by_stage: Counter[str] = Counter()
            loose_by_stage: Counter[str] = Counter()

            for key in overlap:
                stage = str(key[0])
                loose_by_stage[stage] += 1
                left_values = left_index[key]
                right_values = right_index[key]
                if len(left_values) != 1 or len(right_values) != 1:
                    ambiguous += 1
                    continue
                left_row = left_values[0]
                right_row = right_values[0]
                left_candidate = left_row.get("candidate_tag_normalized")
                right_candidate = right_row.get("candidate_tag_normalized")
                if left_candidate is None or right_candidate is None:
                    missing_candidates += 1
                    candidate_same = False
                else:
                    candidate_same = left_candidate == right_candidate
                truth_same = left_row.get("ground_truth") == right_row.get("ground_truth")
                candidate_matches += int(candidate_same)
                truth_matches += int(truth_same)
                candidate_mismatches += int(not candidate_same)
                truth_mismatches += int(not truth_same)
                if not candidate_same and key[0] == "Round 1: True Tag":
                    positive_candidate_mismatches += 1
                if candidate_same and truth_same:
                    exact_matches += 1
                    exact_by_stage[stage] += 1
                elif len(mismatch_examples) < 20:
                    mismatch_examples.append(
                        {
                            "stage": key[0],
                            "pmid": key[1],
                            "left_candidate": left_row.get("candidate_tag"),
                            "right_candidate": right_row.get("candidate_tag"),
                            "left_truth": left_row.get("ground_truth"),
                            "right_truth": right_row.get("ground_truth"),
                        }
                    )

            unambiguous_overlap = len(overlap) - ambiguous
            comparisons.append(
                {
                    "check": "candidate_consistency",
                    "severity": "error" if truth_mismatches else "info",
                    "left_condition": left_condition,
                    "right_condition": right_condition,
                    "left_row_count": len(left_rows),
                    "right_row_count": len(right_rows),
                    "loose_overlap_count": len(overlap),
                    "unambiguous_loose_overlap_count": unambiguous_overlap,
                    "ambiguous_loose_key_count": ambiguous,
                    "candidate_match_count": candidate_matches,
                    "candidate_mismatch_count": candidate_mismatches,
                    "positive_stage_candidate_mismatch_count": positive_candidate_mismatches,
                    "missing_candidate_count": missing_candidates,
                    "truth_match_count": truth_matches,
                    "truth_mismatch_count": truth_mismatches,
                    "exact_pairing_eligible_count": exact_matches,
                    "exact_match_rate_within_unambiguous_overlap": safe_divide(
                        exact_matches, unambiguous_overlap
                    ),
                    "loose_overlap_by_stage": dict(sorted(loose_by_stage.items())),
                    "exact_overlap_by_stage": dict(sorted(exact_by_stage.items())),
                    "left_unmatched_loose_key_count": len(
                        set(left_index).difference(right_index)
                    ),
                    "right_unmatched_loose_key_count": len(
                        set(right_index).difference(left_index)
                    ),
                    "mismatch_examples": mismatch_examples,
                    "pairing_rule": (
                        "Paired analyses may use only unambiguous rows matching stage, "
                        "PMID, normalized candidate tag, and ground truth."
                    ),
                }
            )
    return comparisons


def verify_rejudge_statement_content(rows: Sequence[Mapping[str, Any]]) -> Table:
    left_condition = "statement.robust_0.8B"
    right_condition = "statement.rejudge_2B"
    paired = _pair_exact_unique_rows(
        _rows_for_condition(rows, left_condition),
        _rows_for_condition(rows, right_condition),
    )
    checks: Table = []
    required_text_fields = (
        "abstract",
        "arg_a",
        "arg_b",
        "pro_argument",
        "con_argument",
    )
    comparison_fields = required_text_fields + (
        "candidate_tag",
        "displayed_a_side",
        "displayed_b_side",
        "pro_is_displayed_a",
    )
    for left, right in paired["pairs"]:
        unavailable = [
            field
            for field in required_text_fields
            if left.get(field) is None or right.get(field) is None
        ]
        mismatched = [
            field for field in comparison_fields if left.get(field) != right.get(field)
        ]
        verified: Optional[bool]
        if unavailable:
            verified = None
        else:
            verified = not mismatched
        checks.append(
            {
                "exact_key": _key_as_record(make_exact_match_key(left)),
                "content_verified": verified,
                "unavailable_fields": unavailable,
                "mismatched_fields": mismatched,
                "left_source_file": left.get("source_file"),
                "right_source_file": right.get("source_file"),
            }
        )
    return [
        _content_verification_summary(
            "statement_rejudge_fixed_essays",
            left_condition,
            right_condition,
            paired,
            checks,
        )
    ]


def verify_rejudge_interactive_content(rows: Sequence[Mapping[str, Any]]) -> Table:
    summaries: Table = []
    for variant in ("ABA", "BAB"):
        left_condition = f"interactive.robust_0.8B.{variant}"
        right_condition = f"interactive.rejudge_2B.{variant}"
        paired = _pair_exact_unique_rows(
            _rows_for_condition(rows, left_condition),
            _rows_for_condition(rows, right_condition),
        )
        checks: Table = []
        for left, right in paired["pairs"]:
            left_turns = left.get("ordered_turns") or []
            right_turns = right.get("ordered_turns") or []
            unavailable = []
            if left.get("abstract") is None or right.get("abstract") is None:
                unavailable.append("abstract")
            if not left_turns or not right_turns:
                unavailable.append("ordered_turns")
            mismatched: List[str] = []
            for field in (
                "candidate_tag",
                "abstract",
                "displayed_a_side",
                "displayed_b_side",
                "speaker_sequence",
            ):
                if left.get(field) != right.get(field):
                    mismatched.append(field)
            if left_turns != right_turns:
                mismatched.append("ordered_turns")
            verified = None if unavailable else not mismatched
            checks.append(
                {
                    "exact_key": _key_as_record(make_exact_match_key(left)),
                    "content_verified": verified,
                    "unavailable_fields": unavailable,
                    "mismatched_fields": mismatched,
                    "left_source_file": left.get("source_file"),
                    "right_source_file": right.get("source_file"),
                }
            )
        summaries.append(
            _content_verification_summary(
                f"interactive_{variant.lower()}_rejudge_fixed_transcript",
                left_condition,
                right_condition,
                paired,
                checks,
            )
        )
    return summaries


def verify_swapped_bab_content(rows: Sequence[Mapping[str, Any]]) -> Table:
    left_condition = "interactive.robust_0.8B.BAB"
    right_condition = "interactive.robust_0.8B.BAB_swapped_labels"
    paired = _pair_exact_unique_rows(
        _rows_for_condition(rows, left_condition),
        _rows_for_condition(rows, right_condition),
    )
    checks: Table = []
    for original, swapped in paired["pairs"]:
        original_turns = original.get("ordered_turns") or []
        swapped_turns = swapped.get("ordered_turns") or []
        original_texts = [turn.get("text") for turn in original_turns]
        swapped_texts = [turn.get("text") for turn in swapped_turns]
        original_labels = [turn.get("label") for turn in original_turns]
        swapped_labels = [turn.get("label") for turn in swapped_turns]
        original_sides = [turn.get("side") for turn in original_turns]
        swapped_sides = [turn.get("side") for turn in swapped_turns]

        unavailable: List[str] = []
        if not original_turns or not swapped_turns:
            unavailable.append("ordered_turns")
        if original.get("abstract") is None or swapped.get("abstract") is None:
            unavailable.append("abstract")

        mismatched: List[str] = []
        if original.get("candidate_tag") != swapped.get("candidate_tag"):
            mismatched.append("candidate_tag")
        if original.get("abstract") != swapped.get("abstract"):
            mismatched.append("abstract")
        if original_texts != swapped_texts:
            mismatched.append("physical_turn_texts")
        if original_sides != swapped_sides:
            mismatched.append("physical_turn_sides")
        if original_labels != ["B", "A", "B"]:
            mismatched.append("original_BAB_labels")
        if swapped_labels != ["A", "B", "A"]:
            mismatched.append("swapped_ABA_display_labels")
        if original.get("displayed_a_side") != swapped.get("displayed_b_side"):
            mismatched.append("A_to_B_side_mapping")
        if original.get("displayed_b_side") != swapped.get("displayed_a_side"):
            mismatched.append("B_to_A_side_mapping")

        verified = None if unavailable else not mismatched
        checks.append(
            {
                "exact_key": _key_as_record(make_exact_match_key(original)),
                "content_verified": verified,
                "unavailable_fields": unavailable,
                "mismatched_fields": mismatched,
                "original_labels": original_labels,
                "swapped_labels": swapped_labels,
                "left_source_file": original.get("source_file"),
                "right_source_file": swapped.get("source_file"),
            }
        )

    summary = _content_verification_summary(
        "bab_swapped_labels_fixed_physical_content",
        left_condition,
        right_condition,
        paired,
        checks,
    )
    summary["clean_label_test"] = summary["comparison_status"] == "controlled"
    summary["verification_rule"] = (
        "Candidate, abstract, physical turn text, and physical side order must be "
        "identical; displayed A/B names and side mappings must be exchanged."
    )
    return [summary]


def validate_pydantic_interactive_subgroups(rows: Sequence[Mapping[str, Any]]) -> Table:
    condition_id = "interactive.older_pydantic_0.8B.ABA"
    condition_rows = _rows_for_condition(rows, condition_id)
    if not condition_rows:
        return [
            {
                "check": "pydantic_interactive_subgroups",
                "severity": "info",
                "condition_id": condition_id,
                "status": "unavailable",
                "row_count": 0,
                "warning": (
                    "The older Pydantic interactive result file is not available as a "
                    "normalized condition."
                ),
            }
        ]

    grouped: Dict[str, List[Mapping[str, Any]]] = {
        "A_is_PRO": [],
        "A_is_CON": [],
        "side_mapping_unknown": [],
    }
    for row in condition_rows:
        value = row.get("pro_is_displayed_a")
        if value is True:
            grouped["A_is_PRO"].append(row)
        elif value is False:
            grouped["A_is_CON"].append(row)
        else:
            grouped["side_mapping_unknown"].append(row)

    output: Table = []
    for subgroup, subgroup_rows in grouped.items():
        metrics = compute_accuracy_metrics(subgroup_rows)
        output.append(
            {
                "check": "pydantic_interactive_subgroups",
                "severity": "warning" if subgroup == "side_mapping_unknown" and subgroup_rows else "info",
                "condition_id": condition_id,
                "status": "available",
                "subgroup": subgroup,
                "row_count": len(subgroup_rows),
                "coverage": safe_divide(len(subgroup_rows), len(condition_rows)),
                "strict_accuracy": metrics.get("strict_accuracy"),
                "valid_only_accuracy": metrics.get("valid_only_accuracy"),
                "balanced_accuracy": metrics.get("balanced_accuracy"),
                "yes_prediction_rate": metrics.get("yes_prediction_rate"),
                "unknown_prediction_count": metrics.get("unknown_prediction_count"),
                "warning": (
                    "Differences between A-is-PRO and A-is-CON may reflect the known "
                    "older transcript-label construction issue; they are not a clean "
                    "first-speaker or side effect."
                ),
            }
        )
    return output


def run_integrity_checks(
    rows: Sequence[Mapping[str, Any]],
    inventory: Sequence[Mapping[str, Any]],
) -> JSONDict:
    condition_keys = validate_condition_keys(rows)
    ground_truth = validate_ground_truth_consistency(rows)
    candidate_consistency = validate_candidate_consistency(rows)
    statement_content = verify_rejudge_statement_content(rows)
    interactive_content = verify_rejudge_interactive_content(rows)
    swapped_content = verify_swapped_bab_content(rows)
    pydantic_subgroups = validate_pydantic_interactive_subgroups(rows)
    known_expectations = validate_known_audit_expectations(inventory)
    duplicate_groups = detect_normalized_duplicate_files(inventory)

    findings: Table = []
    findings.extend(condition_keys)
    findings.extend(ground_truth)
    findings.extend(known_expectations)

    for row in inventory:
        for issue in row.get("audit_issues", []) or []:
            findings.append(
                {
                    "check": "physical_file_audit",
                    "severity": "error" if row.get("load_status") != "loaded" else "warning",
                    "filename": row.get("filename"),
                    "message": issue,
                }
            )

    for group in duplicate_groups:
        status = group.get("status")
        findings.append(
            {
                "check": "normalized_duplicate_files",
                "severity": "error" if status == "known_swapped_pair_mismatch" else "info",
                "filename": None,
                "status": status,
                "filenames": group.get("filenames"),
                "canonical_filename": group.get("canonical_filename"),
                "message": (
                    "Normalized duplicate result arrays are represented by one canonical file."
                    if group.get("is_duplicate_group")
                    else "A documented duplicate pair no longer matches."
                ),
            }
        )

    content_checks = statement_content + interactive_content + swapped_content
    for check in content_checks:
        status = check.get("comparison_status")
        findings.append(
            {
                "check": check.get("check"),
                "severity": (
                    "info" if status in {"controlled", "unavailable"} else "warning"
                ),
                "left_condition": check.get("left_condition"),
                "right_condition": check.get("right_condition"),
                "comparison_status": status,
                "exact_pair_count": check.get("exact_pair_count"),
                "content_verified_pair_count": check.get("content_verified_pair_count"),
                "content_mismatch_pair_count": check.get("content_mismatch_pair_count"),
            }
        )

    severity_counts = Counter(str(item.get("severity", "info")) for item in findings)
    controlled_comparisons = {
        str(item.get("check")): {
            "status": item.get("comparison_status"),
            "verified_exact_keys": item.get("verified_exact_keys", []),
            "verified_pair_count": item.get("content_verified_pair_count", 0),
        }
        for item in content_checks
    }

    return {
        "condition_keys": condition_keys,
        "ground_truth": ground_truth,
        "candidate_consistency": candidate_consistency,
        "statement_rejudge_content": statement_content,
        "interactive_rejudge_content": interactive_content,
        "swapped_bab_content": swapped_content,
        "pydantic_interactive_subgroups": pydantic_subgroups,
        "known_audit_expectations": known_expectations,
        "normalized_duplicate_groups": duplicate_groups,
        "controlled_comparisons": controlled_comparisons,
        "findings": findings,
        "severity_counts": dict(sorted(severity_counts.items())),
        "has_errors": severity_counts.get("error", 0) > 0,
        "has_warnings": severity_counts.get("warning", 0) > 0,
        "note": (
            "Candidate mismatches are documented rather than treated as integrity "
            "errors; paired analyses must use only unambiguous exact candidate matches."
        ),
    }


# =============================================================================
# 6. Core condition metrics
# =============================================================================


def _wilson_interval(
    successes: int,
    total: int,
    z: float = 1.959963984540054,
) -> Optional[Tuple[float, float]]:
    if total <= 0:
        return None
    proportion = successes / total
    z_squared = z * z
    denominator = 1.0 + z_squared / total
    center = (proportion + z_squared / (2.0 * total)) / denominator
    margin = (
        z
        * (
            (proportion * (1.0 - proportion) / total)
            + (z_squared / (4.0 * total * total))
        )
        ** 0.5
        / denominator
    )
    return max(0.0, center - margin), min(1.0, center + margin)


def _difference_in_independent_proportions(
    left_successes: int,
    left_total: int,
    right_successes: int,
    right_total: int,
    z: float = 1.959963984540054,
) -> JSONDict:
    left = safe_divide(left_successes, left_total)
    right = safe_divide(right_successes, right_total)
    if left is None or right is None:
        return {"difference": None, "confidence_interval_95": None}
    difference = left - right
    standard_error = (
        left * (1.0 - left) / left_total
        + right * (1.0 - right) / right_total
    ) ** 0.5
    return {
        "difference": difference,
        "confidence_interval_95": (
            difference - z * standard_error,
            difference + z * standard_error,
        ),
    }


def safe_divide(numerator: float, denominator: float) -> Optional[float]:
    if denominator == 0:
        return None
    return numerator / denominator


def compute_confusion_counts(rows: Sequence[Mapping[str, Any]]) -> JSONDict:
    counts: Counter[str] = Counter()
    for row in rows:
        truth = row.get("ground_truth")
        prediction = row.get("prediction")
        if prediction not in {"Yes", "No", "Unknown", "Missing", "Invalid"}:
            prediction = normalize_label(prediction)

        counts["total"] += 1
        if truth == "Yes":
            counts["truth_yes"] += 1
        elif truth == "No":
            counts["truth_no"] += 1
        else:
            counts["invalid_truth"] += 1

        if prediction == "Yes":
            counts["prediction_yes"] += 1
        elif prediction == "No":
            counts["prediction_no"] += 1
        elif prediction == "Unknown":
            counts["prediction_unknown"] += 1
        elif prediction == "Missing":
            counts["prediction_missing"] += 1
        else:
            counts["prediction_invalid"] += 1

        if truth not in VALID_BINARY_LABELS:
            if prediction in VALID_BINARY_LABELS:
                counts["binary_prediction_with_invalid_truth"] += 1
            continue

        if prediction == "Yes" and truth == "Yes":
            counts["tp"] += 1
        elif prediction == "No" and truth == "No":
            counts["tn"] += 1
        elif prediction == "Yes" and truth == "No":
            counts["fp"] += 1
        elif prediction == "No" and truth == "Yes":
            counts["fn"] += 1
        else:
            counts["unresolved_with_valid_truth"] += 1
            if truth == "Yes":
                counts["unresolved_truth_yes"] += 1
            else:
                counts["unresolved_truth_no"] += 1

    tp = counts["tp"]
    tn = counts["tn"]
    fp = counts["fp"]
    fn = counts["fn"]
    counts["binary_evaluable"] = tp + tn + fp + fn
    counts["binary_correct"] = tp + tn
    counts["binary_incorrect"] = fp + fn
    counts["unresolved_prediction"] = (
        counts["prediction_unknown"]
        + counts["prediction_missing"]
        + counts["prediction_invalid"]
    )
    return dict(counts)


def compute_accuracy_metrics(rows: Sequence[Mapping[str, Any]]) -> JSONDict:
    counts = compute_confusion_counts(rows)
    total = counts.get("total", 0)
    tp = counts.get("tp", 0)
    tn = counts.get("tn", 0)
    fp = counts.get("fp", 0)
    fn = counts.get("fn", 0)
    correct = counts.get("binary_correct", 0)
    evaluable = counts.get("binary_evaluable", 0)
    truth_yes = counts.get("truth_yes", 0)
    truth_no = counts.get("truth_no", 0)
    prediction_yes = counts.get("prediction_yes", 0)
    prediction_no = counts.get("prediction_no", 0)
    valid_predictions = prediction_yes + prediction_no

    valid_sensitivity = safe_divide(tp, tp + fn)
    valid_specificity = safe_divide(tn, tn + fp)
    strict_sensitivity = safe_divide(tp, truth_yes)
    strict_specificity = safe_divide(tn, truth_no)
    valid_balanced = (
        (valid_sensitivity + valid_specificity) / 2.0
        if valid_sensitivity is not None and valid_specificity is not None
        else None
    )
    strict_balanced = (
        (strict_sensitivity + strict_specificity) / 2.0
        if strict_sensitivity is not None and strict_specificity is not None
        else None
    )
    precision = safe_divide(tp, tp + fp)
    negative_predictive_value = safe_divide(tn, tn + fn)
    recall = valid_sensitivity
    f1 = (
        2.0 * precision * recall / (precision + recall)
        if precision is not None and recall is not None and precision + recall > 0
        else None
    )
    strict_accuracy = safe_divide(correct, total)
    valid_only_accuracy = safe_divide(correct, evaluable)
    always_no_accuracy = safe_divide(truth_no, total)
    always_yes_accuracy = safe_divide(truth_yes, total)
    majority_count = max(truth_yes, truth_no)
    majority_label = "No" if truth_no >= truth_yes else "Yes"

    return {
        **counts,
        "valid_prediction_count": valid_predictions,
        "valid_binary_evaluable_count": evaluable,
        "valid_prediction_coverage": safe_divide(valid_predictions, total),
        "binary_evaluable_coverage": safe_divide(evaluable, total),
        "unknown_prediction_count": counts.get("prediction_unknown", 0),
        "unknown_prediction_rate": safe_divide(counts.get("prediction_unknown", 0), total),
        "missing_prediction_count": counts.get("prediction_missing", 0),
        "missing_prediction_rate": safe_divide(counts.get("prediction_missing", 0), total),
        "invalid_prediction_count": counts.get("prediction_invalid", 0),
        "invalid_prediction_rate": safe_divide(counts.get("prediction_invalid", 0), total),
        "strict_accuracy": strict_accuracy,
        "strict_accuracy_confidence_interval_95": _wilson_interval(correct, total),
        "valid_only_accuracy": valid_only_accuracy,
        "valid_only_accuracy_confidence_interval_95": _wilson_interval(correct, evaluable),
        "balanced_accuracy": strict_balanced,
        "valid_only_balanced_accuracy": valid_balanced,
        "sensitivity": valid_sensitivity,
        "specificity": valid_specificity,
        "strict_sensitivity": strict_sensitivity,
        "strict_specificity": strict_specificity,
        "precision_yes": precision,
        "negative_predictive_value": negative_predictive_value,
        "f1_yes": f1,
        "false_positive_rate": safe_divide(fp, fp + tn),
        "false_negative_rate": safe_divide(fn, fn + tp),
        "strict_false_positive_or_unresolved_rate": (
            None if truth_no == 0 else 1.0 - (tn / truth_no)
        ),
        "strict_false_negative_or_unresolved_rate": (
            None if truth_yes == 0 else 1.0 - (tp / truth_yes)
        ),
        "yes_prediction_rate": safe_divide(prediction_yes, total),
        "no_prediction_rate": safe_divide(prediction_no, total),
        "yes_rate_among_valid_predictions": safe_divide(
            prediction_yes, valid_predictions
        ),
        "no_rate_among_valid_predictions": safe_divide(
            prediction_no, valid_predictions
        ),
        "always_no_accuracy": always_no_accuracy,
        "always_yes_accuracy": always_yes_accuracy,
        "majority_class_label": majority_label,
        "majority_class_accuracy": safe_divide(majority_count, total),
        "accuracy_minus_always_no": (
            strict_accuracy - always_no_accuracy
            if strict_accuracy is not None and always_no_accuracy is not None
            else None
        ),
        "balanced_accuracy_minus_chance": (
            strict_balanced - 0.5 if strict_balanced is not None else None
        ),
        "beats_always_no_strictly": (
            strict_accuracy > always_no_accuracy
            if strict_accuracy is not None and always_no_accuracy is not None
            else None
        ),
        "unknown_handling": (
            "Strict accuracy and balanced accuracy count unresolved predictions as "
            "failures; valid-only metrics exclude them."
        ),
    }


def compute_stage_metrics(rows: Sequence[Mapping[str, Any]]) -> Table:
    grouped: Dict[str, List[Mapping[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[str(row.get("stage"))].append(row)

    ordered_stages = list(EXPECTED_STAGE_COUNTS)
    ordered_stages.extend(
        sorted(stage for stage in grouped if stage not in EXPECTED_STAGE_COUNTS)
    )
    stage_rows: Table = []
    for stage in ordered_stages:
        metrics = compute_accuracy_metrics(grouped.get(stage, []))
        stage_rows.append(
            {
                "stage": stage,
                "expected_record_count": EXPECTED_STAGE_COUNTS.get(stage),
                **metrics,
            }
        )

    by_stage = {row["stage"]: row for row in stage_rows}
    unrelated = by_stage.get("Round 2: Unrelated Tag", {})
    similar = by_stage.get("Round 3: Similar Tag", {})
    strict_gap = None
    valid_gap = None
    balanced_gap = None
    if unrelated.get("strict_accuracy") is not None and similar.get("strict_accuracy") is not None:
        strict_gap = similar["strict_accuracy"] - unrelated["strict_accuracy"]
    if unrelated.get("valid_only_accuracy") is not None and similar.get("valid_only_accuracy") is not None:
        valid_gap = similar["valid_only_accuracy"] - unrelated["valid_only_accuracy"]
    if unrelated.get("balanced_accuracy") is not None and similar.get("balanced_accuracy") is not None:
        balanced_gap = similar["balanced_accuracy"] - unrelated["balanced_accuracy"]

    for row in stage_rows:
        row["similar_minus_unrelated_strict_accuracy"] = strict_gap
        row["similar_minus_unrelated_valid_only_accuracy"] = valid_gap
        row["similar_minus_unrelated_balanced_accuracy"] = balanced_gap
        row["negative_stage_contrast_note"] = (
            "Negative values mean Similar Tag cases were harder than Unrelated Tag cases."
        )
    return stage_rows


def compute_condition_metrics(rows: Sequence[Mapping[str, Any]]) -> Tuple[Table, Table]:
    condition_table: Table = []
    stage_table: Table = []
    for condition_id, condition_rows in sorted(_rows_grouped_by_condition(rows).items()):
        exact_counter = Counter(make_exact_match_key(row) for row in condition_rows)
        duplicate_exact_count = sum(1 for count in exact_counter.values() if count > 1)
        first = condition_rows[0] if condition_rows else {}
        metrics = compute_accuracy_metrics(condition_rows)
        condition_table.append(
            {
                "condition_id": condition_id,
                "display_name": _condition_display_name(condition_id),
                "family": first.get("family"),
                "generation": first.get("generation"),
                "variant": first.get("condition_variant"),
                "source_files": sorted(
                    {str(row.get("source_file")) for row in condition_rows}
                ),
                "judge_model": _consistent_catalog_value(condition_rows, "judge_model"),
                "debater_model": _consistent_catalog_value(condition_rows, "debater_model"),
                "manual_in_judge_prompt": _consistent_catalog_value(
                    condition_rows, "manual_in_judge_prompt"
                ),
                "assigned_tags_in_judge_prompt": _consistent_catalog_value(
                    condition_rows, "assigned_tags_in_judge_prompt"
                ),
                "duplicate_exact_key_count": duplicate_exact_count,
                "metric_status": (
                    "invalid_duplicate_exact_keys"
                    if duplicate_exact_count
                    else "computed"
                ),
                **metrics,
            }
        )
        for stage_metrics in compute_stage_metrics(condition_rows):
            stage_table.append(
                {
                    "condition_id": condition_id,
                    "display_name": _condition_display_name(condition_id),
                    "family": first.get("family"),
                    "generation": first.get("generation"),
                    "variant": first.get("condition_variant"),
                    **stage_metrics,
                }
            )
    return condition_table, stage_table


def compute_majority_reference_metrics(rows: Sequence[Mapping[str, Any]]) -> Table:
    references: Table = []
    for condition_id, condition_rows in sorted(_rows_grouped_by_condition(rows).items()):
        truth_yes = sum(row.get("ground_truth") == "Yes" for row in condition_rows)
        truth_no = sum(row.get("ground_truth") == "No" for row in condition_rows)
        total = len(condition_rows)
        both_classes = truth_yes > 0 and truth_no > 0
        for strategy, correct, sensitivity, specificity in (
            ("always_No", truth_no, 0.0 if truth_yes else None, 1.0 if truth_no else None),
            ("always_Yes", truth_yes, 1.0 if truth_yes else None, 0.0 if truth_no else None),
        ):
            balanced = (
                (sensitivity + specificity) / 2.0
                if sensitivity is not None and specificity is not None
                else None
            )
            references.append(
                {
                    "condition_id": condition_id,
                    "strategy": strategy,
                    "total_records": total,
                    "truth_yes_count": truth_yes,
                    "truth_no_count": truth_no,
                    "ordinary_accuracy": safe_divide(correct, total),
                    "balanced_accuracy": balanced,
                    "sensitivity": sensitivity,
                    "specificity": specificity,
                    "both_truth_classes_present": both_classes,
                    "canonical_expected_accuracy": (
                        2.0 / 3.0 if strategy == "always_No" else 1.0 / 3.0
                    ),
                    "canonical_expected_balanced_accuracy": 0.5,
                    "note": (
                        "Observed references are recomputed from this condition's truth "
                        "coverage; canonical values assume 1,000 positive and 2,000 negative cases."
                    ),
                }
            )
    return references


# =============================================================================
# 7. Bias, position, and verbosity analysis
# =============================================================================


def _rate_summary(successes: int, total: int) -> JSONDict:
    return {
        "count": successes,
        "eligible_count": total,
        "rate": safe_divide(successes, total),
        "confidence_interval_95": _wilson_interval(successes, total),
    }


def _mean(values: Sequence[float]) -> Optional[float]:
    return sum(values) / len(values) if values else None


def _median(values: Sequence[float]) -> Optional[float]:
    if not values:
        return None
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return float(ordered[middle])
    return (ordered[middle - 1] + ordered[middle]) / 2.0


def _selected_side_for_row(row: Mapping[str, Any]) -> Optional[str]:
    return prediction_to_selected_side(str(row.get("prediction")))


def _correct_side_for_row(row: Mapping[str, Any]) -> Optional[str]:
    if row.get("ground_truth") == "Yes":
        return "PRO"
    if row.get("ground_truth") == "No":
        return "CON"
    return None


def prediction_to_selected_side(prediction: str) -> Optional[str]:
    normalized = normalize_label(prediction)
    if normalized == "Yes":
        return "PRO"
    if normalized == "No":
        return "CON"
    return None


def selected_displayed_label(row: Mapping[str, Any]) -> Optional[str]:
    selected_side = _selected_side_for_row(row)
    if selected_side is None:
        return None
    displayed_a = row.get("displayed_a_side") or row.get("a_side")
    displayed_b = row.get("displayed_b_side") or row.get("b_side")
    if displayed_a == selected_side:
        return "A"
    if displayed_b == selected_side:
        return "B"
    if selected_side == "PRO":
        label = row.get("pro_displayed_label")
        return label if label in {"A", "B"} else None
    label = row.get("con_displayed_label")
    return label if label in {"A", "B"} else None


def compute_pro_con_bias(rows: Sequence[Mapping[str, Any]]) -> JSONDict:
    valid_rows = [row for row in rows if _selected_side_for_row(row) is not None]
    pro_count = sum(_selected_side_for_row(row) == "PRO" for row in valid_rows)
    con_count = sum(_selected_side_for_row(row) == "CON" for row in valid_rows)
    confusion = compute_confusion_counts(rows)
    fp = confusion.get("fp", 0)
    tn = confusion.get("tn", 0)
    fn = confusion.get("fn", 0)
    tp = confusion.get("tp", 0)
    asymmetry = _difference_in_independent_proportions(fp, fp + tn, fn, fn + tp)

    stage_rows: Table = []
    for stage in list(EXPECTED_STAGE_COUNTS) + sorted(
        {
            str(row.get("stage"))
            for row in rows
            if row.get("stage") not in EXPECTED_STAGE_COUNTS
        }
    ):
        subset = [row for row in rows if row.get("stage") == stage]
        valid_subset = [row for row in subset if _selected_side_for_row(row) is not None]
        subset_pro = sum(_selected_side_for_row(row) == "PRO" for row in valid_subset)
        stage_rows.append(
            {
                "stage": stage,
                "total_records": len(subset),
                "valid_prediction_count": len(valid_subset),
                "pro_selection_count": subset_pro,
                "con_selection_count": len(valid_subset) - subset_pro,
                "pro_selection_rate": safe_divide(subset_pro, len(valid_subset)),
                "pro_selection_confidence_interval_95": _wilson_interval(
                    subset_pro, len(valid_subset)
                ),
            }
        )

    truth_rows: Table = []
    for truth in ("Yes", "No"):
        subset = [row for row in valid_rows if row.get("ground_truth") == truth]
        subset_pro = sum(_selected_side_for_row(row) == "PRO" for row in subset)
        truth_rows.append(
            {
                "ground_truth": truth,
                "eligible_count": len(subset),
                "pro_selection_count": subset_pro,
                "pro_selection_rate": safe_divide(subset_pro, len(subset)),
                "pro_selection_confidence_interval_95": _wilson_interval(
                    subset_pro, len(subset)
                ),
            }
        )

    interval = asymmetry.get("confidence_interval_95")
    difference = asymmetry.get("difference")
    if interval is not None and interval[0] > 0:
        interpretation = "More false-positive/PRO-side errors than false-negative/CON-side errors."
    elif interval is not None and interval[1] < 0:
        interpretation = "More false-negative/CON-side errors than false-positive/PRO-side errors."
    else:
        interpretation = "No clear directional error asymmetry at the descriptive 95% interval level."

    truth_yes_valid = sum(
        row.get("ground_truth") == "Yes" for row in valid_rows
    )
    return {
        "supported": bool(valid_rows),
        "total_records": len(rows),
        "valid_prediction_count": len(valid_rows),
        "pro_selection": _rate_summary(pro_count, len(valid_rows)),
        "con_selection": _rate_summary(con_count, len(valid_rows)),
        "pro_selection_rate_all_records": safe_divide(pro_count, len(rows)),
        "truth_yes_rate_among_valid_predictions": safe_divide(
            truth_yes_valid, len(valid_rows)
        ),
        "pro_selection_minus_truth_yes_prevalence": (
            safe_divide(pro_count, len(valid_rows))
            - safe_divide(truth_yes_valid, len(valid_rows))
            if valid_rows
            else None
        ),
        "false_positive_rate": safe_divide(fp, fp + tn),
        "false_negative_rate": safe_divide(fn, fn + tp),
        "false_positive_minus_false_negative_rate": difference,
        "error_asymmetry_confidence_interval_95": interval,
        "error_asymmetry_interpretation": interpretation,
        "by_stage": stage_rows,
        "by_ground_truth": truth_rows,
        "interpretation_guardrail": (
            "Raw PRO/Yes selection is not sufficient evidence of bias because the "
            "ground-truth distribution is imbalanced; FPR/FNR asymmetry and controlled "
            "position or label interventions are more informative."
        ),
    }


def compute_ab_label_bias(rows: Sequence[Mapping[str, Any]]) -> JSONDict:
    eligible: List[JSONDict] = []
    for row in rows:
        selected = selected_displayed_label(row)
        displayed_a = row.get("displayed_a_side")
        displayed_b = row.get("displayed_b_side")
        if selected is None or displayed_a not in {"PRO", "CON"} or displayed_b not in {"PRO", "CON"}:
            continue
        correct_side = _correct_side_for_row(row)
        correct_label = None
        if correct_side == displayed_a:
            correct_label = "A"
        elif correct_side == displayed_b:
            correct_label = "B"
        eligible.append(
            {
                "row": row,
                "selected_label": selected,
                "correct_label": correct_label,
                "a_side": displayed_a,
            }
        )

    a_count = sum(item["selected_label"] == "A" for item in eligible)
    stratified: Table = []
    for stage in list(EXPECTED_STAGE_COUNTS):
        for a_side in ("PRO", "CON"):
            subset = [
                item
                for item in eligible
                if item["row"].get("stage") == stage and item["a_side"] == a_side
            ]
            selected_a = sum(item["selected_label"] == "A" for item in subset)
            stratified.append(
                {
                    "stage": stage,
                    "displayed_a_side": a_side,
                    "eligible_count": len(subset),
                    "displayed_a_selection_count": selected_a,
                    "displayed_a_selection_rate": safe_divide(selected_a, len(subset)),
                    "confidence_interval_95": _wilson_interval(selected_a, len(subset)),
                }
            )

    accuracy_by_correct_label: Table = []
    counts_for_difference: Dict[str, Tuple[int, int]] = {}
    for correct_label in ("A", "B"):
        subset = [item for item in eligible if item["correct_label"] == correct_label]
        correct = sum(item["selected_label"] == correct_label for item in subset)
        counts_for_difference[correct_label] = (correct, len(subset))
        accuracy_by_correct_label.append(
            {
                "correct_answer_displayed_as": correct_label,
                "eligible_count": len(subset),
                "correct_count": correct,
                "accuracy": safe_divide(correct, len(subset)),
                "confidence_interval_95": _wilson_interval(correct, len(subset)),
            }
        )
    a_correct, a_total = counts_for_difference["A"]
    b_correct, b_total = counts_for_difference["B"]
    contextual_difference = _difference_in_independent_proportions(
        a_correct, a_total, b_correct, b_total
    )

    confounded = any(row.get("position_effects_confounded") for row in rows)
    notes = sorted(
        {
            str(row.get("position_confounding_note"))
            for row in rows
            if row.get("position_confounding_note")
        }
    )
    return {
        "supported": bool(eligible),
        "total_records": len(rows),
        "eligible_count": len(eligible),
        "mapping_coverage": safe_divide(len(eligible), len(rows)),
        "displayed_a_selection": _rate_summary(a_count, len(eligible)),
        "displayed_b_selection": _rate_summary(len(eligible) - a_count, len(eligible)),
        "by_stage_and_a_side": stratified,
        "accuracy_by_correct_displayed_label": accuracy_by_correct_label,
        "accuracy_when_correct_is_A_minus_when_correct_is_B": contextual_difference.get("difference"),
        "contextual_accuracy_difference_confidence_interval_95": contextual_difference.get(
            "confidence_interval_95"
        ),
        "label_and_position_confounded": confounded,
        "confounding_notes": notes,
        "pure_label_bias_test": False,
        "interpretation_guardrail": (
            "Within a statement, ABA, or BAB condition, displayed label can be "
            "confounded with position and turn allocation. The fixed-content original-"
            "BAB versus swapped-BAB comparison is required for the strongest A/B claim."
        ),
    }


def compute_speaking_order_bias(rows: Sequence[Mapping[str, Any]]) -> JSONDict:
    role_specs = (
        ("first", "first_speaker_label", "first_speaker_side"),
        ("last", "last_speaker_label", "last_speaker_side"),
        ("two_turn", "two_turn_speaker_label", "two_turn_speaker_side"),
    )
    role_summaries: Table = []

    for role, label_field, side_field in role_specs:
        eligible: List[Tuple[Mapping[str, Any], str, str]] = []
        for row in rows:
            label = row.get(label_field)
            side = row.get(side_field)
            selected = selected_displayed_label(row)
            if label in {"A", "B"} and side in {"PRO", "CON"} and selected in {"A", "B"}:
                eligible.append((row, str(label), str(side)))
        selected_role = sum(selected_displayed_label(row) == label for row, label, _ in eligible)

        by_side_and_stage: Table = []
        for stage in list(EXPECTED_STAGE_COUNTS):
            for role_side in ("PRO", "CON"):
                subset = [
                    (row, label)
                    for row, label, side in eligible
                    if row.get("stage") == stage and side == role_side
                ]
                selected_count = sum(
                    selected_displayed_label(row) == label for row, label in subset
                )
                by_side_and_stage.append(
                    {
                        "stage": stage,
                        "role_side": role_side,
                        "eligible_count": len(subset),
                        "selected_count": selected_count,
                        "selection_rate": safe_divide(selected_count, len(subset)),
                        "confidence_interval_95": _wilson_interval(
                            selected_count, len(subset)
                        ),
                    }
                )

        correct_role = []
        correct_not_role = []
        for row, _, side in eligible:
            correct_side = _correct_side_for_row(row)
            if correct_side is None or row.get("binary_correct") is None:
                continue
            target = correct_role if correct_side == side else correct_not_role
            target.append(bool(row.get("binary_correct")))
        role_summaries.append(
            {
                "role": role,
                "supported": bool(eligible),
                "eligible_count": len(eligible),
                "selected_role_count": selected_role,
                "selection_rate": safe_divide(selected_role, len(eligible)),
                "selection_confidence_interval_95": _wilson_interval(
                    selected_role, len(eligible)
                ),
                "accuracy_when_correct_side_has_role": safe_divide(
                    sum(correct_role), len(correct_role)
                ),
                "accuracy_when_correct_side_lacks_role": safe_divide(
                    sum(correct_not_role), len(correct_not_role)
                ),
                "by_side_and_stage": by_side_and_stage,
            }
        )

    first_labels = {row.get("first_speaker_label") for row in rows if row.get("first_speaker_label")}
    last_labels = {row.get("last_speaker_label") for row in rows if row.get("last_speaker_label")}
    two_turn_labels = {row.get("two_turn_speaker_label") for row in rows if row.get("two_turn_speaker_label")}
    confounded = any(row.get("position_effects_confounded") for row in rows)
    return {
        "supported": any(item["supported"] for item in role_summaries),
        "roles": role_summaries,
        "position_effects_confounded": confounded,
        "first_last_two_turn_same_label": bool(
            len(first_labels) == 1
            and first_labels == last_labels
            and first_labels == two_turn_labels
        ),
        "confounding_notes": sorted(
            {
                str(row.get("position_confounding_note"))
                for row in rows
                if row.get("position_confounding_note")
            }
        ),
        "interpretation_guardrail": (
            "ABA and BAB allocate opening, closing, and two turns to the same speaker; "
            "those positional mechanisms cannot be separated within one order."
        ),
    }


def count_words(text: Optional[str]) -> Optional[int]:
    if text is None:
        return None
    return len(re.findall(r"\b[^\W_]+(?:[’'\-][^\W_]+)*\b", text, flags=re.UNICODE))


def compute_verbosity_bias(rows: Sequence[Mapping[str, Any]]) -> JSONDict:
    enriched: List[JSONDict] = []
    for row in rows:
        pro_words = count_words(row.get("pro_argument_text"))
        con_words = count_words(row.get("con_argument_text"))
        a_words = count_words(row.get("a_argument_text"))
        b_words = count_words(row.get("b_argument_text"))
        if all(value is None for value in (pro_words, con_words, a_words, b_words)):
            continue
        selected_side = _selected_side_for_row(row)
        selected_label = selected_displayed_label(row)
        side_longer = None
        if pro_words is not None and con_words is not None and pro_words != con_words:
            side_longer = "PRO" if pro_words > con_words else "CON"
        label_longer = None
        if a_words is not None and b_words is not None and a_words != b_words:
            label_longer = "A" if a_words > b_words else "B"
        enriched.append(
            {
                "row": row,
                "pro_words": pro_words,
                "con_words": con_words,
                "a_words": a_words,
                "b_words": b_words,
                "selected_side": selected_side,
                "selected_label": selected_label,
                "side_longer": side_longer,
                "label_longer": label_longer,
            }
        )

    side_eligible = [
        item
        for item in enriched
        if item["side_longer"] is not None and item["selected_side"] is not None
    ]
    side_selected_longer = [
        item for item in side_eligible if item["selected_side"] == item["side_longer"]
    ]
    side_selected_shorter = [
        item for item in side_eligible if item["selected_side"] != item["side_longer"]
    ]
    label_eligible = [
        item
        for item in enriched
        if item["label_longer"] is not None and item["selected_label"] is not None
    ]
    label_selected_longer = [
        item for item in label_eligible if item["selected_label"] == item["label_longer"]
    ]

    stratified: Table = []
    for stage in list(EXPECTED_STAGE_COUNTS):
        for truth in ("Yes", "No"):
            subset = [
                item
                for item in side_eligible
                if item["row"].get("stage") == stage
                and item["row"].get("ground_truth") == truth
            ]
            selected = sum(
                item["selected_side"] == item["side_longer"] for item in subset
            )
            stratified.append(
                {
                    "stage": stage,
                    "ground_truth": truth,
                    "eligible_count": len(subset),
                    "longer_side_selected_count": selected,
                    "longer_side_selection_rate": safe_divide(selected, len(subset)),
                    "confidence_interval_95": _wilson_interval(selected, len(subset)),
                }
            )

    def correctness(items: Sequence[Mapping[str, Any]]) -> Optional[float]:
        values = [
            bool(item["row"].get("binary_correct"))
            for item in items
            if item["row"].get("binary_correct") is not None
        ]
        return safe_divide(sum(values), len(values))

    pro_lengths = [float(item["pro_words"]) for item in enriched if item["pro_words"] is not None]
    con_lengths = [float(item["con_words"]) for item in enriched if item["con_words"] is not None]
    a_lengths = [float(item["a_words"]) for item in enriched if item["a_words"] is not None]
    b_lengths = [float(item["b_words"]) for item in enriched if item["b_words"] is not None]
    pro_longer_count = sum(item["side_longer"] == "PRO" for item in side_eligible)
    a_longer_count = sum(item["label_longer"] == "A" for item in label_eligible)

    return {
        "supported": bool(enriched),
        "total_records": len(rows),
        "argument_length_record_count": len(enriched),
        "argument_length_coverage": safe_divide(len(enriched), len(rows)),
        "mean_pro_words": _mean(pro_lengths),
        "median_pro_words": _median(pro_lengths),
        "mean_con_words": _mean(con_lengths),
        "median_con_words": _median(con_lengths),
        "mean_a_words": _mean(a_lengths),
        "median_a_words": _median(a_lengths),
        "mean_b_words": _mean(b_lengths),
        "median_b_words": _median(b_lengths),
        "pro_longer": _rate_summary(pro_longer_count, len(side_eligible)),
        "a_longer": _rate_summary(a_longer_count, len(label_eligible)),
        "longer_side_selected": _rate_summary(
            len(side_selected_longer), len(side_eligible)
        ),
        "longer_displayed_label_selected": _rate_summary(
            len(label_selected_longer), len(label_eligible)
        ),
        "accuracy_when_selected_side_is_longer": correctness(side_selected_longer),
        "accuracy_when_selected_side_is_shorter": correctness(side_selected_shorter),
        "by_stage_and_truth": stratified,
        "interactive_turn_allocation_confounded": any(
            row.get("two_turn_speaker_label") is not None for row in rows
        ),
        "interpretation_guardrail": (
            "In three-turn debate, the opening/closing side receives two turns by "
            "design, so total length can reflect turn allocation rather than a free "
            "verbosity choice."
        ),
    }


def compute_condition_bias_metrics(rows: Sequence[Mapping[str, Any]]) -> Table:
    table: Table = []
    for condition_id, condition_rows in sorted(_rows_grouped_by_condition(rows).items()):
        first = condition_rows[0] if condition_rows else {}
        pro_con = compute_pro_con_bias(condition_rows)
        ab_label = compute_ab_label_bias(condition_rows)
        order = compute_speaking_order_bias(condition_rows)
        verbosity = compute_verbosity_bias(condition_rows)
        role_by_name = {item["role"]: item for item in order.get("roles", [])}
        table.append(
            {
                "condition_id": condition_id,
                "display_name": _condition_display_name(condition_id),
                "family": first.get("family"),
                "generation": first.get("generation"),
                "variant": first.get("condition_variant"),
                "row_count": len(condition_rows),
                "pro_con_supported": pro_con.get("supported"),
                "pro_selection_rate": pro_con.get("pro_selection", {}).get("rate"),
                "con_selection_rate": pro_con.get("con_selection", {}).get("rate"),
                "false_positive_rate": pro_con.get("false_positive_rate"),
                "false_negative_rate": pro_con.get("false_negative_rate"),
                "false_positive_minus_false_negative_rate": pro_con.get(
                    "false_positive_minus_false_negative_rate"
                ),
                "error_asymmetry_confidence_interval_95": pro_con.get(
                    "error_asymmetry_confidence_interval_95"
                ),
                "ab_label_supported": ab_label.get("supported"),
                "displayed_a_selection_rate": ab_label.get(
                    "displayed_a_selection", {}
                ).get("rate"),
                "label_and_position_confounded": ab_label.get(
                    "label_and_position_confounded"
                ),
                "order_supported": order.get("supported"),
                "first_speaker_selection_rate": role_by_name.get("first", {}).get(
                    "selection_rate"
                ),
                "last_speaker_selection_rate": role_by_name.get("last", {}).get(
                    "selection_rate"
                ),
                "two_turn_speaker_selection_rate": role_by_name.get("two_turn", {}).get(
                    "selection_rate"
                ),
                "position_effects_confounded": order.get(
                    "position_effects_confounded"
                ),
                "verbosity_supported": verbosity.get("supported"),
                "argument_length_coverage": verbosity.get("argument_length_coverage"),
                "longer_side_selection_rate": verbosity.get(
                    "longer_side_selected", {}
                ).get("rate"),
                "accuracy_when_selected_side_is_longer": verbosity.get(
                    "accuracy_when_selected_side_is_longer"
                ),
                "accuracy_when_selected_side_is_shorter": verbosity.get(
                    "accuracy_when_selected_side_is_shorter"
                ),
                "pro_con_detail": pro_con,
                "ab_label_detail": ab_label,
                "speaking_order_detail": order,
                "verbosity_detail": verbosity,
            }
        )
    return table


# =============================================================================
# 8. Confidence and log-probability analysis
# =============================================================================


def clamp_probability(probability: float, epsilon: float = 1e-12) -> float:
    import math

    if not 0.0 < epsilon < 0.5:
        raise ValueError("epsilon must be strictly between zero and 0.5")
    try:
        converted = float(probability)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Invalid probability: {probability!r}") from exc
    if not math.isfinite(converted):
        raise ValueError(f"Probability must be finite, found {converted!r}")
    if converted < 0.0 or converted > 1.0:
        raise ValueError(f"Probability must lie in [0, 1], found {converted!r}")
    return min(1.0 - epsilon, max(epsilon, converted))


def probability_argmax_label(probability_yes: Optional[float]) -> Optional[str]:
    probability = _as_probability(probability_yes)
    if probability is None:
        return None
    return "Yes" if probability >= 0.5 else "No"


def debater_probability_to_yes(row: Mapping[str, Any]) -> Optional[float]:
    probability_a = _as_probability(row.get("debater_prob_A_right", MISSING))
    if probability_a is None:
        return None
    displayed_a_side = _normalize_side(
        row.get(
            "presented_a_side",
            row.get("displayed_a_side", row.get("a_side", MISSING)),
        )
    )
    if displayed_a_side == "PRO":
        return probability_a
    if displayed_a_side == "CON":
        return 1.0 - probability_a
    return None


def _confidence_probability(
    row: Mapping[str, Any], probability_field: str
) -> Optional[float]:
    if probability_field == "debater_prob_yes":
        stored = _as_probability(row.get(probability_field, MISSING))
        return stored if stored is not None else debater_probability_to_yes(row)
    return _as_probability(row.get(probability_field, MISSING))


def compute_binary_auc(
    rows: Sequence[Mapping[str, Any]], probability_field: str
) -> Optional[float]:
    observations: List[Tuple[float, int]] = []
    for row in rows:
        truth = row.get("ground_truth")
        probability = _confidence_probability(row, probability_field)
        if truth in VALID_BINARY_LABELS and probability is not None:
            observations.append((probability, 1 if truth == "Yes" else 0))

    positive_count = sum(label for _, label in observations)
    negative_count = len(observations) - positive_count
    if positive_count == 0 or negative_count == 0:
        return None

    observations.sort(key=lambda item: item[0])
    positive_rank_sum = 0.0
    index = 0
    while index < len(observations):
        end = index + 1
        while end < len(observations) and observations[end][0] == observations[index][0]:
            end += 1
        average_rank = ((index + 1) + end) / 2.0
        positive_rank_sum += average_rank * sum(
            label for _, label in observations[index:end]
        )
        index = end

    return (
        positive_rank_sum
        - positive_count * (positive_count + 1) / 2.0
    ) / (positive_count * negative_count)


def compute_brier_score(
    rows: Sequence[Mapping[str, Any]], probability_field: str
) -> Optional[float]:
    errors: List[float] = []
    for row in rows:
        probability = _confidence_probability(row, probability_field)
        truth = row.get("ground_truth")
        if probability is None or truth not in VALID_BINARY_LABELS:
            continue
        target = 1.0 if truth == "Yes" else 0.0
        errors.append((probability - target) ** 2)
    return _mean(errors)


def compute_log_loss(
    rows: Sequence[Mapping[str, Any]], probability_field: str
) -> Optional[float]:
    import math

    losses: List[float] = []
    for row in rows:
        probability = _confidence_probability(row, probability_field)
        truth = row.get("ground_truth")
        if probability is None or truth not in VALID_BINARY_LABELS:
            continue
        bounded = clamp_probability(probability)
        losses.append(-math.log(bounded if truth == "Yes" else 1.0 - bounded))
    return _mean(losses)


def compute_expected_calibration_error(
    rows: Sequence[Mapping[str, Any]],
    probability_field: str,
    bins: int = 10,
) -> JSONDict:
    if bins <= 0:
        raise ValueError("bins must be greater than zero")

    eligible: List[Tuple[Mapping[str, Any], float, int]] = []
    for row in rows:
        probability = _confidence_probability(row, probability_field)
        truth = row.get("ground_truth")
        if probability is not None and truth in VALID_BINARY_LABELS:
            eligible.append((row, probability, 1 if truth == "Yes" else 0))

    buckets: List[List[Tuple[Mapping[str, Any], float, int]]] = [
        [] for _ in range(bins)
    ]
    for item in eligible:
        bucket_index = min(bins - 1, int(item[1] * bins))
        buckets[bucket_index].append(item)

    calibration_rows: Table = []
    probability_ece = 0.0
    chosen_confidence_ece = 0.0
    total = len(eligible)
    for bucket_index, bucket in enumerate(buckets):
        lower = bucket_index / bins
        upper = (bucket_index + 1) / bins
        count = len(bucket)
        mean_probability = _mean([probability for _, probability, _ in bucket])
        observed_yes_rate = _mean([float(target) for _, _, target in bucket])
        threshold_correct = [
            probability_argmax_label(probability)
            == ("Yes" if target == 1 else "No")
            for _, probability, target in bucket
        ]
        mean_chosen_confidence = _mean(
            [max(probability, 1.0 - probability) for _, probability, _ in bucket]
        )
        threshold_accuracy = safe_divide(sum(threshold_correct), count)
        probability_gap = (
            abs(mean_probability - observed_yes_rate)
            if mean_probability is not None and observed_yes_rate is not None
            else None
        )
        confidence_gap = (
            abs(mean_chosen_confidence - threshold_accuracy)
            if mean_chosen_confidence is not None and threshold_accuracy is not None
            else None
        )
        weight = safe_divide(count, total)
        if weight is not None and probability_gap is not None:
            probability_ece += weight * probability_gap
        if weight is not None and confidence_gap is not None:
            chosen_confidence_ece += weight * confidence_gap
        calibration_rows.append(
            {
                "bin": bucket_index + 1,
                "lower_probability_inclusive": lower,
                "upper_probability_inclusive": upper if bucket_index == bins - 1 else None,
                "upper_probability_exclusive": None if bucket_index == bins - 1 else upper,
                "count": count,
                "weight": weight,
                "mean_probability_yes": mean_probability,
                "observed_yes_rate": observed_yes_rate,
                "probability_calibration_gap": probability_gap,
                "mean_argmax_confidence": mean_chosen_confidence,
                "argmax_accuracy": threshold_accuracy,
                "confidence_calibration_gap": confidence_gap,
            }
        )

    return {
        "probability_field": probability_field,
        "total_rows": len(rows),
        "eligible_count": total,
        "coverage": safe_divide(total, len(rows)),
        "bin_count": bins,
        "expected_calibration_error": probability_ece if total else None,
        "argmax_confidence_ece": chosen_confidence_ece if total else None,
        "calibration_bins": calibration_rows,
        "definition": (
            "Probability ECE compares mean P(Yes) with the observed Yes rate. "
            "Argmax-confidence ECE compares confidence in the thresholded class "
            "with thresholded-label accuracy."
        ),
    }


def compute_confidence_deciles(
    rows: Sequence[Mapping[str, Any]],
    probability_field: str,
) -> Table:
    eligible: List[Tuple[float, float, Mapping[str, Any]]] = []
    for row in rows:
        probability = _confidence_probability(row, probability_field)
        if probability is None or row.get("ground_truth") not in VALID_BINARY_LABELS:
            continue
        eligible.append((max(probability, 1.0 - probability), probability, row))

    eligible.sort(
        key=lambda item: (
            item[0],
            item[1],
            repr(make_exact_match_key(item[2])),
        )
    )
    grouped: Dict[int, List[Tuple[float, float, Mapping[str, Any]]]] = defaultdict(list)
    total = len(eligible)
    for index, item in enumerate(eligible):
        decile = min(10, int(index * 10 / total) + 1) if total else 1
        grouped[decile].append(item)

    output: Table = []
    for decile in range(1, 11):
        bucket = grouped.get(decile, [])
        threshold_correct = [
            probability_argmax_label(probability) == row.get("ground_truth")
            for _, probability, row in bucket
        ]
        generated_strict_correct = [
            bool(row.get("binary_correct")) for _, _, row in bucket
        ]
        generated_valid = [
            row
            for _, _, row in bucket
            if row.get("prediction") in VALID_BINARY_LABELS
        ]
        output.append(
            {
                "probability_field": probability_field,
                "decile": decile,
                "decile_order": "1=lowest confidence, 10=highest confidence",
                "count": len(bucket),
                "coverage_of_eligible": safe_divide(len(bucket), total),
                "coverage_of_condition": safe_divide(len(bucket), len(rows)),
                "minimum_confidence": min((item[0] for item in bucket), default=None),
                "maximum_confidence": max((item[0] for item in bucket), default=None),
                "mean_confidence": _mean([item[0] for item in bucket]),
                "threshold_accuracy": safe_divide(
                    sum(threshold_correct), len(threshold_correct)
                ),
                "generated_strict_accuracy": safe_divide(
                    sum(generated_strict_correct), len(generated_strict_correct)
                ),
                "generated_valid_only_accuracy": safe_divide(
                    sum(bool(row.get("binary_correct")) for row in generated_valid),
                    len(generated_valid),
                ),
                "generated_valid_prediction_count": len(generated_valid),
            }
        )
    return output


def compute_selective_accuracy(
    rows: Sequence[Mapping[str, Any]],
    probability_field: str,
) -> Table:
    import math

    eligible: List[Tuple[float, float, Mapping[str, Any]]] = []
    for row in rows:
        probability = _confidence_probability(row, probability_field)
        if probability is None or row.get("ground_truth") not in VALID_BINARY_LABELS:
            continue
        eligible.append((max(probability, 1.0 - probability), probability, row))
    eligible.sort(
        key=lambda item: (
            -item[0],
            -item[1],
            repr(make_exact_match_key(item[2])),
        )
    )

    output: Table = []
    coverage_levels = (1.0, 0.9, 0.8, 0.7, 0.6, 0.5, 0.4, 0.3, 0.2, 0.1)
    previous_retained = None
    for requested_coverage in coverage_levels:
        retained_count = (
            min(len(eligible), max(1, int(math.ceil(len(eligible) * requested_coverage))))
            if eligible
            else 0
        )
        if retained_count == previous_retained:
            continue
        previous_retained = retained_count
        retained = eligible[:retained_count]
        threshold_correct = [
            probability_argmax_label(probability) == row.get("ground_truth")
            for _, probability, row in retained
        ]
        generated_valid = [
            row
            for _, _, row in retained
            if row.get("prediction") in VALID_BINARY_LABELS
        ]
        output.append(
            {
                "probability_field": probability_field,
                "requested_coverage_of_confidence_eligible": requested_coverage,
                "retained_count": retained_count,
                "eligible_count": len(eligible),
                "actual_coverage_of_confidence_eligible": safe_divide(
                    retained_count, len(eligible)
                ),
                "actual_coverage_of_condition": safe_divide(retained_count, len(rows)),
                "minimum_retained_confidence": (
                    retained[-1][0] if retained else None
                ),
                "threshold_accuracy": safe_divide(
                    sum(threshold_correct), len(threshold_correct)
                ),
                "generated_strict_accuracy": safe_divide(
                    sum(bool(row.get("binary_correct")) for _, _, row in retained),
                    len(retained),
                ),
                "generated_valid_only_accuracy": safe_divide(
                    sum(bool(row.get("binary_correct")) for row in generated_valid),
                    len(generated_valid),
                ),
                "generated_valid_prediction_count": len(generated_valid),
            }
        )
    return output


def compute_framing_agreement(rows: Sequence[Mapping[str, Any]]) -> JSONDict:
    frame_order = (
        "generated_prediction",
        "yes_no",
        "true_false",
        "debater_ab_converted",
    )
    labels_by_row: List[Tuple[Mapping[str, Any], Dict[str, Optional[str]]]] = []
    for row in rows:
        generated = normalize_label(row.get("prediction", MISSING))
        labels = {
            "generated_prediction": generated if generated in VALID_BINARY_LABELS else None,
            "yes_no": probability_argmax_label(
                _confidence_probability(row, "verdict_prob_belongs")
            ),
            "true_false": probability_argmax_label(
                _confidence_probability(row, "boolean_prob_true")
            ),
            "debater_ab_converted": probability_argmax_label(
                _confidence_probability(row, "debater_prob_yes")
            ),
        }
        labels_by_row.append((row, labels))

    pairwise: Table = []
    pair_specs: List[Tuple[str, str]] = []
    for left_index, left in enumerate(frame_order):
        for right in frame_order[left_index + 1 :]:
            pair_specs.append((left, right))
            eligible = [
                labels
                for _, labels in labels_by_row
                if labels[left] is not None and labels[right] is not None
            ]
            agreements = sum(labels[left] == labels[right] for labels in eligible)
            pairwise.append(
                {
                    "left_framing": left,
                    "right_framing": right,
                    "eligible_count": len(eligible),
                    "agreement_count": agreements,
                    "disagreement_count": len(eligible) - agreements,
                    "agreement_rate": safe_divide(agreements, len(eligible)),
                    "disagreement_rate": safe_divide(
                        len(eligible) - agreements, len(eligible)
                    ),
                }
            )

    by_stage: Table = []
    for stage in list(EXPECTED_STAGE_COUNTS) + sorted(
        {
            str(row.get("stage"))
            for row in rows
            if row.get("stage") not in EXPECTED_STAGE_COUNTS
        }
    ):
        stage_items = [item for item in labels_by_row if item[0].get("stage") == stage]
        for left, right in pair_specs:
            eligible = [
                labels
                for _, labels in stage_items
                if labels[left] is not None and labels[right] is not None
            ]
            agreements = sum(labels[left] == labels[right] for labels in eligible)
            by_stage.append(
                {
                    "stage": stage,
                    "left_framing": left,
                    "right_framing": right,
                    "eligible_count": len(eligible),
                    "agreement_count": agreements,
                    "agreement_rate": safe_divide(agreements, len(eligible)),
                }
            )

    patterns: Counter[str] = Counter()
    complete_count = 0
    for _, labels in labels_by_row:
        available = {name: value for name, value in labels.items() if value is not None}
        if len(available) < 2:
            continue
        if len(available) == len(frame_order):
            complete_count += 1
        pattern = " | ".join(
            f"{name}={labels[name] if labels[name] is not None else 'NA'}"
            for name in frame_order
        )
        patterns[pattern] += 1

    return {
        "total_records": len(rows),
        "available_counts": {
            name: sum(labels[name] is not None for _, labels in labels_by_row)
            for name in frame_order
        },
        "complete_all_framings_count": complete_count,
        "complete_all_framings_coverage": safe_divide(complete_count, len(rows)),
        "pairwise": pairwise,
        "by_stage": by_stage,
        "patterns": [
            {"pattern": pattern, "count": count}
            for pattern, count in sorted(
                patterns.items(), key=lambda item: (-item[1], item[0])
            )
        ],
        "interpretation_note": (
            "These probabilities come from separate teacher-forced follow-up "
            "framings. Disagreement measures framing sensitivity, not sampling "
            "variance in the original generated explanation."
        ),
    }


def compute_fallback_stratified_logprob_metrics(
    rows: Sequence[Mapping[str, Any]],
) -> Table:
    prepared: List[Row] = []
    for original in rows:
        row = dict(original)
        row["debater_prob_yes"] = debater_probability_to_yes(row)
        prepared.append(row)

    fallback_true = [row for row in prepared if row.get("needed_fallback") is True]
    fallback_false = [row for row in prepared if row.get("needed_fallback") is False]
    scopes = (
        ("all", prepared),
        ("non_fallback", fallback_false),
        ("fallback", fallback_true),
    )
    framings = (
        ("yes_no", "verdict_prob_belongs"),
        ("true_false", "boolean_prob_true"),
        ("debater_ab_converted", "debater_prob_yes"),
    )

    output: Table = []
    for scope, scope_rows in scopes:
        for framing, field in framings:
            eligible = [
                row
                for row in scope_rows
                if row.get("ground_truth") in VALID_BINARY_LABELS
                and _confidence_probability(row, field) is not None
            ]
            if not eligible:
                continue
            threshold_correct = sum(
                probability_argmax_label(_confidence_probability(row, field))
                == row.get("ground_truth")
                for row in eligible
            )
            agreement_rows = [
                row
                for row in eligible
                if row.get("prediction") in VALID_BINARY_LABELS
            ]
            agreements = sum(
                probability_argmax_label(_confidence_probability(row, field))
                == row.get("prediction")
                for row in agreement_rows
            )
            calibration = compute_expected_calibration_error(eligible, field)
            output.append(
                {
                    "scope": scope,
                    "framing": framing,
                    "probability_field": field,
                    "scope_record_count": len(scope_rows),
                    "eligible_count": len(eligible),
                    "coverage_within_scope": safe_divide(len(eligible), len(scope_rows)),
                    "threshold_accuracy": safe_divide(threshold_correct, len(eligible)),
                    "generated_prediction_agreement_count": agreements,
                    "generated_prediction_agreement_eligible": len(agreement_rows),
                    "generated_prediction_agreement_rate": safe_divide(
                        agreements, len(agreement_rows)
                    ),
                    "roc_auc": compute_binary_auc(eligible, field),
                    "brier_score": compute_brier_score(eligible, field),
                    "negative_log_likelihood": compute_log_loss(eligible, field),
                    "expected_calibration_error": calibration.get(
                        "expected_calibration_error"
                    ),
                    "argmax_confidence_ece": calibration.get(
                        "argmax_confidence_ece"
                    ),
                    "fallback_circularity_warning": (
                        scope == "fallback" and framing == "yes_no"
                    ),
                    "interpretation_note": (
                        "On fallback records, the final prediction was selected from "
                        "the Yes/No confidence argmax; prediction/agreement is therefore "
                        "circular for that framing."
                        if scope == "fallback" and framing == "yes_no"
                        else None
                    ),
                }
            )
    return output


def compute_logprob_metrics_for_condition(
    rows: Sequence[Mapping[str, Any]],
) -> JSONDict:
    prepared: List[Row] = []
    for original in rows:
        row = dict(original)
        row["debater_prob_yes"] = debater_probability_to_yes(row)
        prepared.append(row)

    framing_specs = (
        ("yes_no", "verdict_prob_belongs"),
        ("true_false", "boolean_prob_true"),
        ("debater_ab_converted", "debater_prob_yes"),
    )
    framing_rows: Table = []
    for framing, field in framing_specs:
        eligible = [
            row
            for row in prepared
            if row.get("ground_truth") in VALID_BINARY_LABELS
            and _confidence_probability(row, field) is not None
        ]
        if not eligible:
            continue

        threshold_items: List[Tuple[Mapping[str, Any], float, str, bool]] = []
        for row in eligible:
            probability = _confidence_probability(row, field)
            if probability is None:
                continue
            label = probability_argmax_label(probability)
            if label is None:
                continue
            threshold_items.append(
                (
                    row,
                    probability,
                    label,
                    label == row.get("ground_truth"),
                )
            )
        threshold_correct = sum(item[3] for item in threshold_items)
        threshold_confidence_correct = [
            max(item[1], 1.0 - item[1]) for item in threshold_items if item[3]
        ]
        threshold_confidence_errors = [
            max(item[1], 1.0 - item[1]) for item in threshold_items if not item[3]
        ]
        high_confidence = [
            item for item in threshold_items if max(item[1], 1.0 - item[1]) >= 0.9
        ]
        high_confidence_errors = [item for item in high_confidence if not item[3]]

        generated_items: List[Tuple[Mapping[str, Any], float, bool, bool]] = []
        for row, probability, label, _ in threshold_items:
            prediction = row.get("prediction")
            if prediction not in VALID_BINARY_LABELS:
                continue
            generated_confidence = probability if prediction == "Yes" else 1.0 - probability
            generated_items.append(
                (
                    row,
                    generated_confidence,
                    prediction == label,
                    prediction == row.get("ground_truth"),
                )
            )
        generated_high_confidence = [
            item for item in generated_items if item[1] >= 0.9
        ]
        generated_high_confidence_errors = [
            item for item in generated_high_confidence if not item[3]
        ]
        calibration = compute_expected_calibration_error(eligible, field)

        framing_rows.append(
            {
                "framing": framing,
                "probability_field": field,
                "total_records": len(prepared),
                "eligible_count": len(eligible),
                "coverage": safe_divide(len(eligible), len(prepared)),
                "threshold_correct_count": threshold_correct,
                "threshold_accuracy": safe_divide(
                    threshold_correct, len(threshold_items)
                ),
                "threshold_accuracy_confidence_interval_95": _wilson_interval(
                    threshold_correct, len(threshold_items)
                ),
                "generated_prediction_agreement_count": sum(
                    item[2] for item in generated_items
                ),
                "generated_prediction_agreement_eligible": len(generated_items),
                "generated_prediction_agreement_rate": safe_divide(
                    sum(item[2] for item in generated_items), len(generated_items)
                ),
                "roc_auc": compute_binary_auc(eligible, field),
                "brier_score": compute_brier_score(eligible, field),
                "negative_log_likelihood": compute_log_loss(eligible, field),
                "expected_calibration_error": calibration.get(
                    "expected_calibration_error"
                ),
                "argmax_confidence_ece": calibration.get(
                    "argmax_confidence_ece"
                ),
                "mean_argmax_confidence_correct": _mean(
                    threshold_confidence_correct
                ),
                "mean_argmax_confidence_error": _mean(
                    threshold_confidence_errors
                ),
                "high_confidence_threshold": 0.9,
                "high_confidence_count": len(high_confidence),
                "high_confidence_error_count": len(high_confidence_errors),
                "high_confidence_error_rate": safe_divide(
                    len(high_confidence_errors), len(high_confidence)
                ),
                "mean_generated_label_confidence_correct": _mean(
                    [item[1] for item in generated_items if item[3]]
                ),
                "mean_generated_label_confidence_error": _mean(
                    [item[1] for item in generated_items if not item[3]]
                ),
                "generated_high_confidence_count": len(generated_high_confidence),
                "generated_high_confidence_error_count": len(
                    generated_high_confidence_errors
                ),
                "generated_high_confidence_error_rate": safe_divide(
                    len(generated_high_confidence_errors),
                    len(generated_high_confidence),
                ),
                "calibration_bins": calibration.get("calibration_bins", []),
                "confidence_deciles": compute_confidence_deciles(eligible, field),
                "selective_accuracy": compute_selective_accuracy(eligible, field),
            }
        )

    fallback_true = sum(row.get("needed_fallback") is True for row in prepared)
    fallback_false = sum(row.get("needed_fallback") is False for row in prepared)
    return {
        "available": bool(framing_rows),
        "total_records": len(prepared),
        "framing_count": len(framing_rows),
        "framings": framing_rows,
        "framing_agreement": compute_framing_agreement(prepared),
        "fallback_metrics": compute_fallback_stratified_logprob_metrics(prepared),
        "fallback_true_count": fallback_true,
        "fallback_false_count": fallback_false,
        "fallback_unknown_count": len(prepared) - fallback_true - fallback_false,
        "fallback_rate_among_known": safe_divide(
            fallback_true, fallback_true + fallback_false
        ),
        "confidence_provenance": (
            "Teacher-forced continuation scores from separate follow-up prompt "
            "framings; they are not probabilities extracted from the original "
            "generated explanation."
        ),
        "status": "computed" if framing_rows else "not_applicable_no_confidence_fields",
    }


def compute_all_logprob_metrics(
    rows: Sequence[Mapping[str, Any]],
) -> Tuple[Table, Table, Table]:
    summary_rows: Table = []
    calibration_rows: Table = []
    selective_rows: Table = []

    for condition_id, condition_rows in sorted(_rows_grouped_by_condition(rows).items()):
        detail = compute_logprob_metrics_for_condition(condition_rows)
        agreement = detail.get("framing_agreement", {})
        if not detail.get("framings"):
            summary_rows.append(
                {
                    "condition_id": condition_id,
                    "display_name": _condition_display_name(condition_id),
                    "scope": "all",
                    "framing": None,
                    "status": detail.get("status"),
                    "total_records": len(condition_rows),
                    "confidence_provenance": detail.get("confidence_provenance"),
                }
            )
            continue

        for framing in detail.get("framings", []):
            summary = {
                key: value
                for key, value in framing.items()
                if key
                not in {
                    "calibration_bins",
                    "confidence_deciles",
                    "selective_accuracy",
                }
            }
            summary_rows.append(
                {
                    "condition_id": condition_id,
                    "display_name": _condition_display_name(condition_id),
                    "scope": "all",
                    "status": "computed",
                    **summary,
                    "fallback_rate_among_known": detail.get(
                        "fallback_rate_among_known"
                    ),
                    "complete_all_framings_count": agreement.get(
                        "complete_all_framings_count"
                    ),
                    "confidence_provenance": detail.get("confidence_provenance"),
                }
            )
            for calibration in framing.get("calibration_bins", []):
                calibration_rows.append(
                    {
                        "condition_id": condition_id,
                        "display_name": _condition_display_name(condition_id),
                        "framing": framing.get("framing"),
                        "probability_field": framing.get("probability_field"),
                        **calibration,
                    }
                )
            for decile in framing.get("confidence_deciles", []):
                selective_rows.append(
                    {
                        "condition_id": condition_id,
                        "display_name": _condition_display_name(condition_id),
                        "table_type": "confidence_decile",
                        "framing": framing.get("framing"),
                        **decile,
                    }
                )
            for selective in framing.get("selective_accuracy", []):
                selective_rows.append(
                    {
                        "condition_id": condition_id,
                        "display_name": _condition_display_name(condition_id),
                        "table_type": "selective_accuracy",
                        "framing": framing.get("framing"),
                        **selective,
                    }
                )

        for fallback_row in detail.get("fallback_metrics", []):
            if fallback_row.get("scope") == "all":
                continue
            summary_rows.append(
                {
                    "condition_id": condition_id,
                    "display_name": _condition_display_name(condition_id),
                    "status": "computed",
                    "confidence_provenance": detail.get("confidence_provenance"),
                    **fallback_row,
                }
            )

    return summary_rows, calibration_rows, selective_rows


# =============================================================================
# 9. Pairing and statistical comparisons
# =============================================================================


def index_rows_by_loose_key(rows: Sequence[Mapping[str, Any]]) -> JSONDict:
    index: Dict[Tuple[Any, Any], List[Mapping[str, Any]]] = defaultdict(list)
    invalid_key_rows: List[Mapping[str, Any]] = []
    for row in rows:
        key = make_stage_pmid_key(row)
        if key[0] is None or key[1] is None:
            invalid_key_rows.append(row)
        index[key].append(row)

    duplicate_keys = {
        key: values for key, values in index.items() if len(values) > 1
    }
    return {
        "index": dict(index),
        "row_count": len(rows),
        "key_count": len(index),
        "unique_key_count": sum(len(values) == 1 for values in index.values()),
        "duplicate_key_count": len(duplicate_keys),
        "duplicate_excess_row_count": sum(
            len(values) - 1 for values in duplicate_keys.values()
        ),
        "invalid_key_row_count": len(invalid_key_rows),
        "duplicate_key_examples": [
            {
                "stage": key[0],
                "pmid": key[1],
                "count": len(values),
            }
            for key, values in sorted(
                duplicate_keys.items(), key=lambda item: repr(item[0])
            )[:20]
        ],
    }


def pair_conditions(
    left_rows: Sequence[Mapping[str, Any]],
    right_rows: Sequence[Mapping[str, Any]],
) -> JSONDict:
    left_payload = index_rows_by_loose_key(left_rows)
    right_payload = index_rows_by_loose_key(right_rows)
    left_index = left_payload["index"]
    right_index = right_payload["index"]
    shared_loose_keys = sorted(
        set(left_index).intersection(right_index), key=repr
    )

    pairs: List[Tuple[Row, Row]] = []
    candidate_mismatches = 0
    truth_mismatches = 0
    missing_candidate_count = 0
    ambiguous_loose_keys = 0
    exact_by_stage: Counter[str] = Counter()
    loose_by_stage: Counter[str] = Counter()
    mismatch_examples: Table = []

    for key in shared_loose_keys:
        loose_by_stage[str(key[0])] += 1
        left_values = left_index[key]
        right_values = right_index[key]
        if len(left_values) != 1 or len(right_values) != 1:
            ambiguous_loose_keys += 1
            continue
        left = left_values[0]
        right = right_values[0]
        left_candidate = left.get("candidate_tag_normalized")
        right_candidate = right.get("candidate_tag_normalized")
        left_truth = left.get("ground_truth")
        right_truth = right.get("ground_truth")
        missing_candidate = left_candidate is None or right_candidate is None
        candidate_matches = not missing_candidate and left_candidate == right_candidate
        truth_matches = (
            left_truth in VALID_BINARY_LABELS
            and right_truth in VALID_BINARY_LABELS
            and left_truth == right_truth
        )
        if missing_candidate:
            missing_candidate_count += 1
        elif not candidate_matches:
            candidate_mismatches += 1
        if not truth_matches:
            truth_mismatches += 1

        if candidate_matches and truth_matches:
            pairs.append((dict(left), dict(right)))
            exact_by_stage[str(key[0])] += 1
        elif len(mismatch_examples) < 30:
            mismatch_examples.append(
                {
                    "stage": key[0],
                    "pmid": key[1],
                    "left_candidate": left.get("candidate_tag"),
                    "right_candidate": right.get("candidate_tag"),
                    "left_truth": left_truth,
                    "right_truth": right_truth,
                    "candidate_matches": candidate_matches,
                    "truth_matches": truth_matches,
                }
            )

    pair_keys = [make_exact_match_key(left) for left, _ in pairs]
    pair_key_counter = Counter(pair_keys)
    duplicate_exact_pairs = sum(
        count - 1 for count in pair_key_counter.values() if count > 1
    )
    if duplicate_exact_pairs:
        unique_pairs: List[Tuple[Row, Row]] = []
        for pair in pairs:
            if pair_key_counter[make_exact_match_key(pair[0])] == 1:
                unique_pairs.append(pair)
        pairs = unique_pairs

    return {
        "pairs": pairs,
        "pair_count": len(pairs),
        "left_row_count": len(left_rows),
        "right_row_count": len(right_rows),
        "left_loose_key_count": left_payload["key_count"],
        "right_loose_key_count": right_payload["key_count"],
        "loose_overlap_count": len(shared_loose_keys),
        "unambiguous_loose_overlap_count": len(shared_loose_keys) - ambiguous_loose_keys,
        "ambiguous_loose_key_count": ambiguous_loose_keys,
        "candidate_mismatch_count": candidate_mismatches,
        "truth_mismatch_count": truth_mismatches,
        "missing_candidate_count": missing_candidate_count,
        "duplicate_exact_pair_excess_count": duplicate_exact_pairs,
        "left_duplicate_loose_key_count": left_payload["duplicate_key_count"],
        "right_duplicate_loose_key_count": right_payload["duplicate_key_count"],
        "left_unmatched_loose_key_count": len(set(left_index).difference(right_index)),
        "right_unmatched_loose_key_count": len(set(right_index).difference(left_index)),
        "exact_pairing_coverage_left": safe_divide(len(pairs), len(left_rows)),
        "exact_pairing_coverage_right": safe_divide(len(pairs), len(right_rows)),
        "loose_overlap_by_stage": dict(sorted(loose_by_stage.items())),
        "exact_pairs_by_stage": dict(sorted(exact_by_stage.items())),
        "mismatch_examples": mismatch_examples,
        "pairing_rule": (
            "Rows are paired only when (stage, PMID) is unambiguous and normalized "
            "candidate tag plus binary ground truth match exactly."
        ),
    }


def compute_paired_outcome_counts(
    pairs: Sequence[Tuple[Row, Row]],
) -> JSONDict:
    counts: Counter[str] = Counter()
    transitions: Counter[str] = Counter()
    by_stage: Dict[str, Counter[str]] = defaultdict(Counter)

    for left, right in pairs:
        left_prediction = normalize_label(left.get("prediction", MISSING))
        right_prediction = normalize_label(right.get("prediction", MISSING))
        truth = left.get("ground_truth")
        left_correct = (
            truth in VALID_BINARY_LABELS
            and left_prediction in VALID_BINARY_LABELS
            and left_prediction == truth
        )
        right_correct = (
            truth in VALID_BINARY_LABELS
            and right_prediction in VALID_BINARY_LABELS
            and right_prediction == truth
        )
        if left_correct and right_correct:
            outcome = "both_correct"
        elif left_correct:
            outcome = "left_only_correct"
        elif right_correct:
            outcome = "right_only_correct"
        else:
            outcome = "both_incorrect"
        counts[outcome] += 1
        counts["left_valid_prediction"] += int(left_prediction in VALID_BINARY_LABELS)
        counts["right_valid_prediction"] += int(right_prediction in VALID_BINARY_LABELS)
        counts["prediction_agreement"] += int(left_prediction == right_prediction)
        if left_prediction in VALID_BINARY_LABELS and right_prediction in VALID_BINARY_LABELS:
            counts["both_binary_predictions"] += 1
            counts["binary_prediction_agreement"] += int(
                left_prediction == right_prediction
            )
        if left_prediction not in VALID_BINARY_LABELS or right_prediction not in VALID_BINARY_LABELS:
            counts["transition_involving_unresolved"] += 1

        transition = f"{left_prediction}->{right_prediction}"
        transitions[transition] += 1
        stage = str(left.get("stage"))
        by_stage[stage][outcome] += 1
        by_stage[stage][transition] += 1
        by_stage[stage]["total"] += 1

    total = len(pairs)
    left_correct_count = counts["both_correct"] + counts["left_only_correct"]
    right_correct_count = counts["both_correct"] + counts["right_only_correct"]
    return {
        "pair_count": total,
        "both_correct": counts["both_correct"],
        "left_only_correct": counts["left_only_correct"],
        "right_only_correct": counts["right_only_correct"],
        "both_incorrect": counts["both_incorrect"],
        "left_correct_count": left_correct_count,
        "right_correct_count": right_correct_count,
        "left_strict_accuracy": safe_divide(left_correct_count, total),
        "right_strict_accuracy": safe_divide(right_correct_count, total),
        "right_minus_left_strict_accuracy": safe_divide(
            right_correct_count - left_correct_count, total
        ),
        "records_fixed_by_right": counts["right_only_correct"],
        "records_broken_by_right": counts["left_only_correct"],
        "net_records_fixed": counts["right_only_correct"] - counts["left_only_correct"],
        "prediction_agreement_count": counts["prediction_agreement"],
        "prediction_agreement_rate": safe_divide(counts["prediction_agreement"], total),
        "binary_prediction_agreement_count": counts["binary_prediction_agreement"],
        "binary_prediction_agreement_eligible": counts["both_binary_predictions"],
        "binary_prediction_agreement_rate": safe_divide(
            counts["binary_prediction_agreement"], counts["both_binary_predictions"]
        ),
        "transition_involving_unresolved_count": counts[
            "transition_involving_unresolved"
        ],
        "prediction_transitions": dict(
            sorted(transitions.items(), key=lambda item: (-item[1], item[0]))
        ),
        "yes_to_no_count": transitions["Yes->No"],
        "no_to_yes_count": transitions["No->Yes"],
        "by_stage": [
            {"stage": stage, **dict(stage_counts)}
            for stage, stage_counts in sorted(by_stage.items())
        ],
    }


def exact_mcnemar_test(
    left_only_correct: int,
    right_only_correct: int,
) -> Optional[float]:
    import math

    left = int(left_only_correct)
    right = int(right_only_correct)
    if left < 0 or right < 0:
        raise ValueError("McNemar discordant counts cannot be negative")
    discordant = left + right
    if discordant == 0:
        return None
    tail = min(left, right)
    log_probabilities = [
        math.lgamma(discordant + 1)
        - math.lgamma(k + 1)
        - math.lgamma(discordant - k + 1)
        - discordant * math.log(2.0)
        for k in range(tail + 1)
    ]
    maximum = max(log_probabilities)
    lower_tail = math.exp(maximum) * sum(
        math.exp(value - maximum) for value in log_probabilities
    )
    return min(1.0, 2.0 * lower_tail)


def clustered_bootstrap_accuracy_difference(
    pairs: Sequence[Tuple[Row, Row]],
    samples: int,
    seed: int,
) -> JSONDict:
    import random

    if samples <= 0:
        raise ValueError("samples must be greater than zero")
    if not pairs:
        return {
            "pair_count": 0,
            "cluster_count": 0,
            "strict_difference_right_minus_left": None,
            "strict_confidence_interval_95": None,
            "valid_only_difference_right_minus_left": None,
            "valid_only_confidence_interval_95": None,
            "bootstrap_samples_requested": samples,
            "bootstrap_samples_used": 0,
        }

    clusters: Dict[str, List[Tuple[Row, Row]]] = defaultdict(list)
    for index, pair in enumerate(pairs):
        pmid = pair[0].get("pmid")
        cluster_key = str(pmid) if pmid is not None else f"<missing:{index}>"
        clusters[cluster_key].append(pair)

    def aggregate(cluster_pairs: Sequence[Tuple[Row, Row]]) -> Tuple[int, int, int, int, int, int, int]:
        total = 0
        left_strict_correct = 0
        right_strict_correct = 0
        left_valid = 0
        right_valid = 0
        left_valid_correct = 0
        right_valid_correct = 0
        for left, right in cluster_pairs:
            truth = left.get("ground_truth")
            left_prediction = normalize_label(left.get("prediction", MISSING))
            right_prediction = normalize_label(right.get("prediction", MISSING))
            left_is_valid = left_prediction in VALID_BINARY_LABELS and truth in VALID_BINARY_LABELS
            right_is_valid = right_prediction in VALID_BINARY_LABELS and truth in VALID_BINARY_LABELS
            total += 1
            left_strict_correct += int(left_is_valid and left_prediction == truth)
            right_strict_correct += int(right_is_valid and right_prediction == truth)
            left_valid += int(left_is_valid)
            right_valid += int(right_is_valid)
            left_valid_correct += int(left_is_valid and left_prediction == truth)
            right_valid_correct += int(right_is_valid and right_prediction == truth)
        return (
            total,
            left_strict_correct,
            right_strict_correct,
            left_valid,
            right_valid,
            left_valid_correct,
            right_valid_correct,
        )

    cluster_aggregates = [aggregate(value) for _, value in sorted(clusters.items())]

    def difference_from_aggregate(values: Sequence[int]) -> Tuple[Optional[float], Optional[float]]:
        total, left_sc, right_sc, left_valid, right_valid, left_vc, right_vc = values
        strict = safe_divide(right_sc - left_sc, total)
        left_valid_accuracy = safe_divide(left_vc, left_valid)
        right_valid_accuracy = safe_divide(right_vc, right_valid)
        valid = (
            right_valid_accuracy - left_valid_accuracy
            if right_valid_accuracy is not None and left_valid_accuracy is not None
            else None
        )
        return strict, valid

    point_aggregate = tuple(
        sum(values[position] for values in cluster_aggregates)
        for position in range(7)
    )
    point_strict, point_valid = difference_from_aggregate(point_aggregate)

    rng = random.Random(seed)
    strict_distribution: List[float] = []
    valid_distribution: List[float] = []
    cluster_count = len(cluster_aggregates)
    for _ in range(samples):
        sampled = [
            cluster_aggregates[rng.randrange(cluster_count)]
            for _ in range(cluster_count)
        ]
        aggregate_values = tuple(
            sum(values[position] for values in sampled) for position in range(7)
        )
        strict, valid = difference_from_aggregate(aggregate_values)
        if strict is not None:
            strict_distribution.append(strict)
        if valid is not None:
            valid_distribution.append(valid)

    def percentile(values: Sequence[float], quantile: float) -> Optional[float]:
        if not values:
            return None
        ordered = sorted(values)
        position = (len(ordered) - 1) * quantile
        lower = int(position)
        upper = min(len(ordered) - 1, lower + 1)
        fraction = position - lower
        return ordered[lower] * (1.0 - fraction) + ordered[upper] * fraction

    strict_interval = (
        (percentile(strict_distribution, 0.025), percentile(strict_distribution, 0.975))
        if strict_distribution
        else None
    )
    valid_interval = (
        (percentile(valid_distribution, 0.025), percentile(valid_distribution, 0.975))
        if valid_distribution
        else None
    )
    return {
        "pair_count": len(pairs),
        "cluster_count": cluster_count,
        "cluster_unit": "PMID",
        "strict_difference_right_minus_left": point_strict,
        "strict_confidence_interval_95": strict_interval,
        "valid_only_difference_right_minus_left": point_valid,
        "valid_only_confidence_interval_95": valid_interval,
        "bootstrap_samples_requested": samples,
        "bootstrap_strict_samples_used": len(strict_distribution),
        "bootstrap_valid_only_samples_used": len(valid_distribution),
        "random_seed": seed,
    }


def _paired_scalar_difference(
    right_value: Any, left_value: Any
) -> Optional[float]:
    if isinstance(right_value, bool) or isinstance(left_value, bool):
        return None
    if not isinstance(right_value, (int, float)) or not isinstance(left_value, (int, float)):
        return None
    return float(right_value) - float(left_value)


def compute_paired_comparison(
    left_condition: str,
    right_condition: str,
    rows: Sequence[Mapping[str, Any]],
    comparison_type: str,
    causal_status: str,
    context: Mapping[str, Any],
) -> JSONDict:
    left_rows = _rows_for_condition(rows, left_condition)
    right_rows = _rows_for_condition(rows, right_condition)
    paired = pair_conditions(left_rows, right_rows)
    pairs = paired.get("pairs", [])
    pairing_summary = {key: value for key, value in paired.items() if key != "pairs"}
    comparison_id = f"{left_condition}__vs__{right_condition}"

    if not left_rows or not right_rows or not pairs:
        return {
            "comparison_id": comparison_id,
            "comparison_type": comparison_type,
            "comparison_family": comparison_type,
            "left_condition": left_condition,
            "right_condition": right_condition,
            "causal_status": causal_status,
            "comparison_status": "unavailable",
            "reason": (
                "One or both conditions are absent."
                if not left_rows or not right_rows
                else "No unambiguous exact candidate matches are available."
            ),
            "pairing": pairing_summary,
            "mcnemar_p_value": None,
        }

    paired_left = [left for left, _ in pairs]
    paired_right = [right for _, right in pairs]
    left_metrics = compute_accuracy_metrics(paired_left)
    right_metrics = compute_accuracy_metrics(paired_right)
    outcomes = compute_paired_outcome_counts(pairs)
    mcnemar_p = exact_mcnemar_test(
        outcomes["left_only_correct"], outcomes["right_only_correct"]
    )
    bootstrap = clustered_bootstrap_accuracy_difference(
        pairs,
        int(context.get("bootstrap_samples", 10_000)),
        int(context.get("random_seed", 42)),
    )

    stage_changes: Table = []
    for stage in list(EXPECTED_STAGE_COUNTS) + sorted(
        {
            str(left.get("stage"))
            for left, _ in pairs
            if left.get("stage") not in EXPECTED_STAGE_COUNTS
        }
    ):
        stage_left = [left for left, _ in pairs if left.get("stage") == stage]
        stage_right = [right for left, right in pairs if left.get("stage") == stage]
        left_stage_metrics = compute_accuracy_metrics(stage_left)
        right_stage_metrics = compute_accuracy_metrics(stage_right)
        stage_changes.append(
            {
                "stage": stage,
                "pair_count": len(stage_left),
                "left_strict_accuracy": left_stage_metrics.get("strict_accuracy"),
                "right_strict_accuracy": right_stage_metrics.get("strict_accuracy"),
                "strict_accuracy_difference_right_minus_left": _paired_scalar_difference(
                    right_stage_metrics.get("strict_accuracy"),
                    left_stage_metrics.get("strict_accuracy"),
                ),
                "left_valid_only_accuracy": left_stage_metrics.get(
                    "valid_only_accuracy"
                ),
                "right_valid_only_accuracy": right_stage_metrics.get(
                    "valid_only_accuracy"
                ),
                "valid_only_accuracy_difference_right_minus_left": _paired_scalar_difference(
                    right_stage_metrics.get("valid_only_accuracy"),
                    left_stage_metrics.get("valid_only_accuracy"),
                ),
                "left_balanced_accuracy": left_stage_metrics.get("balanced_accuracy"),
                "right_balanced_accuracy": right_stage_metrics.get("balanced_accuracy"),
            }
        )

    content_available = 0
    content_matches = 0
    abstract_available = 0
    abstract_matches = 0
    for left, right in pairs:
        left_digest = left.get("argument_content_sha256")
        right_digest = right.get("argument_content_sha256")
        if left_digest is not None and right_digest is not None:
            content_available += 1
            content_matches += int(left_digest == right_digest)
        if left.get("abstract") is not None and right.get("abstract") is not None:
            abstract_available += 1
            abstract_matches += int(left.get("abstract") == right.get("abstract"))

    left_bias = compute_pro_con_bias(paired_left)
    right_bias = compute_pro_con_bias(paired_right)
    left_ab = compute_ab_label_bias(paired_left)
    right_ab = compute_ab_label_bias(paired_right)
    left_order = compute_speaking_order_bias(paired_left)
    right_order = compute_speaking_order_bias(paired_right)
    left_verbosity = compute_verbosity_bias(paired_left)
    right_verbosity = compute_verbosity_bias(paired_right)
    left_logprob = compute_logprob_metrics_for_condition(paired_left)
    right_logprob = compute_logprob_metrics_for_condition(paired_right)

    status = causal_status
    if causal_status == "controlled" and content_available and content_matches != content_available:
        status = "partially_controlled_content_mismatch"

    strict_difference = _paired_scalar_difference(
        right_metrics.get("strict_accuracy"), left_metrics.get("strict_accuracy")
    )
    valid_difference = _paired_scalar_difference(
        right_metrics.get("valid_only_accuracy"),
        left_metrics.get("valid_only_accuracy"),
    )
    balanced_difference = _paired_scalar_difference(
        right_metrics.get("balanced_accuracy"), left_metrics.get("balanced_accuracy")
    )

    return {
        "comparison_id": comparison_id,
        "comparison_type": comparison_type,
        "comparison_family": comparison_type,
        "left_condition": left_condition,
        "right_condition": right_condition,
        "causal_status": causal_status,
        "comparison_status": status,
        "pairing": pairing_summary,
        "exact_pair_count": len(pairs),
        "left_full_condition_metrics": compute_accuracy_metrics(left_rows),
        "right_full_condition_metrics": compute_accuracy_metrics(right_rows),
        "left_paired_metrics": left_metrics,
        "right_paired_metrics": right_metrics,
        "strict_accuracy_difference_right_minus_left": strict_difference,
        "valid_only_accuracy_difference_right_minus_left": valid_difference,
        "balanced_accuracy_difference_right_minus_left": balanced_difference,
        "stage_changes": stage_changes,
        "paired_outcomes": outcomes,
        "mcnemar_p_value": mcnemar_p,
        "mcnemar_test": {
            "test": "two-sided exact McNemar/binomial test",
            "left_only_correct": outcomes["left_only_correct"],
            "right_only_correct": outcomes["right_only_correct"],
            "p_value": mcnemar_p,
        },
        "clustered_bootstrap": bootstrap,
        "content_identity": {
            "argument_content_pair_count": content_available,
            "argument_content_match_count": content_matches,
            "argument_content_match_rate": safe_divide(
                content_matches, content_available
            ),
            "abstract_pair_count": abstract_available,
            "abstract_match_count": abstract_matches,
            "abstract_match_rate": safe_divide(abstract_matches, abstract_available),
        },
        "bias_comparison": {
            "left_pro_con": left_bias,
            "right_pro_con": right_bias,
            "pro_selection_rate_difference_right_minus_left": _paired_scalar_difference(
                right_bias.get("pro_selection", {}).get("rate"),
                left_bias.get("pro_selection", {}).get("rate"),
            ),
            "false_positive_rate_difference_right_minus_left": _paired_scalar_difference(
                right_bias.get("false_positive_rate"),
                left_bias.get("false_positive_rate"),
            ),
            "false_negative_rate_difference_right_minus_left": _paired_scalar_difference(
                right_bias.get("false_negative_rate"),
                left_bias.get("false_negative_rate"),
            ),
            "left_ab": left_ab,
            "right_ab": right_ab,
            "displayed_a_selection_rate_difference_right_minus_left": _paired_scalar_difference(
                right_ab.get("displayed_a_selection", {}).get("rate"),
                left_ab.get("displayed_a_selection", {}).get("rate"),
            ),
            "left_order": left_order,
            "right_order": right_order,
            "left_verbosity": left_verbosity,
            "right_verbosity": right_verbosity,
            "longer_side_selection_rate_difference_right_minus_left": _paired_scalar_difference(
                right_verbosity.get("longer_side_selected", {}).get("rate"),
                left_verbosity.get("longer_side_selected", {}).get("rate"),
            ),
        },
        "logprob_comparison": {
            "left": left_logprob,
            "right": right_logprob,
        },
        "effect_direction": (
            "right_higher"
            if strict_difference is not None and strict_difference > 0
            else "left_higher"
            if strict_difference is not None and strict_difference < 0
            else "equal"
            if strict_difference == 0
            else "unavailable"
        ),
        "interpretation_guardrail": (
            "A numerical difference should be interpreted with exact-match coverage, "
            "the PMID-clustered confidence interval, McNemar discordance, and the "
            "declared causal status."
        ),
    }


def benjamini_hochberg_correction(
    comparisons: Sequence[Mapping[str, Any]],
) -> Table:
    output: Table = []
    grouped: Dict[str, List[Tuple[int, float]]] = defaultdict(list)

    for index, comparison in enumerate(comparisons):
        raw = comparison.get("mcnemar_p_value")
        if raw is None and isinstance(comparison.get("mcnemar_test"), Mapping):
            raw = comparison["mcnemar_test"].get("p_value")
        try:
            p_value = float(raw) if raw is not None else None
        except (TypeError, ValueError):
            p_value = None
        if p_value is not None and not 0.0 <= p_value <= 1.0:
            p_value = None
        family = str(
            comparison.get("comparison_family")
            or comparison.get("comparison_type")
            or "all_comparisons"
        )
        output.append(
            {
                "comparison_id": comparison.get("comparison_id", f"comparison_{index + 1}"),
                "comparison_family": family,
                "left_condition": comparison.get("left_condition"),
                "right_condition": comparison.get("right_condition"),
                "raw_p_value": p_value,
                "adjusted_p_value": None,
                "rank_within_family": None,
                "tests_in_family": None,
                "correction": "Benjamini-Hochberg FDR",
                "status": "eligible" if p_value is not None else "unavailable",
            }
        )
        if p_value is not None:
            grouped[family].append((index, p_value))

    for family, values in grouped.items():
        ordered = sorted(values, key=lambda item: (item[1], item[0]))
        test_count = len(ordered)
        adjusted_by_index: Dict[int, float] = {}
        running_minimum = 1.0
        for reverse_position in range(test_count - 1, -1, -1):
            original_index, p_value = ordered[reverse_position]
            rank = reverse_position + 1
            running_minimum = min(
                running_minimum, p_value * test_count / rank
            )
            adjusted_by_index[original_index] = min(1.0, running_minimum)
        for rank, (original_index, _) in enumerate(ordered, start=1):
            output[original_index]["adjusted_p_value"] = adjusted_by_index[original_index]
            output[original_index]["rank_within_family"] = rank
            output[original_index]["tests_in_family"] = test_count
            output[original_index]["status"] = "corrected"

    return output


# =============================================================================
# 10. Analysis section 1: legacy baseline, statement, and interactive
# =============================================================================


def identify_legacy_conditions(
    catalog: Sequence[Mapping[str, Any]],
) -> JSONDict:
    family_specs = {
        "baseline": lambda row: row.get("family") == "baseline",
        "statement": lambda row: row.get("family") == "statement",
        "interactive": lambda row: (
            row.get("family") == "interactive"
            and row.get("variant") in {None, "ABA"}
        ),
    }
    selected: Dict[str, Optional[str]] = {}
    entries: Dict[str, Any] = {}
    ambiguities: Dict[str, List[str]] = {}
    missing: List[str] = []

    for family, predicate in family_specs.items():
        candidates = [
            row
            for row in catalog
            if row.get("generation") == "legacy" and predicate(row)
        ]
        candidates.sort(
            key=lambda row: (
                -int(row.get("unique_stage_pmid_count") or 0),
                -int(row.get("row_count") or 0),
                str(row.get("condition_id")),
            )
        )
        if not candidates:
            selected[family] = None
            entries[family] = None
            missing.append(family)
            continue
        chosen = candidates[0]
        condition_id = str(chosen.get("condition_id"))
        selected[family] = condition_id
        record_complete = (
            chosen.get("unique_stage_pmid_count") == EXPECTED_TOTAL_RECORDS
            and chosen.get("row_count") == EXPECTED_TOTAL_RECORDS
        )
        provenance_status = chosen.get("provenance_status")
        entries[family] = {
            "condition_id": condition_id,
            "display_name": chosen.get("display_name"),
            "source_files": chosen.get("source_files", []),
            "row_count": chosen.get("row_count"),
            "unique_stage_pmid_count": chosen.get("unique_stage_pmid_count"),
            "record_complete": record_complete,
            "prediction_paths": chosen.get("prediction_paths", []),
            "judge_model": chosen.get("judge_model"),
            "debater_model": chosen.get("debater_model"),
            "manual_in_judge_prompt": chosen.get("manual_in_judge_prompt"),
            "assigned_tags_in_judge_prompt": chosen.get(
                "assigned_tags_in_judge_prompt"
            ),
            "assigned_tags_in_debater_prompt": chosen.get(
                "assigned_tags_in_debater_prompt"
            ),
            "parser_type": chosen.get("parser_type"),
            "confidence_available": chosen.get("confidence_available"),
            "provenance_status": provenance_status,
            "historical_comparison_role": "descriptive_historical",
            "primary_comparison_eligible": False,
            "audit_status": (
                "record_and_schema_audited_legacy_provenance_cautious"
                if record_complete
                else "incomplete_or_noncanonical_legacy_file"
            ),
            "limitations": chosen.get("limitations", []),
        }
        if len(candidates) > 1:
            ambiguities[family] = [
                str(candidate.get("condition_id")) for candidate in candidates
            ]

    return {
        "conditions": selected,
        "entries": entries,
        "missing_families": missing,
        "ambiguities": ambiguities,
        "all_three_available": not missing,
        "status": "available" if not missing else "partial" if len(missing) < 3 else "unavailable",
        "comparison_policy": (
            "Legacy conditions are analyzed as a separate historical family. Exact "
            "candidate pairing is required, and cross-family differences remain "
            "descriptive because separate generation scripts/prompts and unresolved "
            "historical provenance can introduce additional factors."
        ),
    }


def analyze_legacy_progression(
    rows: Sequence[Mapping[str, Any]],
    catalog: Sequence[Mapping[str, Any]],
    integrity: Mapping[str, Any],
    context: Mapping[str, Any],
) -> JSONDict:
    identified = identify_legacy_conditions(catalog)
    conditions = identified.get("conditions", {})
    condition_summaries: Table = []
    condition_stage_metrics: Table = []
    condition_bias_metrics: Table = []
    condition_logprob_metrics: Table = []

    for family in ("baseline", "statement", "interactive"):
        condition_id = conditions.get(family)
        if not condition_id:
            continue
        condition_rows = _rows_for_condition(rows, condition_id)
        metrics = compute_accuracy_metrics(condition_rows)
        stages = compute_stage_metrics(condition_rows)
        pro_con = compute_pro_con_bias(condition_rows)
        ab_label = compute_ab_label_bias(condition_rows)
        order = compute_speaking_order_bias(condition_rows)
        verbosity = compute_verbosity_bias(condition_rows)
        logprob = compute_logprob_metrics_for_condition(condition_rows)
        by_stage = {stage["stage"]: stage for stage in stages}
        unrelated = by_stage.get("Round 2: Unrelated Tag", {})
        similar = by_stage.get("Round 3: Similar Tag", {})
        similar_minus_unrelated = _paired_scalar_difference(
            similar.get("strict_accuracy"), unrelated.get("strict_accuracy")
        )

        condition_summaries.append(
            {
                "family": family,
                "condition_id": condition_id,
                "display_name": _condition_display_name(condition_id),
                **metrics,
                "similar_minus_unrelated_strict_accuracy": similar_minus_unrelated,
                "confidence_available": logprob.get("available"),
                "analysis_role": "descriptive_historical",
            }
        )
        for stage in stages:
            condition_stage_metrics.append(
                {
                    "family": family,
                    "condition_id": condition_id,
                    **stage,
                }
            )
        condition_bias_metrics.append(
            {
                "family": family,
                "condition_id": condition_id,
                "pro_con": pro_con,
                "ab_label": ab_label,
                "speaking_order": order,
                "verbosity": verbosity,
            }
        )
        condition_logprob_metrics.append(
            {
                "family": family,
                "condition_id": condition_id,
                **logprob,
            }
        )

    comparison_specs = (
        (
            "baseline_to_statement",
            conditions.get("baseline"),
            conditions.get("statement"),
            "Do independent PRO/CON essays improve the legacy judge over baseline?",
        ),
        (
            "baseline_to_interactive",
            conditions.get("baseline"),
            conditions.get("interactive"),
            "Does the legacy three-turn debate improve the judge over baseline?",
        ),
        (
            "statement_to_interactive",
            conditions.get("statement"),
            conditions.get("interactive"),
            "Does direct rebuttal improve on independent side-by-side essays?",
        ),
    )
    comparisons: Table = []
    for comparison_name, left_condition, right_condition, question in comparison_specs:
        if left_condition and right_condition:
            comparison = compute_paired_comparison(
                left_condition,
                right_condition,
                rows,
                "legacy_progression",
                "descriptive_confounded",
                context,
            )
        else:
            comparison = {
                "comparison_id": comparison_name,
                "comparison_type": "legacy_progression",
                "comparison_family": "legacy_progression",
                "left_condition": left_condition,
                "right_condition": right_condition,
                "causal_status": "descriptive_confounded",
                "comparison_status": "unavailable",
                "reason": "A required legacy condition is absent.",
                "mcnemar_p_value": None,
            }
        comparison["comparison_name"] = comparison_name
        comparison["research_question"] = question
        comparison["legacy_interpretation_note"] = (
            "Exact pairing controls candidate identity, but it does not remove prompt, "
            "input, parser, retry, or script-generation differences."
        )
        comparisons.append(comparison)

    corrections = benjamini_hochberg_correction(comparisons)
    takeaways: List[str] = []
    for summary in condition_summaries:
        strict = summary.get("strict_accuracy")
        balanced = summary.get("balanced_accuracy")
        coverage = summary.get("valid_prediction_coverage")
        if strict is not None:
            takeaways.append(
                f"{summary['display_name']}: strict accuracy {strict * 100:.2f}%, "
                f"balanced accuracy {balanced * 100:.2f}%"
                f"{f', valid-output coverage {coverage * 100:.2f}%' if coverage is not None else ''}."
            )
        gap = summary.get("similar_minus_unrelated_strict_accuracy")
        if gap is not None:
            takeaways.append(
                f"For {summary['display_name']}, Similar Tag accuracy was "
                f"{gap * 100:+.2f} percentage points relative to Unrelated Tag accuracy."
            )

    for comparison in comparisons:
        difference = comparison.get("strict_accuracy_difference_right_minus_left")
        pair_count = comparison.get("exact_pair_count", 0)
        interval = comparison.get("clustered_bootstrap", {}).get(
            "strict_confidence_interval_95"
        )
        if difference is None:
            takeaways.append(
                f"{comparison['comparison_name']}: no exact paired effect estimate is available."
            )
            continue
        interval_text = (
            f", 95% PMID-clustered bootstrap CI "
            f"[{interval[0] * 100:+.2f}, {interval[1] * 100:+.2f}] pp"
            if interval is not None and None not in interval
            else ""
        )
        takeaways.append(
            f"{comparison['comparison_name']} changed strict accuracy by "
            f"{difference * 100:+.2f} percentage points on {pair_count:,} exact pairs"
            f"{interval_text}; this is a descriptive, confounded historical comparison."
        )

    for bias in condition_bias_metrics:
        pro_con = bias["pro_con"]
        interval = pro_con.get("error_asymmetry_confidence_interval_95")
        difference = pro_con.get("false_positive_minus_false_negative_rate")
        if difference is not None and interval is not None:
            if interval[0] > 0:
                direction = "more false-positive/PRO-side errors"
            elif interval[1] < 0:
                direction = "more false-negative/CON-side errors"
            else:
                direction = "no clear directional FPR/FNR asymmetry"
            takeaways.append(
                f"{_condition_display_name(bias['condition_id'])} showed {direction} "
                f"(FPR−FNR {difference * 100:+.2f} pp)."
            )

    if condition_logprob_metrics and all(
        not item.get("available") for item in condition_logprob_metrics
    ):
        takeaways.append(
            "The audited legacy conditions expose no usable teacher-forced confidence "
            "fields, so log-probability accuracy and calibration are not applicable."
        )

    limitations = [
        "Legacy files are historical conditions and are not pooled with robust runs.",
        "Exact candidate matching does not make separately generated prompts, arguments, parsers, or retries identical.",
        "In legacy statement, displayed A and first position are confounded.",
        "In legacy ABA, A is first, last, and receives two turns; those effects cannot be separated.",
        "Raw Yes/PRO selection is not interpreted as bias without FPR/FNR or a controlled intervention.",
        "Unknown outputs count as failures in strict metrics and are excluded only in explicitly labelled valid-only metrics.",
    ]
    expectations = [
        "Debate may improve the smaller judge by presenting both sides and simplifying medical evidence.",
        "Independent side-by-side statements may provide most of the benefit even without explicit rebuttal.",
        "Similar incorrect tags are expected to be harder than unrelated incorrect tags.",
        "Debate can also amplify persuasive but incorrect PRO arguments or position/verbosity effects.",
    ]

    return {
        "section_id": "legacy_progression",
        "title": "Legacy baseline → statement → interactive",
        "status": identified.get("status"),
        "identified_conditions": identified,
        "condition_metrics": condition_summaries,
        "stage_metrics": condition_stage_metrics,
        "bias_metrics": condition_bias_metrics,
        "logprob_metrics": condition_logprob_metrics,
        "comparisons": comparisons,
        "multiple_testing": corrections,
        "takeaways": takeaways,
        "expectations": expectations,
        "limitations": limitations,
        "integrity_context": {
            "has_errors": integrity.get("has_errors"),
            "has_warnings": integrity.get("has_warnings"),
            "include_unverified_legacy_requested": context.get(
                "include_unverified_legacy"
            ),
        },
        "primary_comparison_eligible": False,
        "analysis_policy": identified.get("comparison_policy"),
    }


# BEGIN PRIVATE HELPERS FOR SECTIONS 11-14
# These helpers are intentionally private and schema-tolerant. They let the
# section analyses work with both normalized scalar columns and retained raw
# records without changing any section 1-10 implementation.


def _s1114_get(mapping: Mapping[str, Any], path: str, default: Any = None) -> Any:
    current: Any = mapping
    for part in path.split("."):
        if not isinstance(current, Mapping) or part not in current:
            return default
        current = current[part]
    return current


def _s1114_sources(row: Mapping[str, Any]) -> List[Mapping[str, Any]]:
    sources: List[Mapping[str, Any]] = [row]
    for key in ("raw_record", "source_record", "record", "original_record", "payload"):
        value = row.get(key)
        if isinstance(value, Mapping) and value is not row:
            sources.append(value)
    return sources


def _s1114_first(row: Mapping[str, Any], *paths: str, default: Any = None) -> Any:
    sentinel = object()
    for source in _s1114_sources(row):
        for path in paths:
            value = _s1114_get(source, path, sentinel)
            if value is not sentinel and value is not None:
                return value
    return default


def _s1114_bool(value: Any) -> Optional[bool]:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and value in (0, 1):
        return bool(value)
    if isinstance(value, str):
        text = value.strip().casefold()
        if text in {"true", "yes", "1", "y", "pro", "a"}:
            return True
        if text in {"false", "no", "0", "n", "con", "b"}:
            return False
    return None


def _s1114_binary(value: Any) -> Optional[str]:
    if isinstance(value, bool):
        return "Yes" if value else "No"
    if isinstance(value, (int, float)) and value in (0, 1):
        return "Yes" if bool(value) else "No"
    if isinstance(value, str):
        text = value.strip().casefold()
        if text in {"yes", "y", "true", "1", "pro", "belongs", "positive"}:
            return "Yes"
        if text in {"no", "n", "false", "0", "con", "does not belong", "negative"}:
            return "No"
    return None


def _s1114_truth(row: Mapping[str, Any]) -> Optional[str]:
    return _s1114_binary(
        _s1114_first(
            row,
            "ground_truth",
            "expected_answer",
            "expected_label",
            "truth",
            "label",
        )
    )


def _s1114_prediction(row: Mapping[str, Any]) -> Optional[str]:
    return _s1114_binary(
        _s1114_first(
            row,
            "prediction",
            "model_prediction",
            "normalized_prediction",
            "judge_prediction",
            "verdict",
            "answer",
        )
    )


def _s1114_prediction_text(row: Mapping[str, Any]) -> str:
    prediction = _s1114_prediction(row)
    if prediction is not None:
        return prediction
    raw = _s1114_first(
        row,
        "prediction",
        "model_prediction",
        "normalized_prediction",
        "judge_prediction",
        "verdict",
        "answer",
        default="Unknown",
    )
    text = str(raw).strip() if raw is not None else "Unknown"
    return text or "Unknown"


def _s1114_filename(row: Mapping[str, Any]) -> str:
    value = _s1114_first(
        row,
        "source_file",
        "filename",
        "file_name",
        "source_path",
        "result_file",
        default="",
    )
    try:
        return Path(str(value)).name
    except Exception:
        return str(value)


def _s1114_decision_text(row: Mapping[str, Any]) -> str:
    values = [
        _s1114_first(row, key, default="")
        for key in (
            "prediction_path",
            "judge_path",
            "decision_path",
            "condition_id",
            "condition",
            "order",
            "debate_order",
            "variant",
        )
    ]
    return " ".join(str(value) for value in values if value).casefold()


def _s1114_has_order(row: Mapping[str, Any], order: str) -> bool:
    text = _s1114_decision_text(row)
    target = order.casefold()
    if target == "swapped":
        return "swapped" in text
    tokens = re.findall(r"[a-z0-9]+", text)
    if target == "aba":
        return "aba" in tokens and "swapped" not in tokens
    if target == "bab":
        return "bab" in tokens and "swapped" not in tokens
    return target in tokens


def _s1114_rows_for_file(
    rows: Sequence[Mapping[str, Any]],
    filename: str,
    order: Optional[str] = None,
) -> Table:
    expected = Path(filename).name.casefold()
    selected = [row for row in rows if _s1114_filename(row).casefold() == expected]
    if not selected:
        stem = Path(filename).stem.casefold()
        selected = [
            row
            for row in rows
            if stem in (_s1114_filename(row) + " " + _s1114_decision_text(row)).casefold()
        ]
    if order is not None:
        selected = [row for row in selected if _s1114_has_order(row, order)]
    return [dict(row) for row in selected]


def _s1114_catalog_sequence(catalog: Any) -> List[Mapping[str, Any]]:
    if isinstance(catalog, Mapping):
        for key in ("conditions", "catalog", "rows", "entries"):
            value = catalog.get(key)
            if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
                return [item for item in value if isinstance(item, Mapping)]
        return [value for value in catalog.values() if isinstance(value, Mapping)]
    if isinstance(catalog, Sequence) and not isinstance(catalog, (str, bytes)):
        return [item for item in catalog if isinstance(item, Mapping)]
    return []


def _s1114_blob(value: Any) -> str:
    if isinstance(value, Mapping):
        return " ".join(f"{key} {_s1114_blob(item)}" for key, item in value.items())
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return " ".join(_s1114_blob(item) for item in value)
    return str(value)


def _s1114_catalog_matches(
    catalog: Any,
    filename: Optional[str] = None,
    required_tokens: Sequence[str] = (),
    excluded_tokens: Sequence[str] = (),
) -> Table:
    result: Table = []
    expected = Path(filename).name.casefold() if filename else None
    expected_stem = Path(filename).stem.casefold() if filename else None
    for item in _s1114_catalog_sequence(catalog):
        blob = _s1114_blob(item).casefold()
        if expected and expected not in blob and expected_stem not in blob:
            continue
        if any(token.casefold() not in blob for token in required_tokens):
            continue
        if any(token.casefold() in blob for token in excluded_tokens):
            continue
        result.append(dict(item))
    return result


def _s1114_norm_text(value: Any) -> str:
    text = unicodedata.normalize("NFKC", str(value or ""))
    return " ".join(text.casefold().split())


def _s1114_stage(row: Mapping[str, Any]) -> str:
    return str(_s1114_first(row, "stage", "round", "dataset_stage", default="Unknown stage"))


def _s1114_stage_kind(row: Mapping[str, Any]) -> str:
    text = _s1114_stage(row).casefold()
    if "true" in text or "positive" in text or "round 1" in text:
        return "true_tag"
    if "unrelated" in text or "random" in text or "round 2" in text:
        return "unrelated_tag"
    if "similar" in text or "hard" in text or "round 3" in text:
        return "similar_tag"
    return _s1114_norm_text(text) or "unknown"


def _s1114_identity(row: Mapping[str, Any]) -> Optional[Tuple[str, str, str, str]]:
    pmid = _s1114_first(row, "pmid", "PMID", "article_id", "id")
    candidate = _s1114_first(row, "candidate_tag", "candidate", "mesh_tag", "tag")
    truth = _s1114_truth(row)
    if pmid is None or candidate is None or truth is None:
        return None
    return (
        _s1114_norm_text(_s1114_stage(row)),
        _s1114_norm_text(pmid),
        _s1114_norm_text(candidate),
        truth,
    )


def _s1114_base_identity(row: Mapping[str, Any]) -> Optional[Tuple[str, str]]:
    pmid = _s1114_first(row, "pmid", "PMID", "article_id", "id")
    if pmid is None:
        return None
    return (_s1114_norm_text(_s1114_stage(row)), _s1114_norm_text(pmid))


def _s1114_unique_map(rows: Sequence[Mapping[str, Any]]) -> Tuple[Dict[Any, Mapping[str, Any]], int]:
    buckets: Dict[Any, List[Mapping[str, Any]]] = defaultdict(list)
    skipped = 0
    for row in rows:
        key = _s1114_identity(row)
        if key is None:
            skipped += 1
            continue
        buckets[key].append(row)
    duplicates = sum(len(items) - 1 for items in buckets.values() if len(items) > 1)
    return {key: items[0] for key, items in buckets.items() if len(items) == 1}, duplicates + skipped


def _s1114_core_metrics(rows: Sequence[Mapping[str, Any]]) -> JSONDict:
    total = len(rows)
    valid = 0
    correct = 0
    tp = tn = fp = fn = 0
    truth_yes = truth_no = 0
    valid_truth_yes = valid_truth_no = 0
    prediction_counts: Counter[str] = Counter()
    fallback_count = 0
    fallback_known = 0

    for row in rows:
        truth = _s1114_truth(row)
        prediction = _s1114_prediction(row)
        prediction_counts[_s1114_prediction_text(row)] += 1
        fallback = _s1114_bool(_s1114_first(row, "needed_fallback", "fallback_used"))
        if fallback is not None:
            fallback_known += 1
            fallback_count += int(fallback)
        if truth == "Yes":
            truth_yes += 1
        elif truth == "No":
            truth_no += 1
        if prediction not in VALID_BINARY_LABELS or truth not in VALID_BINARY_LABELS:
            continue
        valid += 1
        if truth == "Yes":
            valid_truth_yes += 1
        else:
            valid_truth_no += 1
        if prediction == truth:
            correct += 1
        if truth == "Yes" and prediction == "Yes":
            tp += 1
        elif truth == "No" and prediction == "No":
            tn += 1
        elif truth == "No" and prediction == "Yes":
            fp += 1
        elif truth == "Yes" and prediction == "No":
            fn += 1

    tpr_strict = tp / truth_yes if truth_yes else None
    tnr_strict = tn / truth_no if truth_no else None
    tpr_valid = tp / valid_truth_yes if valid_truth_yes else None
    tnr_valid = tn / valid_truth_no if valid_truth_no else None
    strict_balanced = (
        (tpr_strict + tnr_strict) / 2
        if tpr_strict is not None and tnr_strict is not None
        else None
    )
    valid_balanced = (
        (tpr_valid + tnr_valid) / 2
        if tpr_valid is not None and tnr_valid is not None
        else None
    )
    yes_predictions = sum(
        1 for row in rows if _s1114_prediction(row) == "Yes"
    )

    return {
        "total_records": total,
        "valid_predictions": valid,
        "unknown_or_invalid_predictions": total - valid,
        "coverage": valid / total if total else None,
        "strict_accuracy": correct / total if total else None,
        "valid_only_accuracy": correct / valid if valid else None,
        "balanced_accuracy": strict_balanced,
        "valid_only_balanced_accuracy": valid_balanced,
        "sensitivity_tpr": tpr_strict,
        "specificity_tnr": tnr_strict,
        "false_positive_rate": fp / truth_no if truth_no else None,
        "false_negative_rate": fn / truth_yes if truth_yes else None,
        "precision_yes": tp / (tp + fp) if tp + fp else None,
        "yes_prediction_rate": yes_predictions / valid if valid else None,
        "confusion_matrix": {"tp": tp, "tn": tn, "fp": fp, "fn": fn},
        "truth_counts": {"Yes": truth_yes, "No": truth_no},
        "prediction_counts": dict(sorted(prediction_counts.items())),
        "fallback_known_records": fallback_known,
        "fallback_count": fallback_count,
        "fallback_rate": fallback_count / fallback_known if fallback_known else None,
    }


def _s1114_metrics(rows: Sequence[Mapping[str, Any]]) -> JSONDict:
    result = _s1114_core_metrics(rows)
    by_stage: JSONDict = {}
    stages: Dict[str, List[Mapping[str, Any]]] = defaultdict(list)
    for row in rows:
        stages[_s1114_stage(row)].append(row)
    for stage, stage_rows in sorted(stages.items()):
        by_stage[stage] = _s1114_core_metrics(stage_rows)
    result["stage_metrics"] = by_stage
    return result


def _s1114_exact_binomial_p(left_only: int, right_only: int) -> float:
    """Return the exact two-sided binomial p-value used by McNemar's test.

    Under the null hypothesis, either direction of a discordant pair has
    probability 0.5.  For this symmetric distribution, the exact two-sided
    p-value is twice the lower-tail probability at the smaller discordant
    count, capped at 1.  Log-space evaluation avoids converting enormous
    binomial coefficients or powers of two directly to floats.
    """
    import math

    left = int(left_only)
    right = int(right_only)
    if left < 0 or right < 0:
        raise ValueError("Discordant-pair counts must be non-negative.")

    n = left + right
    if n == 0:
        return 1.0

    k = min(left, right)
    log_two = math.log(2.0)
    log_n_factorial = math.lgamma(n + 1.0)

    log_probabilities = [
        log_n_factorial
        - math.lgamma(i + 1.0)
        - math.lgamma(n - i + 1.0)
        - n * log_two
        for i in range(k + 1)
    ]
    largest_log_probability = max(log_probabilities)
    scaled_tail = math.fsum(
        math.exp(value - largest_log_probability)
        for value in log_probabilities
    )
    log_two_sided_p = (
        log_two
        + largest_log_probability
        + math.log(scaled_tail)
    )

    if log_two_sided_p >= 0.0:
        return 1.0
    return math.exp(log_two_sided_p)


def _s1114_bootstrap_ci(
    pairs: Sequence[Tuple[Mapping[str, Any], Mapping[str, Any]]],
    context: Mapping[str, Any],
) -> Optional[Tuple[float, float]]:
    import random

    by_pmid: Dict[str, List[float]] = defaultdict(list)
    for left, right in pairs:
        pmid = _s1114_norm_text(_s1114_first(left, "pmid", "PMID", default=""))
        left_correct = float(_s1114_prediction(left) == _s1114_truth(left))
        right_correct = float(_s1114_prediction(right) == _s1114_truth(right))
        by_pmid[pmid].append(right_correct - left_correct)
    clusters = list(by_pmid.values())
    if not clusters:
        return None
    iterations_value = context.get(
        "bootstrap_iterations",
        context.get("n_bootstrap", context.get("bootstrap_samples", 1_000)),
    )
    try:
        iterations = max(200, int(iterations_value))
    except (TypeError, ValueError):
        iterations = 1_000
    seed_value = context.get("random_seed", context.get("seed", 2026))
    try:
        seed = int(seed_value)
    except (TypeError, ValueError):
        seed = 2026
    rng = random.Random(seed)
    values: List[float] = []
    for _ in range(iterations):
        sampled = [clusters[rng.randrange(len(clusters))] for _ in clusters]
        flattened = [value for cluster in sampled for value in cluster]
        values.append(sum(flattened) / len(flattened))
    values.sort()
    low_index = max(0, int(0.025 * (len(values) - 1)))
    high_index = min(len(values) - 1, int(0.975 * (len(values) - 1)))
    return (values[low_index], values[high_index])


def _s1114_content_signature(row: Mapping[str, Any], mode: str) -> Optional[str]:
    mode = mode.casefold()
    if mode == "statement":
        keys = ("pro_argument", "con_argument", "arg_a", "arg_b")
    elif mode == "aba":
        keys = (
            "debate_ABA",
            "transcript_ABA",
            "aba_transcript",
            "a_turn1",
            "b_turn1",
            "a_turn2",
        )
    elif mode == "bab":
        keys = (
            "debate_BAB",
            "transcript_BAB",
            "bab_transcript",
            "b_turn1_BAB",
            "a_turn1_BAB",
            "b_turn2_BAB",
            "b_turn1",
            "a_turn1",
            "b_turn2",
        )
    else:
        return None
    values: JSONDict = {}
    for key in keys:
        value = _s1114_first(row, key, default=MISSING)
        if value is not MISSING and value not in (None, "", [], {}):
            values[key.casefold()] = value
    if not values:
        return None
    try:
        return json.dumps(values, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    except (TypeError, ValueError):
        return repr(values)


def _s1114_verify_content(
    pairs: Sequence[Tuple[Mapping[str, Any], Mapping[str, Any]]],
    mode: Optional[str],
) -> JSONDict:
    if not mode:
        return {
            "mode": None,
            "checked_pairs": 0,
            "matching_pairs": 0,
            "mismatching_pairs": 0,
            "unavailable_pairs": len(pairs),
            "all_checked_content_identical": None,
        }
    checked = matching = mismatching = unavailable = 0
    for left, right in pairs:
        left_signature = _s1114_content_signature(left, mode)
        right_signature = _s1114_content_signature(right, mode)
        if left_signature is None or right_signature is None:
            unavailable += 1
            continue
        checked += 1
        if left_signature == right_signature:
            matching += 1
        else:
            mismatching += 1
    return {
        "mode": mode,
        "checked_pairs": checked,
        "matching_pairs": matching,
        "mismatching_pairs": mismatching,
        "unavailable_pairs": unavailable,
        "all_checked_content_identical": mismatching == 0 if checked else None,
    }


def _s1114_pair_rows(
    left_rows: Sequence[Mapping[str, Any]],
    right_rows: Sequence[Mapping[str, Any]],
) -> Tuple[List[Tuple[Mapping[str, Any], Mapping[str, Any]]], JSONDict]:
    left_map, left_problem_count = _s1114_unique_map(left_rows)
    right_map, right_problem_count = _s1114_unique_map(right_rows)
    shared = sorted(set(left_map) & set(right_map))
    pairs = [(left_map[key], right_map[key]) for key in shared]

    left_base: Dict[Any, set] = defaultdict(set)
    right_base: Dict[Any, set] = defaultdict(set)
    for key in left_map:
        left_base[key[:2]].add(key[2:])
    for key in right_map:
        right_base[key[:2]].add(key[2:])
    shared_base = set(left_base) & set(right_base)
    candidate_mismatch_bases = sum(
        1 for key in shared_base if not (left_base[key] & right_base[key])
    )
    coverage = {
        "left_records": len(left_rows),
        "right_records": len(right_rows),
        "left_unique_exact_keys": len(left_map),
        "right_unique_exact_keys": len(right_map),
        "exact_matched_records": len(pairs),
        "left_match_rate": len(pairs) / len(left_map) if left_map else None,
        "right_match_rate": len(pairs) / len(right_map) if right_map else None,
        "shared_stage_pmid_keys": len(shared_base),
        "candidate_mismatch_stage_pmid_keys": candidate_mismatch_bases,
        "left_unpairable_or_duplicate_records": left_problem_count,
        "right_unpairable_or_duplicate_records": right_problem_count,
    }
    return pairs, coverage


def _s1114_paired_comparison(
    left_rows: Sequence[Mapping[str, Any]],
    right_rows: Sequence[Mapping[str, Any]],
    left_name: str,
    right_name: str,
    context: Mapping[str, Any],
    causal_status: str,
    content_mode: Optional[str] = None,
) -> JSONDict:
    pairs, coverage = _s1114_pair_rows(left_rows, right_rows)
    left_correct = right_correct = both_correct = both_wrong = fixed = broken = 0
    agreements = 0
    transitions: Counter[str] = Counter()
    valid_pair_count = valid_left_correct = valid_right_correct = 0

    for left, right in pairs:
        truth = _s1114_truth(left)
        left_prediction = _s1114_prediction(left)
        right_prediction = _s1114_prediction(right)
        left_is_correct = left_prediction == truth
        right_is_correct = right_prediction == truth
        left_correct += int(left_is_correct)
        right_correct += int(right_is_correct)
        both_correct += int(left_is_correct and right_is_correct)
        both_wrong += int(not left_is_correct and not right_is_correct)
        fixed += int(not left_is_correct and right_is_correct)
        broken += int(left_is_correct and not right_is_correct)
        agreements += int(left_prediction == right_prediction)
        transitions[f"{left_prediction or 'Unknown'}->{right_prediction or 'Unknown'}"] += 1
        if left_prediction is not None and right_prediction is not None:
            valid_pair_count += 1
            valid_left_correct += int(left_is_correct)
            valid_right_correct += int(right_is_correct)

    n = len(pairs)
    point_difference = (right_correct - left_correct) / n if n else None
    ci = _s1114_bootstrap_ci(pairs, context) if n else None
    content_verification = _s1114_verify_content(pairs, content_mode)
    effective_status = causal_status
    if content_mode:
        if content_verification["mismatching_pairs"]:
            effective_status = "confounded: stored content mismatch detected"
        elif not content_verification["checked_pairs"]:
            effective_status = causal_status + "; stored content unavailable for verification"
        elif content_verification["unavailable_pairs"]:
            effective_status = causal_status + "; content verified only for a subset"

    stage_pairs: Dict[str, List[Tuple[Mapping[str, Any], Mapping[str, Any]]]] = defaultdict(list)
    for pair in pairs:
        stage_pairs[_s1114_stage(pair[0])].append(pair)
    stage_changes: JSONDict = {}
    for stage, items in sorted(stage_pairs.items()):
        left_hits = sum(_s1114_prediction(left) == _s1114_truth(left) for left, _ in items)
        right_hits = sum(_s1114_prediction(right) == _s1114_truth(right) for _, right in items)
        stage_changes[stage] = {
            "matched_records": len(items),
            "left_accuracy": left_hits / len(items),
            "right_accuracy": right_hits / len(items),
            "accuracy_difference_right_minus_left": (right_hits - left_hits) / len(items),
        }

    return {
        "left_condition": left_name,
        "right_condition": right_name,
        "causal_status": effective_status,
        "matching": coverage,
        "left_metrics_all_records": _s1114_metrics(left_rows),
        "right_metrics_all_records": _s1114_metrics(right_rows),
        "paired": {
            "matched_records": n,
            "left_accuracy": left_correct / n if n else None,
            "right_accuracy": right_correct / n if n else None,
            "accuracy_difference_right_minus_left": point_difference,
            "clustered_bootstrap_95ci": ci,
            "prediction_agreement_rate": agreements / n if n else None,
            "prediction_flip_rate": (n - agreements) / n if n else None,
            "both_correct": both_correct,
            "both_incorrect": both_wrong,
            "fixed_by_right": fixed,
            "broken_by_right": broken,
            "mcnemar_exact_p": _s1114_exact_binomial_p(fixed, broken),
            "valid_on_both": valid_pair_count,
            "valid_only_left_accuracy": (
                valid_left_correct / valid_pair_count if valid_pair_count else None
            ),
            "valid_only_right_accuracy": (
                valid_right_correct / valid_pair_count if valid_pair_count else None
            ),
            "transitions": dict(sorted(transitions.items())),
            "stage_changes": stage_changes,
        },
        "content_verification": content_verification,
    }


def _s1114_side(value: Any) -> Optional[str]:
    if isinstance(value, str):
        text = value.strip().casefold()
        if text in {"pro", "yes", "positive", "belongs"} or "pro" == text:
            return "PRO"
        if text in {"con", "no", "negative", "does not belong"} or "contra" in text:
            return "CON"
    return None


def _s1114_a_side(row: Mapping[str, Any], presented: bool = True) -> Optional[str]:
    paths: List[str] = []
    if presented:
        paths.extend(("presented_a_side", "displayed_a_side", "label_a_side"))
    paths.extend(("a_side", "debater_a_side", "side_a"))
    direct = _s1114_side(_s1114_first(row, *paths))
    if direct:
        return direct
    for key in ("pro_is_a", "a_is_pro", "pro_is_debater_a"):
        flag = _s1114_bool(_s1114_first(row, key))
        if flag is not None:
            if presented and _s1114_has_order(row, "swapped"):
                return "CON" if flag else "PRO"
            return "PRO" if flag else "CON"
    return None


def _s1114_selected_side(row: Mapping[str, Any]) -> Optional[str]:
    prediction = _s1114_prediction(row)
    if prediction == "Yes":
        return "PRO"
    if prediction == "No":
        return "CON"
    return None


def _s1114_selected_label(row: Mapping[str, Any], presented: bool = True) -> Optional[str]:
    selected = _s1114_selected_side(row)
    a_side = _s1114_a_side(row, presented=presented)
    if selected is None or a_side is None:
        return None
    return "A" if selected == a_side else "B"


def _s1114_position_side(row: Mapping[str, Any], position: str) -> Optional[str]:
    direct_paths = {
        "first": ("first_speaker_side", "first_side", "opening_side"),
        "last": ("last_speaker_side", "last_side", "closing_side"),
        "two_turn": ("two_turn_side", "majority_turn_side", "extra_turn_side"),
    }
    direct = _s1114_side(_s1114_first(row, *direct_paths[position]))
    if direct:
        return direct

    pro_first = _s1114_bool(_s1114_first(row, "pro_first", "pro_is_first"))
    filename = _s1114_filename(row).casefold()
    if pro_first is not None and "statement" in filename and position == "first":
        return "PRO" if pro_first else "CON"

    a_side = _s1114_a_side(row, presented=True)
    if a_side is None:
        return None
    b_side = "CON" if a_side == "PRO" else "PRO"
    if _s1114_has_order(row, "aba"):
        return a_side if position in {"first", "last", "two_turn"} else None
    if _s1114_has_order(row, "bab"):
        return b_side if position in {"first", "last", "two_turn"} else None
    if _s1114_has_order(row, "swapped"):
        return a_side if position in {"first", "last", "two_turn"} else None
    if "statement" in filename and position == "first":
        return a_side
    return None


def _s1114_words(value: Any) -> int:
    if not isinstance(value, str):
        return 0
    return len(re.findall(r"\b\w+(?:[-']\w+)*\b", value, flags=re.UNICODE))


def _s1114_flat_strings(value: Any, prefix: str = "") -> List[Tuple[str, str]]:
    result: List[Tuple[str, str]] = []
    if isinstance(value, str):
        result.append((prefix.casefold(), value))
    elif isinstance(value, Mapping):
        speaker = value.get("speaker") or value.get("debater") or value.get("label")
        text = value.get("text") or value.get("argument") or value.get("content")
        if speaker is not None and isinstance(text, str):
            result.append((f"{prefix} {speaker}".casefold(), text))
        else:
            for key, item in value.items():
                result.extend(_s1114_flat_strings(item, f"{prefix}.{key}"))
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        for index, item in enumerate(value):
            result.extend(_s1114_flat_strings(item, f"{prefix}[{index}]"))
    return result


def _s1114_word_counts(row: Mapping[str, Any]) -> Optional[Tuple[int, int]]:
    direct_pro = _s1114_first(row, "pro_word_count", "words_pro")
    direct_con = _s1114_first(row, "con_word_count", "words_con")
    if isinstance(direct_pro, (int, float)) and isinstance(direct_con, (int, float)):
        return int(direct_pro), int(direct_con)

    pro_argument = _s1114_first(row, "pro_argument")
    con_argument = _s1114_first(row, "con_argument")
    if isinstance(pro_argument, str) and isinstance(con_argument, str):
        return _s1114_words(pro_argument), _s1114_words(con_argument)

    order = "aba" if _s1114_has_order(row, "aba") else "bab" if (
        _s1114_has_order(row, "bab") or _s1114_has_order(row, "swapped")
    ) else None
    transcript = None
    if order == "aba":
        transcript = _s1114_first(row, "debate_ABA", "transcript_ABA", "aba_transcript")
    elif order == "bab":
        transcript = _s1114_first(row, "debate_BAB", "transcript_BAB", "bab_transcript")
    if transcript is not None:
        a_words = b_words = pro_words = con_words = 0
        for path, text in _s1114_flat_strings(transcript):
            count = _s1114_words(text)
            tokens = set(re.findall(r"[a-z]+", path))
            if "pro" in tokens:
                pro_words += count
            elif "con" in tokens or "contra" in tokens:
                con_words += count
            elif "a" in tokens or "debater_a" in path or "speaker_a" in path:
                a_words += count
            elif "b" in tokens or "debater_b" in path or "speaker_b" in path:
                b_words += count
        if pro_words or con_words:
            return pro_words, con_words
        a_side = _s1114_a_side(row, presented=False)
        if (a_words or b_words) and a_side:
            return (a_words, b_words) if a_side == "PRO" else (b_words, a_words)

    arg_a = _s1114_first(row, "arg_a", "argument_a")
    arg_b = _s1114_first(row, "arg_b", "argument_b")
    a_side = _s1114_a_side(row, presented=False)
    if isinstance(arg_a, str) and isinstance(arg_b, str) and a_side:
        a_words, b_words = _s1114_words(arg_a), _s1114_words(arg_b)
        return (a_words, b_words) if a_side == "PRO" else (b_words, a_words)
    return None


def _s1114_bias_metrics(rows: Sequence[Mapping[str, Any]]) -> JSONDict:
    base = _s1114_core_metrics(rows)
    selected_a = label_eligible = 0
    position: Dict[str, Counter[str]] = {
        "first": Counter(),
        "last": Counter(),
        "two_turn": Counter(),
    }
    longer_eligible = longer_selected = ties = 0
    pro_words: List[int] = []
    con_words: List[int] = []

    for row in rows:
        label = _s1114_selected_label(row, presented=True)
        if label is not None:
            label_eligible += 1
            selected_a += int(label == "A")
        selected_side = _s1114_selected_side(row)
        for name in position:
            side = _s1114_position_side(row, name)
            if side is not None and selected_side is not None:
                position[name]["eligible"] += 1
                position[name]["selected"] += int(side == selected_side)
        lengths = _s1114_word_counts(row)
        if lengths is not None:
            pro_length, con_length = lengths
            pro_words.append(pro_length)
            con_words.append(con_length)
            if pro_length == con_length:
                ties += 1
            elif selected_side is not None:
                longer_eligible += 1
                longer_side = "PRO" if pro_length > con_length else "CON"
                longer_selected += int(selected_side == longer_side)

    return {
        "eligible_records": len(rows),
        "pro_selection_rate": base["yes_prediction_rate"],
        "false_positive_rate": base["false_positive_rate"],
        "false_negative_rate": base["false_negative_rate"],
        "fpr_minus_fnr": (
            base["false_positive_rate"] - base["false_negative_rate"]
            if base["false_positive_rate"] is not None
            and base["false_negative_rate"] is not None
            else None
        ),
        "displayed_a_eligible": label_eligible,
        "displayed_a_selection_rate": selected_a / label_eligible if label_eligible else None,
        "position_selection": {
            name: {
                "eligible": counts["eligible"],
                "selection_rate": (
                    counts["selected"] / counts["eligible"] if counts["eligible"] else None
                ),
            }
            for name, counts in position.items()
        },
        "verbosity": {
            "records_with_word_counts": len(pro_words),
            "mean_pro_words": sum(pro_words) / len(pro_words) if pro_words else None,
            "mean_con_words": sum(con_words) / len(con_words) if con_words else None,
            "longer_side_eligible": longer_eligible,
            "longer_side_selection_rate": (
                longer_selected / longer_eligible if longer_eligible else None
            ),
            "equal_length_records": ties,
        },
    }


def _s1114_probability(row: Mapping[str, Any], framing: str) -> Optional[float]:
    paths = {
        "yes_no": (
            "verdict_prob_belongs",
            "confidence.verdict_prob_belongs",
            "prob_yes",
            "confidence.prob_yes",
            "yes_probability",
        ),
        "true_false": (
            "boolean_prob_true",
            "confidence.boolean_prob_true",
            "prob_true",
            "confidence.prob_true",
        ),
        "a_b": (
            "debater_prob_A_right",
            "confidence.debater_prob_A_right",
            "prob_a_right",
            "confidence.prob_a_right",
        ),
    }
    value = _s1114_first(row, *paths[framing])
    try:
        probability = float(value)
    except (TypeError, ValueError):
        return None
    if not 0.0 <= probability <= 1.0:
        return None
    if framing == "a_b":
        a_side = _s1114_a_side(row, presented=True)
        if a_side is None:
            return None
        return probability if a_side == "PRO" else 1.0 - probability
    return probability


def _s1114_auc(labels: Sequence[int], scores: Sequence[float]) -> Optional[float]:
    n_pos = sum(labels)
    n_neg = len(labels) - n_pos
    if not n_pos or not n_neg:
        return None
    ordered = sorted(zip(scores, labels), key=lambda item: item[0])
    rank_sum = 0.0
    index = 0
    while index < len(ordered):
        end = index + 1
        while end < len(ordered) and ordered[end][0] == ordered[index][0]:
            end += 1
        average_rank = ((index + 1) + end) / 2.0
        rank_sum += average_rank * sum(label for _, label in ordered[index:end])
        index = end
    return (rank_sum - n_pos * (n_pos + 1) / 2.0) / (n_pos * n_neg)


def _s1114_probability_metrics(
    rows: Sequence[Mapping[str, Any]],
    framing: str,
) -> JSONDict:
    import math

    labels: List[int] = []
    probabilities: List[float] = []
    generated_agreements = 0
    confidence_correct: List[float] = []
    confidence_wrong: List[float] = []
    high_confidence_errors = 0
    for row in rows:
        truth = _s1114_truth(row)
        probability = _s1114_probability(row, framing)
        if truth is None or probability is None:
            continue
        label = int(truth == "Yes")
        labels.append(label)
        probabilities.append(probability)
        threshold_prediction = "Yes" if probability >= 0.5 else "No"
        generated_prediction = _s1114_prediction(row)
        generated_agreements += int(generated_prediction == threshold_prediction)
        confidence = max(probability, 1.0 - probability)
        if threshold_prediction == truth:
            confidence_correct.append(confidence)
        else:
            confidence_wrong.append(confidence)
            high_confidence_errors += int(confidence >= 0.9)
    n = len(labels)
    if not n:
        return {"available_records": 0}
    threshold_correct = sum((probability >= 0.5) == bool(label) for label, probability in zip(labels, probabilities))
    brier = sum((probability - label) ** 2 for label, probability in zip(labels, probabilities)) / n
    clipped = [min(1.0 - 1e-15, max(1e-15, probability)) for probability in probabilities]
    nll = -sum(
        label * math.log(probability) + (1 - label) * math.log(1 - probability)
        for label, probability in zip(labels, clipped)
    ) / n
    ece = 0.0
    bins: Table = []
    for bin_index in range(10):
        lower = bin_index / 10
        upper = (bin_index + 1) / 10
        indexes = [
            index
            for index, probability in enumerate(probabilities)
            if lower <= probability < upper or (bin_index == 9 and probability == 1.0)
        ]
        if not indexes:
            continue
        mean_probability = sum(probabilities[index] for index in indexes) / len(indexes)
        empirical_rate = sum(labels[index] for index in indexes) / len(indexes)
        ece += len(indexes) / n * abs(mean_probability - empirical_rate)
        bins.append(
            {
                "lower": lower,
                "upper": upper,
                "records": len(indexes),
                "mean_probability_yes": mean_probability,
                "empirical_yes_rate": empirical_rate,
            }
        )
    return {
        "available_records": n,
        "threshold_accuracy": threshold_correct / n,
        "roc_auc": _s1114_auc(labels, probabilities),
        "brier_score": brier,
        "negative_log_likelihood": nll,
        "expected_calibration_error_10_bins": ece,
        "generated_prediction_agreement": generated_agreements / n,
        "mean_threshold_confidence_correct": (
            sum(confidence_correct) / len(confidence_correct) if confidence_correct else None
        ),
        "mean_threshold_confidence_error": (
            sum(confidence_wrong) / len(confidence_wrong) if confidence_wrong else None
        ),
        "high_confidence_error_count_at_0_9": high_confidence_errors,
        "calibration_bins": bins,
    }


def _s1114_confidence_metrics(rows: Sequence[Mapping[str, Any]]) -> JSONDict:
    framings = {
        framing: _s1114_probability_metrics(rows, framing)
        for framing in ("yes_no", "true_false", "a_b")
    }
    agreement_counts: Counter[str] = Counter()
    multi_frame_records = 0
    for row in rows:
        decisions = []
        for framing in ("yes_no", "true_false", "a_b"):
            probability = _s1114_probability(row, framing)
            if probability is not None:
                decisions.append("Yes" if probability >= 0.5 else "No")
        if len(decisions) >= 2:
            multi_frame_records += 1
            agreement_counts["all_agree" if len(set(decisions)) == 1 else "disagree"] += 1
    fallback_rows = [
        row
        for row in rows
        if _s1114_bool(_s1114_first(row, "needed_fallback", "fallback_used")) is True
    ]
    nonfallback_rows = [
        row
        for row in rows
        if _s1114_bool(_s1114_first(row, "needed_fallback", "fallback_used")) is False
    ]
    return {
        "framings": framings,
        "cross_framing": {
            "records_with_at_least_two_framings": multi_frame_records,
            "all_agree": agreement_counts["all_agree"],
            "disagree": agreement_counts["disagree"],
            "disagreement_rate": (
                agreement_counts["disagree"] / multi_frame_records
                if multi_frame_records
                else None
            ),
        },
        "fallback_strata": {
            "fallback_records": len(fallback_rows),
            "nonfallback_records": len(nonfallback_rows),
            "yes_no_fallback": _s1114_probability_metrics(fallback_rows, "yes_no"),
            "yes_no_nonfallback": _s1114_probability_metrics(nonfallback_rows, "yes_no"),
            "caution": (
                "When fallback selected the final answer from Yes/No scores, "
                "prediction-confidence agreement is mechanically inflated."
            ),
        },
    }


def _s1114_condition_summary(rows: Sequence[Mapping[str, Any]]) -> JSONDict:
    return {
        "records": len(rows),
        "metrics": _s1114_metrics(rows),
        "bias": _s1114_bias_metrics(rows),
        "logprob": _s1114_confidence_metrics(rows),
    }


def _s1114_delta_takeaway(comparison: Mapping[str, Any], subject: str) -> str:
    paired = comparison.get("paired", {})
    difference = paired.get("accuracy_difference_right_minus_left")
    matched = paired.get("matched_records", 0)
    interval = paired.get("clustered_bootstrap_95ci")
    status = comparison.get("causal_status", "descriptive")
    if difference is None or not matched:
        return f"{subject}: no exact candidate-matched records were available."
    if interval and interval[0] > 0:
        direction = "improved"
        evidence = "the clustered 95% interval excludes zero"
    elif interval and interval[1] < 0:
        direction = "reduced"
        evidence = "the clustered 95% interval excludes zero"
    else:
        direction = "changed"
        evidence = "the clustered 95% interval includes zero or is unavailable"
    return (
        f"{subject}: the right-hand condition {direction} paired strict accuracy by "
        f"{difference * 100:+.2f} percentage points across {matched:,} exact matches; "
        f"{evidence}. Interpretation: {status}."
    )


def _s1114_find_stage_change(comparison: Mapping[str, Any], token: str) -> Optional[float]:
    stage_changes = comparison.get("paired", {}).get("stage_changes", {})
    for stage, metrics in stage_changes.items():
        if token.casefold() in stage.casefold():
            return metrics.get("accuracy_difference_right_minus_left")
    return None


def _s1114_average_argument_words(rows: Sequence[Mapping[str, Any]]) -> Optional[float]:
    totals = []
    for row in rows:
        lengths = _s1114_word_counts(row)
        if lengths is not None:
            totals.append(sum(lengths))
    return sum(totals) / len(totals) if totals else None

# END PRIVATE HELPERS FOR SECTIONS 11-14


# =============================================================================
# 11. Analysis section 2: baseline manual ablation
# =============================================================================


def identify_manual_ablation_conditions(catalog: Sequence[Mapping[str, Any]]) -> JSONDict:
    no_manual = _s1114_catalog_matches(
        catalog, filename="baseline_nomanual_results_full.json"
    )
    with_manual = _s1114_catalog_matches(
        catalog, filename="baseline_withmanual_results_full.json"
    )

    def catalog_value(entries: Sequence[Mapping[str, Any]], *keys: str) -> Any:
        if not entries:
            return None
        return _s1114_first(entries[0], *keys)

    no_judge = catalog_value(no_manual, "judge_model", "judge", "model")
    with_judge = catalog_value(with_manual, "judge_model", "judge", "model")
    no_output = catalog_value(no_manual, "structured_output", "output_method", "parser")
    with_output = catalog_value(with_manual, "structured_output", "output_method", "parser")
    no_flag = _s1114_bool(catalog_value(no_manual, "has_manual", "uses_manual"))
    with_flag = _s1114_bool(catalog_value(with_manual, "has_manual", "uses_manual"))

    return {
        "no_manual": no_manual,
        "with_manual": with_manual,
        "both_conditions_found": bool(no_manual and with_manual),
        "same_judge_verified": (
            _s1114_norm_text(no_judge) == _s1114_norm_text(with_judge)
            if no_judge is not None and with_judge is not None
            else None
        ),
        "same_output_method_verified": (
            _s1114_norm_text(no_output) == _s1114_norm_text(with_output)
            if no_output is not None and with_output is not None
            else None
        ),
        "manual_difference_verified_from_catalog": (
            no_flag is False and with_flag is True
            if no_flag is not None and with_flag is not None
            else None
        ),
        "intended_comparison": (
            "Same robust baseline judge and output pipeline; the intended treatment "
            "is inclusion of the NLM indexing manual. Candidate identity is still "
            "verified record by record."
        ),
    }


def analyze_manual_ablation(
    rows: Sequence[Mapping[str, Any]],
    catalog: Sequence[Mapping[str, Any]],
    integrity: Mapping[str, Any],
    context: Mapping[str, Any],
) -> JSONDict:
    identification = identify_manual_ablation_conditions(catalog)
    no_manual = _s1114_rows_for_file(rows, "baseline_nomanual_results_full.json")
    with_manual = _s1114_rows_for_file(rows, "baseline_withmanual_results_full.json")
    comparison = _s1114_paired_comparison(
        no_manual,
        with_manual,
        "baseline without manual",
        "baseline with manual",
        context,
        "controlled manual ablation after exact candidate verification",
    )
    overall_takeaway = _s1114_delta_takeaway(
        comparison, "Effect of adding the NLM manual"
    )
    similar_change = _s1114_find_stage_change(comparison, "similar")
    if similar_change is None:
        similar_takeaway = "The effect on similar negative tags could not be estimated."
    else:
        similar_takeaway = (
            "On similar negative tags, adding the manual changed paired accuracy by "
            f"{similar_change * 100:+.2f} percentage points."
        )

    no_fallback = _s1114_core_metrics(no_manual).get("fallback_rate")
    with_fallback = _s1114_core_metrics(with_manual).get("fallback_rate")
    fallback_takeaway = (
        "Fallback rates were unavailable."
        if no_fallback is None or with_fallback is None
        else (
            "The fallback rate changed from "
            f"{no_fallback * 100:.2f}% without the manual to "
            f"{with_fallback * 100:.2f}% with it."
        )
    )

    return {
        "section_id": 11,
        "title": "Baseline manual ablation",
        "identification": identification,
        "conditions": {
            "without_manual": _s1114_condition_summary(no_manual),
            "with_manual": _s1114_condition_summary(with_manual),
        },
        "comparisons": [comparison],
        "takeaways": [overall_takeaway, similar_takeaway, fallback_takeaway],
        "interpretation": {
            "question": "Does supplying the NLM indexing manual help the 0.8B baseline judge?",
            "positive_mechanism": (
                "Indexing guidance may help reject plausible but incorrect similar tags."
            ),
            "counter_hypothesis": (
                "A long manual may overload or distract a small judge and may induce "
                "overly conservative No decisions."
            ),
        },
        "limitations": [
            "The comparison is treated as controlled only for exact candidate matches.",
            "Teacher-forced confidence is analyzed separately from the generated verdict.",
            "Fallback confidence agreement is partly circular when fallback chose the verdict.",
        ],
    }


# =============================================================================
# 12. Analysis section 3: older Pydantic implementations
# =============================================================================


def identify_pydantic_comparison_sets(catalog: Sequence[Mapping[str, Any]]) -> JSONDict:
    files = {
        "pydantic_baseline": "pydantic_baseline_results_full.json",
        "legacy_baseline": "baseline_results_merged.json",
        "robust_baseline_with_manual": "baseline_withmanual_results_full.json",
        "pydantic_statement": "pydantic_statement_results_full.json",
        "legacy_statement": "statement_results_merged.json",
        "robust_statement": "statement_results_full.json",
        "pydantic_interactive": "pydantic_interactive_results_full.json",
        "legacy_interactive": "interactive_results_merged.json",
        "robust_interactive": "interactive_results_full.json",
    }
    located = {
        name: _s1114_catalog_matches(catalog, filename=filename)
        for name, filename in files.items()
    }
    return {
        "files": files,
        "located_catalog_entries": located,
        "comparison_groups": {
            "baseline": [
                "pydantic_baseline",
                "legacy_baseline",
                "robust_baseline_with_manual",
            ],
            "statement": [
                "pydantic_statement",
                "legacy_statement",
                "robust_statement",
            ],
            "interactive": [
                "pydantic_interactive",
                "legacy_interactive",
                "robust_interactive ABA",
            ],
        },
        "causal_status": (
            "Historical implementation comparisons: prompts, supplied inputs, retries, "
            "parsers, fallback behavior, candidate choices, and sometimes transcript "
            "construction differ. They do not isolate Pydantic itself."
        ),
    }


def analyze_pydantic_unknowns(rows: Sequence[Mapping[str, Any]]) -> JSONDict:
    target = _s1114_rows_for_file(rows, "pydantic_statement_results_full.json")
    unknown = [row for row in target if _s1114_prediction(row) is None]
    valid = [row for row in target if _s1114_prediction(row) is not None]
    by_stage: Counter[str] = Counter(_s1114_stage(row) for row in unknown)
    by_pro_position: Counter[str] = Counter()
    for row in unknown:
        pro_first = _s1114_bool(_s1114_first(row, "pro_first", "pro_is_first"))
        if pro_first is True:
            by_pro_position["PRO first"] += 1
        elif pro_first is False:
            by_pro_position["PRO second"] += 1
        else:
            a_side = _s1114_a_side(row, presented=False)
            by_pro_position[
                "PRO displayed as A" if a_side == "PRO" else
                "PRO displayed as B" if a_side == "CON" else
                "position unavailable"
            ] += 1

    return {
        "file": "pydantic_statement_results_full.json",
        "metrics": _s1114_metrics(target),
        "unknown_count": len(unknown),
        "unknown_rate": len(unknown) / len(target) if target else None,
        "expected_unknown_count_from_audit": 129,
        "matches_expected_unknown_count": len(unknown) == 129 if target else None,
        "unknown_by_stage": dict(sorted(by_stage.items())),
        "unknown_by_pro_position": dict(sorted(by_pro_position.items())),
        "difficulty_indicators": {
            "mean_total_argument_words_unknown": _s1114_average_argument_words(unknown),
            "mean_total_argument_words_valid": _s1114_average_argument_words(valid),
        },
        "interpretation": (
            "Unknown is parser/model non-coverage, not a third class and not No. Strict "
            "accuracy counts it as failure; valid-only accuracy is reported with coverage."
        ),
    }


def analyze_pydantic_interactive_issue(rows: Sequence[Mapping[str, Any]]) -> JSONDict:
    pydantic_rows = _s1114_rows_for_file(
        rows, "pydantic_interactive_results_full.json"
    )
    pro_as_a: Table = []
    pro_as_b: Table = []
    unavailable: Table = []
    for row in pydantic_rows:
        flag = _s1114_bool(
            _s1114_first(row, "pro_is_a", "a_is_pro", "pro_is_debater_a", "pro_first")
        )
        if flag is True:
            pro_as_a.append(row)
        elif flag is False:
            pro_as_b.append(row)
        else:
            unavailable.append(row)

    robust_aba = _s1114_rows_for_file(
        rows, "interactive_results_full.json", order="ABA"
    )
    descriptive = _s1114_paired_comparison(
        pydantic_rows,
        robust_aba,
        "older Pydantic interactive",
        "corrected robust ABA",
        {},
        (
            "descriptive/confounded: parser, judge prompt, regenerated missing content, "
            "and corrected transcript construction may differ"
        ),
        content_mode="aba",
    )
    return {
        "available": bool(pydantic_rows),
        "all_records": _s1114_condition_summary(pydantic_rows),
        "split": {
            "pro_is_a_or_pro_first": _s1114_condition_summary(pro_as_a),
            "pro_is_b_or_not_first": _s1114_condition_summary(pro_as_b),
            "mapping_unavailable": len(unavailable),
        },
        "corrected_robust_aba_comparison": descriptive,
        "known_issue": (
            "In the older generator, when PRO was not A, arg1/arg2 could be reordered "
            "while the judge prompt still named them A/B, making the transcript internally "
            "inconsistent. A split difference is therefore not clean position-bias evidence."
        ),
    }


def analyze_pydantic_comparisons(
    rows: Sequence[Mapping[str, Any]],
    catalog: Sequence[Mapping[str, Any]],
    integrity: Mapping[str, Any],
    context: Mapping[str, Any],
) -> JSONDict:
    sets = identify_pydantic_comparison_sets(catalog)
    pyd_baseline = _s1114_rows_for_file(rows, "pydantic_baseline_results_full.json")
    legacy_baseline = _s1114_rows_for_file(rows, "baseline_results_merged.json")
    robust_baseline = _s1114_rows_for_file(rows, "baseline_withmanual_results_full.json")
    pyd_statement = _s1114_rows_for_file(rows, "pydantic_statement_results_full.json")
    legacy_statement = _s1114_rows_for_file(rows, "statement_results_merged.json")
    robust_statement = _s1114_rows_for_file(rows, "statement_results_full.json")
    pyd_interactive = _s1114_rows_for_file(rows, "pydantic_interactive_results_full.json")
    legacy_interactive = _s1114_rows_for_file(rows, "interactive_results_merged.json")
    robust_aba = _s1114_rows_for_file(rows, "interactive_results_full.json", order="ABA")

    specs = [
        (legacy_baseline, pyd_baseline, "legacy baseline", "older Pydantic baseline", None),
        (pyd_baseline, robust_baseline, "older Pydantic baseline", "robust with-manual baseline", None),
        (legacy_statement, pyd_statement, "legacy statement", "older Pydantic statement", "statement"),
        (pyd_statement, robust_statement, "older Pydantic statement", "robust statement", "statement"),
        (legacy_interactive, pyd_interactive, "legacy interactive", "older Pydantic interactive", "aba"),
        (pyd_interactive, robust_aba, "older Pydantic interactive", "corrected robust ABA", "aba"),
    ]
    comparisons = [
        _s1114_paired_comparison(
            left,
            right,
            left_name,
            right_name,
            context,
            (
                "descriptive/confounded implementation comparison; do not attribute the "
                "difference to Pydantic alone"
            ),
            content_mode=content_mode,
        )
        for left, right, left_name, right_name, content_mode in specs
        if left or right
    ]
    takeaways = [
        _s1114_delta_takeaway(comparison, f"{comparison['left_condition']} vs {comparison['right_condition']}")
        for comparison in comparisons
    ]
    return {
        "section_id": 12,
        "title": "Older Pydantic implementation comparisons",
        "identification": sets,
        "conditions": {
            "pydantic_baseline": _s1114_condition_summary(pyd_baseline),
            "pydantic_statement": _s1114_condition_summary(pyd_statement),
            "pydantic_interactive": _s1114_condition_summary(pyd_interactive),
        },
        "unknown_analysis": analyze_pydantic_unknowns(rows),
        "interactive_transcript_issue": analyze_pydantic_interactive_issue(rows),
        "comparisons": comparisons,
        "takeaways": takeaways,
        "limitations": [
            "These are implementation comparisons, not clean tests of Pydantic formatting.",
            "Strict and valid-only accuracy must both be shown when Unknowns occur.",
            "The interactive transcript-label issue can create a mapping-specific artifact.",
            "Log probabilities are unavailable for the older named Pydantic files.",
        ],
    }


# =============================================================================
# 13. Analysis section 4: 2B rejudging
# =============================================================================


def identify_large_judge_conditions(catalog: Sequence[Mapping[str, Any]]) -> JSONDict:
    files = {
        "statement_0_8b": "statement_results_full.json",
        "statement_2b": "statement_results_full_rejudge2B.json",
        "interactive_0_8b": "interactive_results_full.json",
        "interactive_2b": "interactive_results_full_rejudge2B.json",
        "pydantic_statement": "pydantic_statement_results_full.json",
        "pydantic_interactive": "pydantic_interactive_results_full.json",
    }
    return {
        "files": files,
        "located_catalog_entries": {
            name: _s1114_catalog_matches(catalog, filename=filename)
            for name, filename in files.items()
        },
        "primary_comparisons": [
            "statement 0.8B vs same essays rejudged by 2B",
            "interactive ABA 0.8B vs same transcript rejudged by 2B",
            "interactive BAB 0.8B vs same transcript rejudged by 2B",
        ],
        "secondary_comparisons": [
            "2B statement vs older Pydantic statement",
            "2B ABA vs older Pydantic interactive",
        ],
    }


def analyze_clean_judge_size_comparisons(
    rows: Sequence[Mapping[str, Any]],
    catalog: Sequence[Mapping[str, Any]],
    integrity: Mapping[str, Any],
    context: Mapping[str, Any],
) -> JSONDict:
    statement_small = _s1114_rows_for_file(rows, "statement_results_full.json")
    statement_large = _s1114_rows_for_file(rows, "statement_results_full_rejudge2B.json")
    interactive_small_aba = _s1114_rows_for_file(
        rows, "interactive_results_full.json", order="ABA"
    )
    interactive_large_aba = _s1114_rows_for_file(
        rows, "interactive_results_full_rejudge2B.json", order="ABA"
    )
    interactive_small_bab = _s1114_rows_for_file(
        rows, "interactive_results_full.json", order="BAB"
    )
    interactive_large_bab = _s1114_rows_for_file(
        rows, "interactive_results_full_rejudge2B.json", order="BAB"
    )

    comparisons = [
        _s1114_paired_comparison(
            statement_small,
            statement_large,
            "statement judge 0.8B",
            "statement judge 2B",
            context,
            "controlled judge-size comparison conditional on identical stored essays",
            content_mode="statement",
        ),
        _s1114_paired_comparison(
            interactive_small_aba,
            interactive_large_aba,
            "interactive ABA judge 0.8B",
            "interactive ABA judge 2B",
            context,
            "controlled judge-size comparison conditional on identical ABA transcript",
            content_mode="aba",
        ),
        _s1114_paired_comparison(
            interactive_small_bab,
            interactive_large_bab,
            "interactive BAB judge 0.8B",
            "interactive BAB judge 2B",
            context,
            "controlled judge-size comparison conditional on identical BAB transcript",
            content_mode="bab",
        ),
    ]
    return {
        "comparisons": comparisons,
        "condition_bias_and_logprob": {
            "statement_0_8b": _s1114_condition_summary(statement_small),
            "statement_2b": _s1114_condition_summary(statement_large),
            "aba_0_8b": _s1114_condition_summary(interactive_small_aba),
            "aba_2b": _s1114_condition_summary(interactive_large_aba),
            "bab_0_8b": _s1114_condition_summary(interactive_small_bab),
            "bab_2b": _s1114_condition_summary(interactive_large_bab),
        },
        "takeaways": [
            _s1114_delta_takeaway(comparison, comparison["right_condition"])
            for comparison in comparisons
        ],
        "oversight_caveat": (
            "The 2B judge has the same nominal size as the debaters, so this no longer "
            "represents the original weak-judge scalable-oversight setting."
        ),
    }


def analyze_descriptive_2b_vs_pydantic(
    rows: Sequence[Mapping[str, Any]],
    catalog: Sequence[Mapping[str, Any]],
    integrity: Mapping[str, Any],
    context: Mapping[str, Any],
) -> JSONDict:
    pyd_statement = _s1114_rows_for_file(rows, "pydantic_statement_results_full.json")
    large_statement = _s1114_rows_for_file(rows, "statement_results_full_rejudge2B.json")
    pyd_interactive = _s1114_rows_for_file(rows, "pydantic_interactive_results_full.json")
    large_aba = _s1114_rows_for_file(
        rows, "interactive_results_full_rejudge2B.json", order="ABA"
    )
    comparisons = [
        _s1114_paired_comparison(
            pyd_statement,
            large_statement,
            "older Pydantic statement",
            "robust statement rejudged by 2B",
            context,
            (
                "descriptive/confounded: judge size, prompt, parser, fallback, candidate, "
                "and possibly essay generation differ"
            ),
            content_mode="statement",
        ),
        _s1114_paired_comparison(
            pyd_interactive,
            large_aba,
            "older Pydantic interactive",
            "robust ABA rejudged by 2B",
            context,
            (
                "descriptive/confounded: judge size, prompt, parser, fallback, transcript "
                "construction, and possibly generated turns differ"
            ),
            content_mode="aba",
        ),
    ]
    return {
        "comparisons": comparisons,
        "takeaways": [
            _s1114_delta_takeaway(comparison, comparison["right_condition"])
            for comparison in comparisons
        ],
        "warning": "Never attribute these historical differences to judge size alone.",
    }


def analyze_large_judge_section(
    rows: Sequence[Mapping[str, Any]],
    catalog: Sequence[Mapping[str, Any]],
    integrity: Mapping[str, Any],
    context: Mapping[str, Any],
) -> JSONDict:
    primary = analyze_clean_judge_size_comparisons(
        rows, catalog, integrity, context
    )
    secondary = analyze_descriptive_2b_vs_pydantic(
        rows, catalog, integrity, context
    )
    return {
        "section_id": 13,
        "title": "Original 0.8B judge versus rejudged 2B judge",
        "identification": identify_large_judge_conditions(catalog),
        "primary_controlled_analysis": primary,
        "secondary_historical_analysis": secondary,
        "comparisons": primary["comparisons"] + secondary["comparisons"],
        "takeaways": primary["takeaways"] + secondary["takeaways"],
        "limitations": [
            "A primary result is controlled only where stored content is verified identical.",
            "The 2B-vs-Pydantic comparisons are historical and multi-factor.",
            "Confidence scores are teacher-forced follow-up scores, not the original verdict token probability.",
        ],
    }


# =============================================================================
# 14. Analysis section 5: ABA, BAB, and swapped BAB labels
# =============================================================================


def identify_interactive_order_conditions(catalog: Sequence[Mapping[str, Any]]) -> JSONDict:
    original = _s1114_catalog_matches(
        catalog, filename="interactive_results_full.json"
    )
    swapped = _s1114_catalog_matches(
        catalog, filename=CANONICAL_SWAPPED_BAB_FILE
    )
    duplicate = _s1114_catalog_matches(
        catalog, filename=KNOWN_DUPLICATE_SWAPPED_BAB_FILE
    )
    large = _s1114_catalog_matches(
        catalog, filename="interactive_results_full_rejudge2B.json"
    )
    return {
        "original_interactive": original,
        "canonical_swapped_bab": swapped,
        "excluded_duplicate_swapped_bab": duplicate,
        "large_judge_interactive": large,
        "conditions": ["ABA", "BAB", "BAB with displayed A/B labels swapped"],
        "duplicate_policy": (
            f"Use {CANONICAL_SWAPPED_BAB_FILE}; exclude "
            f"{KNOWN_DUPLICATE_SWAPPED_BAB_FILE} from independent-condition counts."
        ),
    }


def compute_three_way_prediction_patterns(
    aba_rows: Sequence[Mapping[str, Any]],
    bab_rows: Sequence[Mapping[str, Any]],
    swapped_rows: Sequence[Mapping[str, Any]],
) -> Table:
    aba_map, _ = _s1114_unique_map(aba_rows)
    bab_map, _ = _s1114_unique_map(bab_rows)
    swapped_map, _ = _s1114_unique_map(swapped_rows)
    shared = sorted(set(aba_map) & set(bab_map) & set(swapped_map))
    grouped: Dict[Tuple[str, str], Counter[str]] = defaultdict(Counter)

    for key in shared:
        aba = aba_map[key]
        bab = bab_map[key]
        swapped = swapped_map[key]
        pa = _s1114_prediction(aba)
        pb = _s1114_prediction(bab)
        ps = _s1114_prediction(swapped)
        if pa == pb == ps:
            category = "ABA = BAB = swapped"
        elif pa != pb and pb == ps:
            category = "ABA differs; BAB = swapped"
        elif pa == ps and pb != pa:
            category = "ABA = swapped; BAB differs"
        elif pa == pb and ps != pa:
            category = "ABA = BAB; swapped differs"
        else:
            category = "all other patterns"
        truth = _s1114_truth(aba)
        correctness = "".join(
            name if prediction == truth else "-"
            for name, prediction in (("A", pa), ("B", pb), ("S", ps))
        ) or "none"
        for stage in ("ALL", _s1114_stage(aba)):
            grouped[(stage, category)]["count"] += 1
            grouped[(stage, category)][f"correctness_{correctness}"] += 1

    totals = Counter()
    for (stage, _), counts in grouped.items():
        totals[stage] += counts["count"]
    table: Table = []
    for (stage, category), counts in sorted(grouped.items()):
        row: Row = {
            "stage": stage,
            "pattern": category,
            "count": counts["count"],
            "share_within_stage": counts["count"] / totals[stage] if totals[stage] else None,
            "three_way_exact_match_total": len(shared),
        }
        row.update({key: value for key, value in counts.items() if key != "count"})
        table.append(row)
    return table


def analyze_aba_vs_bab(
    rows: Sequence[Mapping[str, Any]],
    context: Mapping[str, Any],
) -> JSONDict:
    aba = _s1114_rows_for_file(rows, "interactive_results_full.json", order="ABA")
    bab = _s1114_rows_for_file(rows, "interactive_results_full.json", order="BAB")
    comparison = _s1114_paired_comparison(
        aba,
        bab,
        "interactive ABA",
        "interactive BAB",
        context,
        (
            "order/content comparison: ABA and BAB transcripts were generated separately, "
            "so speaking order and turn allocation are confounded with argument quality"
        ),
    )
    return {
        "comparison": comparison,
        "conditions": {
            "ABA": _s1114_condition_summary(aba),
            "BAB": _s1114_condition_summary(bab),
        },
        "takeaway": _s1114_delta_takeaway(comparison, "ABA versus BAB"),
        "interpretation": (
            "A difference cannot be called a pure first-speaker or turn-count effect because "
            "the two transcripts contain separately generated text."
        ),
    }


def analyze_bab_label_swap(
    rows: Sequence[Mapping[str, Any]],
    integrity: Mapping[str, Any],
    context: Mapping[str, Any],
) -> JSONDict:
    original = _s1114_rows_for_file(
        rows, "interactive_results_full.json", order="BAB"
    )
    swapped = _s1114_rows_for_file(
        rows, CANONICAL_SWAPPED_BAB_FILE, order="swapped"
    )
    comparison = _s1114_paired_comparison(
        original,
        swapped,
        "original BAB labels",
        "BAB with displayed labels swapped",
        context,
        "clean displayed-label test conditional on fixed-content verification",
        content_mode="bab",
    )
    pairs, _ = _s1114_pair_rows(original, swapped)
    original_a_eligible = original_a_selected = 0
    swapped_a_eligible = swapped_a_selected = 0
    flips_toward_new_a = flips_toward_new_b = 0
    correctness_gained = correctness_lost = 0

    for left, right in pairs:
        left_label = _s1114_selected_label(left, presented=True)
        right_label = _s1114_selected_label(right, presented=True)
        if left_label is not None:
            original_a_eligible += 1
            original_a_selected += int(left_label == "A")
        if right_label is not None:
            swapped_a_eligible += 1
            swapped_a_selected += int(right_label == "A")
        left_prediction = _s1114_prediction(left)
        right_prediction = _s1114_prediction(right)
        truth = _s1114_truth(left)
        if left_prediction != right_prediction:
            new_label = _s1114_selected_label(right, presented=True)
            flips_toward_new_a += int(new_label == "A")
            flips_toward_new_b += int(new_label == "B")
            correctness_gained += int(left_prediction != truth and right_prediction == truth)
            correctness_lost += int(left_prediction == truth and right_prediction != truth)

    direction_p = _s1114_exact_binomial_p(flips_toward_new_a, flips_toward_new_b)
    verification = comparison["content_verification"]
    if verification["checked_pairs"] and not verification["mismatching_pairs"]:
        label_test_status = "fixed content verified for all checked pairs"
    elif verification["mismatching_pairs"]:
        label_test_status = "content mismatch detected; do not interpret as a clean label test"
    else:
        label_test_status = "content equality could not be verified from normalized rows"

    return {
        "comparison": comparison,
        "label_selection": {
            "original_displayed_a_eligible": original_a_eligible,
            "original_displayed_a_selection_rate": (
                original_a_selected / original_a_eligible if original_a_eligible else None
            ),
            "swapped_displayed_a_eligible": swapped_a_eligible,
            "swapped_displayed_a_selection_rate": (
                swapped_a_selected / swapped_a_eligible if swapped_a_eligible else None
            ),
            "flips_toward_newly_displayed_a": flips_toward_new_a,
            "flips_toward_newly_displayed_b": flips_toward_new_b,
            "directional_flip_exact_p": direction_p,
            "correctness_gained_after_swap": correctness_gained,
            "correctness_lost_after_swap": correctness_lost,
        },
        "conditions": {
            "original_BAB": _s1114_condition_summary(original),
            "swapped_BAB": _s1114_condition_summary(swapped),
        },
        "clean_test_status": label_test_status,
        "takeaway": _s1114_delta_takeaway(comparison, "BAB displayed-label swap"),
        "interpretation": (
            "Frequent but directionally balanced flips indicate label sensitivity or "
            "stochastic instability; systematic flips toward the newly displayed A indicate "
            "an A-label preference."
        ),
    }


def analyze_interactive_orders_and_labels(
    rows: Sequence[Mapping[str, Any]],
    catalog: Sequence[Mapping[str, Any]],
    integrity: Mapping[str, Any],
    context: Mapping[str, Any],
) -> JSONDict:
    aba = _s1114_rows_for_file(rows, "interactive_results_full.json", order="ABA")
    bab = _s1114_rows_for_file(rows, "interactive_results_full.json", order="BAB")
    swapped = _s1114_rows_for_file(
        rows, CANONICAL_SWAPPED_BAB_FILE, order="swapped"
    )
    order_analysis = analyze_aba_vs_bab(rows, context)
    label_analysis = analyze_bab_label_swap(rows, integrity, context)
    patterns = compute_three_way_prediction_patterns(aba, bab, swapped)

    large_aba = _s1114_rows_for_file(
        rows, "interactive_results_full_rejudge2B.json", order="ABA"
    )
    large_bab = _s1114_rows_for_file(
        rows, "interactive_results_full_rejudge2B.json", order="BAB"
    )
    large_order = None
    if large_aba or large_bab:
        large_order = _s1114_paired_comparison(
            large_aba,
            large_bab,
            "2B judge on ABA",
            "2B judge on BAB",
            context,
            (
                "order/content comparison: fixed judge but separately generated ABA/BAB "
                "transcripts still confound order with argument quality"
            ),
        )

    takeaways = [order_analysis["takeaway"], label_analysis["takeaway"]]
    if large_order is not None:
        takeaways.append(_s1114_delta_takeaway(large_order, "2B ABA versus BAB"))
    return {
        "section_id": 14,
        "title": "Interactive ABA, BAB, and swapped BAB labels",
        "identification": identify_interactive_order_conditions(catalog),
        "order_analysis_0_8b": order_analysis,
        "label_swap_analysis": label_analysis,
        "order_analysis_2b": large_order,
        "prediction_patterns": patterns,
        "conditions": {
            "ABA": _s1114_condition_summary(aba),
            "BAB": _s1114_condition_summary(bab),
            "BAB_swapped_labels": _s1114_condition_summary(swapped),
        },
        "comparisons": [
            order_analysis["comparison"],
            label_analysis["comparison"],
        ] + ([large_order] if large_order is not None else []),
        "takeaways": takeaways,
        "limitations": [
            "ABA-vs-BAB is not a pure order intervention because its arguments were generated separately.",
            "BAB-vs-swapped is the clean label test only where physical transcript equality is verified.",
            "A/first/last/two-turn effects are structurally confounded within one three-turn order.",
            "The normalized duplicate swapped-BAB file is excluded as an independent condition.",
        ],
    }


# =============================================================================
# 15. Expectations, deterministic takeaways, and interpretation rules
# =============================================================================


# REPORTING_HELPERS_SECTIONS_15_16_V1
# Private, dependency-light utilities used only by sections 15 and 16. They are
# intentionally tolerant of the slightly different dictionaries returned by
# the earlier analysis sections, while never silently manufacturing a metric.


def _report_walk(value: Any, path: str = "") -> Iterable[Tuple[str, Any]]:
    yield path, value
    if isinstance(value, Mapping):
        for key, child in value.items():
            child_path = f"{path}.{key}" if path else str(key)
            yield from _report_walk(child, child_path)
    elif isinstance(value, (list, tuple)):
        for index, child in enumerate(value):
            child_path = f"{path}[{index}]"
            yield from _report_walk(child, child_path)


def _report_direct_get(mapping: Mapping[str, Any], name: str) -> Any:
    if name in mapping:
        return mapping[name]
    current: Any = mapping
    for part in name.split("."):
        if not isinstance(current, Mapping) or part not in current:
            return MISSING
        current = current[part]
    return current


def _report_lookup(
    value: Any,
    names: Sequence[str],
    default: Any = None,
    recursive: bool = True,
) -> Any:
    if isinstance(value, Mapping):
        for name in names:
            found = _report_direct_get(value, name)
            if found is not MISSING and found is not None:
                return found
    if recursive:
        wanted = {str(name).split(".")[-1].lower() for name in names}
        for path, child in _report_walk(value):
            if path and path.rsplit(".", 1)[-1].split("[", 1)[0].lower() in wanted:
                if child is not None and not isinstance(child, (Mapping, list, tuple)):
                    return child
    return default


def _report_float(value: Any) -> Optional[float]:
    import math

    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _report_int(value: Any) -> Optional[int]:
    number = _report_float(value)
    if number is None:
        return None
    return int(number)


def _report_fraction(value: Any) -> Optional[float]:
    number = _report_float(value)
    if number is None:
        return None
    if 1.0 < abs(number) <= 100.0:
        return number / 100.0
    return number


def _report_metric(mapping: Any, names: Sequence[str]) -> Optional[float]:
    return _report_fraction(_report_lookup(mapping, names, recursive=True))


def _report_count(mapping: Any, names: Sequence[str]) -> Optional[int]:
    return _report_int(_report_lookup(mapping, names, recursive=True))


def _report_fmt_number(value: Any, digits: int = 3) -> str:
    number = _report_float(value)
    if number is None:
        return "—"
    if number.is_integer():
        return f"{int(number):,}"
    return f"{number:.{digits}f}"


def _report_fmt_percent(value: Any, signed: bool = False, digits: int = 1) -> str:
    number = _report_fraction(value)
    if number is None:
        return "—"
    prefix = "+" if signed and number > 0 else ""
    return f"{prefix}{100.0 * number:.{digits}f}%"


def _report_condition_name(value: Any, fallback: str = "condition") -> str:
    found = _report_lookup(
        value,
        (
            "condition",
            "condition_id",
            "condition_name",
            "display_name",
            "label",
            "name",
            "source_file",
            "filename",
        ),
        recursive=False,
    )
    return str(found) if found not in (None, "") else fallback


def _report_pair_names(comparison: Mapping[str, Any]) -> Tuple[str, str]:
    left = _report_lookup(
        comparison,
        ("condition_a", "left_condition", "baseline_condition", "source_condition", "a"),
        recursive=False,
    )
    right = _report_lookup(
        comparison,
        ("condition_b", "right_condition", "comparison_condition", "target_condition", "b"),
        recursive=False,
    )
    if isinstance(left, Mapping):
        left = _report_condition_name(left, "A")
    if isinstance(right, Mapping):
        right = _report_condition_name(right, "B")
    return str(left or "A"), str(right or "B")


def _report_difference(comparison: Mapping[str, Any]) -> Optional[float]:
    direct = _report_lookup(
        comparison,
        (
            "accuracy_difference",
            "strict_accuracy_difference",
            "difference",
            "delta",
            "effect",
            "effect_size",
            "percentage_point_difference",
            "accuracy_delta",
            "paired_difference",
        ),
        recursive=False,
    )
    if direct is not None:
        return _report_fraction(direct)
    left = _report_metric(
        comparison,
        ("accuracy_a", "left_accuracy", "baseline_accuracy", "source_accuracy"),
    )
    right = _report_metric(
        comparison,
        ("accuracy_b", "right_accuracy", "comparison_accuracy", "target_accuracy"),
    )
    if left is not None and right is not None:
        return right - left
    return None


def _report_ci(value: Mapping[str, Any]) -> Optional[Tuple[float, float]]:
    candidate = _report_lookup(
        value,
        (
            "confidence_interval",
            "bootstrap_ci",
            "ci",
            "accuracy_difference_ci",
            "difference_ci",
        ),
        recursive=False,
    )
    low: Any = None
    high: Any = None
    if isinstance(candidate, Mapping):
        low = _report_lookup(candidate, ("low", "lower", "ci_low", "lower_bound"), recursive=False)
        high = _report_lookup(candidate, ("high", "upper", "ci_high", "upper_bound"), recursive=False)
    elif isinstance(candidate, (list, tuple)) and len(candidate) >= 2:
        low, high = candidate[0], candidate[1]
    if low is None or high is None:
        low = _report_lookup(value, ("ci_low", "lower_ci", "bootstrap_ci_low"), recursive=False)
        high = _report_lookup(value, ("ci_high", "upper_ci", "bootstrap_ci_high"), recursive=False)
    low_number = _report_fraction(low)
    high_number = _report_fraction(high)
    if low_number is None or high_number is None:
        return None
    return (min(low_number, high_number), max(low_number, high_number))


def _report_causal_status(value: Mapping[str, Any]) -> str:
    raw = _report_lookup(
        value,
        ("causal_status", "comparison_quality", "validity", "comparison_type", "interpretation"),
        default="",
        recursive=False,
    )
    text = str(raw or "").lower()
    if any(token in text for token in ("confound", "descriptive", "historical", "implementation")):
        return "confounded"
    if any(token in text for token in ("controlled", "clean", "content-verified", "paired", "fixed-content")):
        return "controlled"
    verified = _report_lookup(value, ("content_verified", "is_controlled", "clean_comparison"), recursive=False)
    if verified is True:
        return "controlled"
    if verified is False:
        return "confounded"
    return "uncertain"


def _report_as_table(value: Any) -> Table:
    if isinstance(value, list):
        return [dict(row) for row in value if isinstance(row, Mapping)]
    if isinstance(value, tuple):
        return [dict(row) for row in value if isinstance(row, Mapping)]
    if isinstance(value, Mapping):
        rows: Table = []
        for key, child in value.items():
            if isinstance(child, Mapping):
                row = dict(child)
                row.setdefault("name", str(key))
                rows.append(row)
        return rows
    return []


def _report_find_tables(value: Any, key_terms: Sequence[str]) -> Table:
    terms = tuple(term.lower() for term in key_terms)
    collected: Table = []
    seen: set = set()
    for path, child in _report_walk(value):
        key = path.rsplit(".", 1)[-1].lower() if path else ""
        if not any(term in key for term in terms):
            continue
        for row in _report_as_table(child):
            signature = json.dumps(_report_json_safe(row), sort_keys=True, ensure_ascii=False)
            if signature not in seen:
                seen.add(signature)
                collected.append(row)
    return collected


def _report_collect_strings(value: Any, key_terms: Sequence[str]) -> List[str]:
    terms = tuple(term.lower() for term in key_terms)
    output: List[str] = []
    for path, child in _report_walk(value):
        key = path.rsplit(".", 1)[-1].lower() if path else ""
        if not any(term in key for term in terms):
            continue
        if isinstance(child, str) and child.strip():
            output.append(child.strip())
        elif isinstance(child, (list, tuple)):
            output.extend(str(item).strip() for item in child if isinstance(item, str) and item.strip())
    return _report_dedupe(output)


def _report_dedupe(values: Sequence[str]) -> List[str]:
    seen: set = set()
    output: List[str] = []
    for value in values:
        normalized = " ".join(str(value).split())
        if normalized and normalized not in seen:
            seen.add(normalized)
            output.append(normalized)
    return output


def _report_json_safe(value: Any) -> Any:
    import math

    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, Mapping):
        return {
            str(key): _report_json_safe(child)
            for key, child in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, (list, tuple)):
        return [_report_json_safe(child) for child in value]
    if isinstance(value, set):
        return [_report_json_safe(child) for child in sorted(value, key=str)]
    try:
        return _report_json_safe(value.item())
    except (AttributeError, TypeError, ValueError):
        return str(value)


def _report_flatten_row(
    value: Mapping[str, Any],
    prefix: str = "",
    output: Optional[Row] = None,
) -> Row:
    if output is None:
        output = {}
    for key, child in value.items():
        name = f"{prefix}.{key}" if prefix else str(key)
        if isinstance(child, Mapping):
            _report_flatten_row(child, name, output)
        elif isinstance(child, (list, tuple, set)):
            output[name] = json.dumps(_report_json_safe(child), ensure_ascii=False, sort_keys=True)
        else:
            output[name] = _report_json_safe(child)
    return output


def _report_integrity_rows(integrity: Mapping[str, Any]) -> Table:
    rows: Table = []
    for path, value in _report_walk(integrity):
        if not path or isinstance(value, (Mapping, list, tuple)):
            continue
        key = path.rsplit(".", 1)[-1].lower()
        if any(token in key for token in ("warning", "error", "finding", "issue", "fatal")):
            rows.append({"path": path, "value": value})
    for path, value in _report_walk(integrity):
        if isinstance(value, list) and value and all(isinstance(item, Mapping) for item in value):
            if any(token in path.lower() for token in ("finding", "warning", "error", "issue")):
                for item in value:
                    row = dict(item)
                    row.setdefault("source", path)
                    rows.append(row)
    return rows


def _report_extract_pvalues(value: Any) -> Table:
    rows: Table = []
    for path, child in _report_walk(value):
        key = path.rsplit(".", 1)[-1].lower() if path else ""
        if key in {"p", "p_value", "pvalue", "mcnemar_p", "mcnemar_p_value", "proportion_p_value"}:
            number = _report_float(child)
            if number is not None and 0.0 <= number <= 1.0:
                rows.append({"path": path, "p_value": number})
    return rows


def _report_bh_rows(rows: Sequence[Mapping[str, Any]]) -> Table:
    indexed = []
    for index, row in enumerate(rows):
        p_value = _report_float(row.get("p_value"))
        if p_value is not None:
            indexed.append((index, p_value, dict(row)))
    if not indexed:
        return []
    ordered = sorted(indexed, key=lambda item: item[1])
    total = len(ordered)
    adjusted = [1.0] * total
    running = 1.0
    for reverse_index in range(total - 1, -1, -1):
        rank = reverse_index + 1
        running = min(running, ordered[reverse_index][1] * total / rank)
        adjusted[reverse_index] = min(1.0, running)
    output: Table = []
    for ordered_index, (_, p_value, row) in enumerate(ordered):
        row["p_value"] = p_value
        row["p_value_bh"] = adjusted[ordered_index]
        row["reject_bh_0_05"] = adjusted[ordered_index] < 0.05
        output.append(row)
    return output


def _report_output_root(output_paths: Mapping[str, Path]) -> Path:
    for key in ("output_dir", "root", "analysis_output", "base"):
        candidate = output_paths.get(key)
        if candidate is not None:
            return Path(candidate)
    for key in ("report", "report_markdown", "analysis_report", "json", "analysis_data"):
        candidate = output_paths.get(key)
        if candidate is not None:
            return Path(candidate).parent
    return Path(DEFAULT_OUTPUT_DIRECTORY)


def _report_output_path(
    output_paths: Mapping[str, Path],
    keys: Sequence[str],
    filename: str,
) -> Path:
    for key in keys:
        candidate = output_paths.get(key)
        if candidate is not None:
            path = Path(candidate)
            if path.suffix or path.name == filename:
                return path
            return path / filename
    return _report_output_root(output_paths) / filename


def _report_plots_dir(output_paths: Mapping[str, Path]) -> Path:
    for key in ("plots_dir", "plot_dir", "plots"):
        candidate = output_paths.get(key)
        if candidate is not None:
            return Path(candidate)
    return _report_output_root(output_paths) / "plots"


def _report_atomic_text(path: Path, text: str) -> None:
    import os
    import tempfile

    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent)
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, path)
    except Exception:
        try:
            os.unlink(temporary_name)
        except OSError:
            pass
        raise


def _report_context_flag(context: Mapping[str, Any], names: Sequence[str]) -> bool:
    for name in names:
        value = _report_lookup(context, (name,), recursive=False)
        if value is not None:
            return bool(value)
    args = context.get("args") if isinstance(context, Mapping) else None
    if args is not None:
        for name in names:
            if hasattr(args, name):
                return bool(getattr(args, name))
    return False


def _report_available_columns(rows: Sequence[Mapping[str, Any]], preferred: Sequence[str]) -> List[str]:
    keys = {str(key) for row in rows for key in row.keys()}
    selected = [column for column in preferred if column in keys]
    selected.extend(sorted(keys - set(selected)))
    return selected


def _report_markdown_escape(value: Any) -> str:
    if value is None:
        return "—"
    if isinstance(value, bool):
        return "Yes" if value else "No"
    if isinstance(value, (Mapping, list, tuple, set)):
        text = json.dumps(_report_json_safe(value), ensure_ascii=False, sort_keys=True)
    else:
        text = str(value)
    return text.replace("|", "\\|").replace("\r", " ").replace("\n", "<br>")


def _report_section_title(section: Mapping[str, Any], fallback: str) -> str:
    title = _report_lookup(section, ("title", "section_title", "name"), recursive=False)
    return str(title or fallback)


def _report_condition_metric_rows(bundle: Mapping[str, Any]) -> Table:
    tables = bundle.get("tables", {}) if isinstance(bundle, Mapping) else {}
    rows = tables.get("condition_metrics", []) if isinstance(tables, Mapping) else []
    if rows:
        return _report_as_table(rows)
    global_metrics = bundle.get("global_metrics", {}) if isinstance(bundle, Mapping) else {}
    return _report_as_table(global_metrics.get("condition_metrics", [])) if isinstance(global_metrics, Mapping) else []


def _report_numeric_series(rows: Sequence[Mapping[str, Any]], aliases: Sequence[str]) -> List[Optional[float]]:
    return [_report_metric(row, aliases) for row in rows]


def build_preregistered_expectations() -> Table:
    return [
        {
            "id": "debate_vs_baseline",
            "variation": "Baseline vs statement/interactive debate",
            "expectation": "Adding adversarial PRO and CON evidence may improve judge accuracy, especially when both sides are visible together.",
            "counter_hypothesis": "Persuasive but incorrect arguments, extra context, or weak evidence evaluation may leave accuracy unchanged or reduce it.",
            "primary_metrics": "Strict accuracy, balanced accuracy, stage accuracy, paired fixes/breaks",
            "status": "preregistered expectation; not a finding",
        },
        {
            "id": "statement_vs_interactive",
            "variation": "Independent statements vs interactive rebuttal",
            "expectation": "Direct rebuttal may expose reasoning flaws beyond side-by-side independent essays.",
            "counter_hypothesis": "Side-by-side comparison may provide most of the benefit; extra turns may mainly add verbosity and positional effects.",
            "primary_metrics": "Matched accuracy change, similar-negative accuracy, first/two-turn preference",
            "status": "preregistered expectation; not a finding",
        },
        {
            "id": "stage_difficulty",
            "variation": "True, unrelated-negative, and similar-negative stages",
            "expectation": "Semantically similar incorrect tags should be harder to reject than unrelated incorrect tags.",
            "counter_hypothesis": "A conservative judge may reject both negative types equally while missing true tags.",
            "primary_metrics": "Stage accuracy, FPR by negative stage, balanced accuracy",
            "status": "preregistered expectation; not a finding",
        },
        {
            "id": "manual_ablation",
            "variation": "NLM manual absent vs present",
            "expectation": "Indexing guidance may improve fine-grained decisions, particularly similar negatives.",
            "counter_hypothesis": "The long manual may distract or overload the 0.8B judge and encourage excessive conservatism.",
            "primary_metrics": "Paired accuracy, similar-negative accuracy, FPR/FNR, fallback and calibration",
            "status": "preregistered expectation; not a finding",
        },
        {
            "id": "larger_judge",
            "variation": "Qwen3.5-0.8B vs Qwen3.5-2B rejudge",
            "expectation": "The larger judge may evaluate evidence and difficult similar tags more reliably.",
            "counter_hypothesis": "Poor or misleading debate evidence may remain the limiting factor, and a larger judge may amplify rhetoric or a side preference.",
            "primary_metrics": "Content-fixed paired accuracy, fixes/breaks, stage accuracy, bias and confidence",
            "status": "preregistered expectation; not a finding",
        },
        {
            "id": "judge_biases",
            "variation": "PRO/CON, A/B, position, turn count, and verbosity",
            "expectation": "A well-calibrated judge should follow evidence rather than side name, display order, or response length.",
            "counter_hypothesis": "Sycophancy, label preference, first/last speaker preference, two-turn advantage, or verbosity bias may affect decisions.",
            "primary_metrics": "Error asymmetry, mapped side-selection rates, paired swaps, stratified positional and length effects",
            "status": "preregistered expectation; not a finding",
        },
        {
            "id": "label_swap_invariance",
            "variation": "Original BAB vs BAB with displayed A/B labels swapped",
            "expectation": "With identical text and physical order, changing speaker names should not change the verdict.",
            "counter_hypothesis": "Frequent or directionally asymmetric flips would indicate label sensitivity or an A/B preference.",
            "primary_metrics": "Agreement, flip directions, correctness gained/lost, displayed-A selection",
            "status": "preregistered expectation; not a finding",
        },
        {
            "id": "confidence_quality",
            "variation": "Teacher-forced Yes/No, true/false, and A/B confidence",
            "expectation": "Useful confidence should discriminate errors, calibrate reasonably, and support selective prediction.",
            "counter_hypothesis": "Framing sensitivity and fallback circularity may inflate apparent agreement without improving calibration.",
            "primary_metrics": "AUC, Brier score, NLL, ECE, framing disagreement, selective accuracy",
            "status": "preregistered expectation; not a finding",
        },
    ]


def classify_effect_strength(
    point_difference: Optional[float],
    confidence_interval: Optional[Tuple[float, float]],
    causal_status: str,
) -> str:
    point = _report_fraction(point_difference)
    status = str(causal_status or "uncertain").lower()
    controlled = any(token in status for token in ("controlled", "clean", "paired", "verified"))
    confounded = any(token in status for token in ("confound", "descriptive", "historical", "implementation"))
    if point is None:
        return "unavailable"
    ci = None
    if confidence_interval is not None and len(confidence_interval) >= 2:
        low = _report_fraction(confidence_interval[0])
        high = _report_fraction(confidence_interval[1])
        if low is not None and high is not None:
            ci = (min(low, high), max(low, high))
    if confounded:
        if abs(point) < 0.005:
            return "no notable descriptive difference (confounded)"
        return "descriptive difference only (confounded)"
    if ci is None:
        if abs(point) < 0.005:
            return "no notable numerical difference; uncertainty unavailable"
        return "suggestive numerical difference; uncertainty unavailable"
    excludes_zero = ci[0] > 0.0 or ci[1] < 0.0
    if excludes_zero and controlled:
        return "clear evidence in this controlled comparison"
    if excludes_zero:
        return "suggestive difference, but comparison validity is uncertain"
    if controlled:
        return "no clear difference; the confidence interval includes zero"
    return "no clear difference; uncertainty and comparison validity limit interpretation"


def generate_accuracy_takeaway(comparison: Mapping[str, Any]) -> str:
    left, right = _report_pair_names(comparison)
    difference = _report_difference(comparison)
    ci = _report_ci(comparison)
    causal_status = _report_causal_status(comparison)
    strength = classify_effect_strength(difference, ci, causal_status)
    matched = _report_count(
        comparison,
        ("exact_matched_count", "matched_count", "n_pairs", "paired_n", "exact_matches"),
    )
    possible = _report_count(
        comparison,
        ("possible_matches", "eligible_count", "union_count", "total_records", "requested_count"),
    )
    if difference is None:
        return f"{left} vs {right}: an accuracy difference could not be computed from the available matched records."
    direction = "increased" if difference > 0 else "decreased" if difference < 0 else "did not change"
    coverage = f" on {matched:,} exact matched records" if matched is not None else ""
    if matched is not None and possible and possible > 0:
        coverage += f" ({100.0 * matched / possible:.1f}% of eligible records)"
    ci_text = ""
    if ci is not None:
        ci_text = f"; 95% CI {_report_fmt_percent(ci[0], signed=True)} to {_report_fmt_percent(ci[1], signed=True)}"
    validity = "controlled" if causal_status == "controlled" else "confounded" if causal_status == "confounded" else "validity not fully established"
    return (
        f"From {left} to {right}, accuracy {direction} by "
        f"{_report_fmt_percent(abs(difference))}{coverage}{ci_text}. "
        f"Interpretation: {strength}; comparison is {validity}."
    )


def generate_bias_takeaway(metrics: Mapping[str, Any]) -> str:
    label = _report_condition_name(metrics, "This condition")
    statements: List[str] = []
    fpr = _report_metric(metrics, ("false_positive_rate", "fpr"))
    fnr = _report_metric(metrics, ("false_negative_rate", "fnr"))
    if fpr is not None and fnr is not None:
        gap = fpr - fnr
        if abs(gap) >= 0.03:
            favored = "Yes/PRO" if gap > 0 else "No/CON"
            statements.append(
                f"error asymmetry descriptively favors {favored} "
                f"(FPR {_report_fmt_percent(fpr)} vs FNR {_report_fmt_percent(fnr)})"
            )
        else:
            statements.append(
                f"FPR and FNR are similar ({_report_fmt_percent(fpr)} vs {_report_fmt_percent(fnr)}), "
                "so there is no large error-asymmetry signal"
            )

    preference_specs = (
        ("displayed A", ("displayed_a_selection_rate", "a_selection_rate"), ("a_selection_ci", "displayed_a_selection_ci")),
        ("first speaker", ("first_speaker_selection_rate", "first_selection_rate"), ("first_selection_ci",)),
        ("two-turn speaker", ("two_turn_selection_rate", "two_turn_speaker_selection_rate"), ("two_turn_selection_ci",)),
        ("longer side", ("longer_side_selection_rate", "longer_argument_selection_rate"), ("longer_side_selection_ci",)),
    )
    for preference, rate_names, ci_names in preference_specs:
        rate = _report_metric(metrics, rate_names)
        if rate is None:
            continue
        ci_value = _report_lookup(metrics, ci_names, recursive=False)
        ci: Optional[Tuple[float, float]] = None
        if isinstance(ci_value, (list, tuple)) and len(ci_value) >= 2:
            low, high = _report_fraction(ci_value[0]), _report_fraction(ci_value[1])
            if low is not None and high is not None:
                ci = (min(low, high), max(low, high))
        p_value = _report_float(
            _report_lookup(metrics, tuple(f"{name}_p_value" for name in rate_names), recursive=False)
        )
        supported = (ci is not None and (ci[0] > 0.5 or ci[1] < 0.5)) or (p_value is not None and p_value < 0.05)
        if supported:
            direction = preference if rate > 0.5 else f"the alternative to {preference}"
            statements.append(f"mapped selections support a preference for {direction} ({_report_fmt_percent(rate)})")
        elif abs(rate - 0.5) >= 0.05:
            statements.append(
                f"{preference} was selected {_report_fmt_percent(rate)} of the time, but uncertainty is insufficient to call this a bias"
            )

    if not statements:
        return f"{label}: no interpretable mapped bias metric with adequate side/order information was available."
    return f"{label}: " + "; ".join(statements) + "."


def generate_logprob_takeaway(metrics: Mapping[str, Any]) -> str:
    label = _report_condition_name(metrics, "This confidence condition")
    auc = _report_metric(metrics, ("roc_auc", "auc", "confidence_auc"))
    brier = _report_float(_report_lookup(metrics, ("brier_score", "brier"), recursive=True))
    ece = _report_float(_report_lookup(metrics, ("expected_calibration_error", "ece"), recursive=True))
    correct_conf = _report_metric(metrics, ("mean_confidence_correct", "correct_mean_confidence"))
    error_conf = _report_metric(metrics, ("mean_confidence_incorrect", "error_mean_confidence"))
    framing = _report_metric(metrics, ("framing_disagreement_rate", "frame_disagreement_rate"))
    fallback_rate = _report_metric(metrics, ("fallback_rate", "needed_fallback_rate"))
    selective_gain = _report_metric(metrics, ("selective_accuracy_gain", "top_confidence_accuracy_gain"))

    findings: List[str] = []
    if auc is not None:
        if auc >= 0.70:
            findings.append(f"confidence discriminates errors well (AUC {_report_fmt_number(auc)})")
        elif auc >= 0.55:
            findings.append(f"confidence has modest discrimination (AUC {_report_fmt_number(auc)})")
        else:
            findings.append(f"confidence has weak or no useful discrimination (AUC {_report_fmt_number(auc)})")
    if correct_conf is not None and error_conf is not None:
        findings.append(
            f"mean confidence is {_report_fmt_percent(correct_conf)} on correct predictions and "
            f"{_report_fmt_percent(error_conf)} on errors"
        )
    if brier is not None:
        findings.append(f"Brier score is {_report_fmt_number(brier)} (lower is better)")
    if ece is not None:
        calibration = "low" if ece < 0.05 else "moderate" if ece < 0.10 else "substantial"
        findings.append(f"calibration error is {calibration} (ECE {_report_fmt_number(ece)})")
    if selective_gain is not None:
        findings.append(f"confidence-based selection changes accuracy by {_report_fmt_percent(selective_gain, signed=True)}")
    if framing is not None:
        findings.append(f"Yes/No, true/false, or A/B framings disagree on {_report_fmt_percent(framing)}")
    if fallback_rate is not None and fallback_rate > 0:
        findings.append(
            f"{_report_fmt_percent(fallback_rate)} required fallback, so prediction–confidence agreement must also be reported without fallback cases"
        )
    if not findings:
        return f"{label}: no teacher-forced confidence/log-probability metrics were available."
    return f"{label}: " + "; ".join(findings) + "."


def generate_section_takeaways(section: Mapping[str, Any]) -> List[str]:
    takeaways: List[str] = []
    comparisons = _report_find_tables(
        section,
        ("comparison", "paired_result", "manual_effect", "judge_size", "order_effect", "label_swap"),
    )
    for comparison in comparisons[:6]:
        if _report_difference(comparison) is not None:
            takeaways.append(generate_accuracy_takeaway(comparison))

    bias_rows = _report_find_tables(section, ("bias", "position", "verbosity", "selection"))
    for metrics in bias_rows[:3]:
        takeaway = generate_bias_takeaway(metrics)
        if "no interpretable" not in takeaway:
            takeaways.append(takeaway)

    logprob_rows = _report_find_tables(section, ("logprob", "confidence_metric", "calibration_metric"))
    for metrics in logprob_rows[:3]:
        takeaway = generate_logprob_takeaway(metrics)
        if "no teacher-forced" not in takeaway:
            takeaways.append(takeaway)

    title = _report_section_title(section, "section").lower()
    primary_difference = next(
        (_report_difference(row) for row in comparisons if _report_difference(row) is not None),
        None,
    )
    if "manual" in title and primary_difference is not None:
        conclusion = "helped" if primary_difference > 0 else "hurt" if primary_difference < 0 else "did not change"
        takeaways.insert(
            0,
            f"On exact matched records, the comparison direction indicates that adding the manual {conclusion} accuracy by {_report_fmt_percent(abs(primary_difference))}; use the paired CI before treating this as clear evidence.",
        )
    if any(token in title for token in ("2b", "large judge", "judge size", "rejudg")) and primary_difference is not None:
        conclusion = "improved" if primary_difference > 0 else "reduced" if primary_difference < 0 else "did not change"
        takeaways.insert(
            0,
            f"The larger judge {conclusion} matched accuracy by {_report_fmt_percent(abs(primary_difference))} in the first reported comparison; statement, ABA, and BAB results should also be read separately.",
        )

    limitations = _report_collect_strings(section, ("limitation", "caveat", "warning", "confound"))
    if limitations:
        takeaways.append(f"Limitation: {limitations[0]}")
    return _report_dedupe(takeaways)[:12]


def build_cross_experiment_synthesis(
    global_metrics: Mapping[str, Any],
    legacy_section: Mapping[str, Any],
    manual_section: Mapping[str, Any],
    pydantic_section: Mapping[str, Any],
    large_judge_section: Mapping[str, Any],
    interactive_section: Mapping[str, Any],
) -> JSONDict:
    condition_rows = _report_as_table(global_metrics.get("condition_metrics", []))
    rankings: Table = []
    for row in condition_rows:
        strict = _report_metric(row, ("strict_accuracy", "accuracy_strict", "overall_accuracy", "accuracy"))
        valid = _report_metric(row, ("valid_only_accuracy", "valid_accuracy", "accuracy_valid"))
        balanced = _report_metric(row, ("balanced_accuracy", "balanced_acc"))
        rankings.append(
            {
                "condition": _report_condition_name(row),
                "strict_accuracy": strict,
                "valid_only_accuracy": valid,
                "balanced_accuracy": balanced,
                "unknown_rate": _report_metric(row, ("unknown_rate", "invalid_rate")),
            }
        )
    rankings.sort(
        key=lambda row: (
            row.get("balanced_accuracy") is not None,
            row.get("balanced_accuracy") or -1.0,
            row.get("strict_accuracy") or -1.0,
        ),
        reverse=True,
    )

    stage_rows = _report_as_table(global_metrics.get("stage_metrics", []))
    stage_leaders: Table = []
    by_stage: Dict[str, List[Row]] = defaultdict(list)
    for row in stage_rows:
        stage = str(_report_lookup(row, ("stage", "stage_name"), default="Unknown", recursive=False))
        by_stage[stage].append(dict(row))
    for stage, rows in by_stage.items():
        scored = [
            (row, _report_metric(row, ("strict_accuracy", "accuracy", "valid_only_accuracy")))
            for row in rows
        ]
        scored = [(row, score) for row, score in scored if score is not None]
        if scored:
            winner, score = max(scored, key=lambda pair: pair[1])
            stage_leaders.append(
                {"stage": stage, "condition": _report_condition_name(winner), "accuracy": score}
            )

    sections = {
        "legacy": legacy_section,
        "manual": manual_section,
        "pydantic": pydantic_section,
        "large_judge": large_judge_section,
        "interactive": interactive_section,
    }
    controlled_findings: List[str] = []
    descriptive_findings: List[str] = []
    for section_name, section in sections.items():
        comparisons = _report_find_tables(section, ("comparison", "effect", "label_swap"))
        for comparison in comparisons:
            if _report_difference(comparison) is None:
                continue
            finding = generate_accuracy_takeaway(comparison)
            if _report_causal_status(comparison) == "controlled":
                controlled_findings.append(finding)
            else:
                descriptive_findings.append(finding)
        if not comparisons:
            generated = generate_section_takeaways(section)
            target = descriptive_findings if section_name in {"legacy", "pydantic"} else controlled_findings
            target.extend(generated[:2])

    bias_rows = _report_as_table(global_metrics.get("bias_metrics", []))
    bias_summary = [generate_bias_takeaway(row) for row in bias_rows]
    bias_summary = [text for text in bias_summary if "no interpretable" not in text]
    logprob_rows = _report_as_table(global_metrics.get("logprob_metrics", []))
    confidence_summary = [generate_logprob_takeaway(row) for row in logprob_rows]
    confidence_summary = [text for text in confidence_summary if "no teacher-forced" not in text]

    expectation_assessment: List[str] = []
    similar_rows = [
        row for row in stage_rows
        if "similar" in str(_report_lookup(row, ("stage", "stage_name"), default="", recursive=False)).lower()
    ]
    unrelated_rows = [
        row for row in stage_rows
        if "unrelated" in str(_report_lookup(row, ("stage", "stage_name"), default="", recursive=False)).lower()
    ]
    if similar_rows and unrelated_rows:
        similar_by_condition = {_report_condition_name(row): _report_metric(row, ("accuracy", "strict_accuracy")) for row in similar_rows}
        unrelated_by_condition = {_report_condition_name(row): _report_metric(row, ("accuracy", "strict_accuracy")) for row in unrelated_rows}
        common = sorted(set(similar_by_condition) & set(unrelated_by_condition))
        harder = sum(
            1 for name in common
            if similar_by_condition[name] is not None and unrelated_by_condition[name] is not None
            and similar_by_condition[name] < unrelated_by_condition[name]
        )
        if common:
            expectation_assessment.append(
                f"Similar negatives were less accurate than unrelated negatives in {harder} of {len(common)} comparable conditions."
            )

    top_takeaways: List[str] = []
    if rankings:
        best = rankings[0]
        top_takeaways.append(
            f"The highest observed balanced accuracy is {_report_fmt_percent(best.get('balanced_accuracy'))} for {best['condition']}; this ranking is descriptive unless the compared runs are controlled and candidate-matched."
        )
    top_takeaways.extend(controlled_findings[:5])
    top_takeaways.extend(expectation_assessment)

    return {
        "title": "Cross-experiment synthesis",
        "condition_ranking": rankings,
        "stage_leaders": stage_leaders,
        "controlled_findings": _report_dedupe(controlled_findings),
        "descriptive_findings": _report_dedupe(descriptive_findings),
        "bias_summary": _report_dedupe(bias_summary),
        "confidence_summary": _report_dedupe(confidence_summary),
        "expectation_assessment": expectation_assessment,
        "takeaways": _report_dedupe(top_takeaways),
        "limitations": [
            "Cross-run rankings are descriptive when prompts, candidate tags, inputs, parsers, fallback behavior, or argument text differ.",
            "Ordinary accuracy must be read with balanced accuracy because two thirds of records are negative.",
            "Unknown predictions remain separate and are failures only in explicitly labelled strict accuracy.",
        ],
    }


# =============================================================================
# 16. Report tables, plots, and output files
# =============================================================================


def initialize_analysis_bundle(
    inventory: Sequence[Mapping[str, Any]],
    catalog: Sequence[Mapping[str, Any]],
    integrity: Mapping[str, Any],
) -> JSONDict:
    return {
        "schema_version": "1.0",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "analysis_policy": {
            "record_key": ["stage", "pmid"],
            "paired_key": ["stage", "pmid", "normalized_candidate_tag", "ground_truth"],
            "expected_records_per_complete_file": EXPECTED_TOTAL_RECORDS,
            "unknown_handling": "Reported separately; incorrect for strict accuracy; excluded only from valid-only accuracy.",
            "class_balance_warning": "The task has 1,000 positive and 2,000 negative cases; report ordinary and balanced accuracy together.",
            "duplicate_policy": f"Use {CANONICAL_SWAPPED_BAB_FILE}; do not count {KNOWN_DUPLICATE_SWAPPED_BAB_FILE} independently.",
            "source_files_read_only": True,
        },
        "inventory": [dict(row) for row in inventory],
        "catalog": [dict(row) for row in catalog],
        "integrity": dict(integrity),
        "global_metrics": {},
        "sections": {},
        "section_order": [],
        "expectations": [],
        "synthesis": {},
        "tables": {},
        "multiple_testing": {},
        "findings": [],
        "notes": [],
        "generated_files": [],
    }


def assemble_analysis_bundle(
    inventory: Sequence[Mapping[str, Any]],
    catalog: Sequence[Mapping[str, Any]],
    integrity: Mapping[str, Any],
    global_metrics: Mapping[str, Any],
    legacy_section: Mapping[str, Any],
    manual_section: Mapping[str, Any],
    pydantic_section: Mapping[str, Any],
    large_judge_section: Mapping[str, Any],
    interactive_section: Mapping[str, Any],
    synthesis: Mapping[str, Any],
    expectations: Sequence[Mapping[str, Any]],
) -> JSONDict:
    bundle = initialize_analysis_bundle(inventory, catalog, integrity)
    sections = {
        "legacy_progression": dict(legacy_section),
        "manual_ablation": dict(manual_section),
        "pydantic_implementations": dict(pydantic_section),
        "large_judge_rejudging": dict(large_judge_section),
        "interactive_orders_and_labels": dict(interactive_section),
    }
    bundle["global_metrics"] = dict(global_metrics)
    bundle["sections"] = sections
    bundle["section_order"] = list(sections)
    bundle["expectations"] = [dict(row) for row in expectations]
    bundle["synthesis"] = dict(synthesis)

    pairwise: Table = []
    for section_name, section in sections.items():
        rows = _report_find_tables(section, ("comparison", "paired_result", "manual_effect", "judge_size_effect"))
        for row in rows:
            row = dict(row)
            row.setdefault("analysis_section", section_name)
            pairwise.append(row)

    patterns = _report_find_tables(interactive_section, ("prediction_pattern", "three_way_pattern", "flip_pattern"))
    provenance: Table = []
    for row in inventory:
        provenance.append(
            {
                "file": _report_lookup(row, ("filename", "file", "path"), recursive=False),
                "family": _report_lookup(row, ("family", "experiment_family"), recursive=False),
                "schema": _report_lookup(row, ("schema", "schema_type"), recursive=False),
                "source_script": _report_lookup(row, ("source_script", "generating_script", "producer"), recursive=False),
                "provenance_confidence": _report_lookup(row, ("provenance_confidence", "source_confidence"), recursive=False),
                "excluded": _report_lookup(row, ("excluded", "is_excluded"), recursive=False),
                "exclusion_reason": _report_lookup(row, ("exclusion_reason", "duplicate_of"), recursive=False),
            }
        )

    tables: Dict[str, Table] = {
        "file_inventory": [dict(row) for row in inventory],
        "condition_overview": [dict(row) for row in catalog],
        "condition_metrics": _report_as_table(global_metrics.get("condition_metrics", [])),
        "stage_metrics": _report_as_table(global_metrics.get("stage_metrics", [])),
        "bias_metrics": _report_as_table(global_metrics.get("bias_metrics", [])),
        "pairwise_comparisons": pairwise,
        "logprob_metrics": _report_as_table(global_metrics.get("logprob_metrics", [])),
        "calibration_rows": _report_as_table(global_metrics.get("calibration_rows", [])),
        "selective_rows": _report_as_table(global_metrics.get("selective_rows", [])),
        "prediction_patterns": patterns,
        "integrity_findings": _report_integrity_rows(integrity),
        "provenance": provenance,
    }
    bundle["tables"] = tables

    p_values = _report_extract_pvalues(sections)
    bundle["multiple_testing"] = {
        "method": "Benjamini-Hochberg across reported inferential p-values",
        "tests": _report_bh_rows(p_values),
        "test_count": len(p_values),
    }

    findings: List[str] = []
    for section_name in bundle["section_order"]:
        section = sections[section_name]
        existing = _report_collect_strings(section, ("takeaway", "finding", "conclusion"))
        generated = generate_section_takeaways(section)
        findings.extend(existing or generated)
    findings.extend(str(item) for item in synthesis.get("takeaways", []) if isinstance(item, str))
    bundle["findings"] = _report_dedupe(findings)
    return bundle


def convert_rows_for_csv(rows: Sequence[Mapping[str, Any]]) -> Table:
    flattened = [_report_flatten_row(dict(row)) for row in rows if isinstance(row, Mapping)]
    if not flattened:
        return []
    preferred = (
        "condition",
        "condition_id",
        "source_file",
        "filename",
        "family",
        "stage",
        "comparison",
        "condition_a",
        "condition_b",
        "total_records",
        "valid_count",
        "unknown_count",
        "strict_accuracy",
        "valid_only_accuracy",
        "balanced_accuracy",
        "accuracy_difference",
        "p_value",
        "p_value_bh",
    )
    keys = {str(key) for row in flattened for key in row}
    columns = [key for key in preferred if key in keys]
    columns.extend(sorted(keys - set(columns)))
    return [{column: row.get(column, "") for column in columns} for row in flattened]


def write_csv_table(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    import csv
    import io

    converted = convert_rows_for_csv(rows)
    if not converted:
        converted = [{"status": "no_rows_available"}]
    columns = list(converted[0].keys())
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=columns, extrasaction="ignore")
    writer.writeheader()
    for row in converted:
        writer.writerow({column: row.get(column, "") for column in columns})
    _report_atomic_text(Path(path), buffer.getvalue())


def write_json_artifact(path: Path, data: Any) -> None:
    serialized = json.dumps(
        _report_json_safe(data),
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
        allow_nan=False,
    )
    _report_atomic_text(Path(path), serialized + "\n")


def format_markdown_table(rows: Sequence[Mapping[str, Any]], columns: Sequence[str]) -> str:
    if not rows:
        return "_No data available._"
    selected = list(columns) or _report_available_columns(rows, ())
    if not selected:
        return "_No tabular columns available._"

    def display(column: str, value: Any) -> str:
        lower = column.lower()
        if value is None or value == "":
            return "—"
        number = _report_float(value)
        is_rate = any(
            token in lower
            for token in ("accuracy", "rate", "coverage", "precision", "recall", "specificity", "sensitivity", "fpr", "fnr", "prob", "percentage", "delta", "difference", "ece")
        ) and not any(token in lower for token in ("count", "n_records", "logprob"))
        if number is not None and is_rate:
            return _report_fmt_percent(number, signed=("delta" in lower or "difference" in lower))
        if number is not None:
            return _report_fmt_number(number)
        return _report_markdown_escape(value)

    header = "| " + " | ".join(_report_markdown_escape(column) for column in selected) + " |"
    separator = "| " + " | ".join("---" for _ in selected) + " |"
    body = [
        "| " + " | ".join(display(column, row.get(column)) for column in selected) + " |"
        for row in rows
    ]
    return "\n".join([header, separator] + body)


def render_inventory_section(bundle: Mapping[str, Any]) -> str:
    inventory = _report_as_table(bundle.get("inventory", []))
    lines = ["## 1. Inventory, integrity, and provenance", ""]
    if not inventory:
        lines.append("_No result-file inventory was available._")
        return "\n".join(lines)

    excluded = sum(bool(_report_lookup(row, ("excluded", "is_excluded"), default=False, recursive=False)) for row in inventory)
    complete = sum(
        _report_count(row, ("unique_record_count", "unique_keys", "record_count")) == EXPECTED_TOTAL_RECORDS
        for row in inventory
    )
    lines.append(
        f"Discovered **{len(inventory)}** result files; **{complete}** have {EXPECTED_TOTAL_RECORDS:,} unique records and **{excluded}** are excluded from independent-condition analyses."
    )
    display_rows: Table = []
    for row in inventory:
        display_rows.append(
            {
                "File": _report_lookup(row, ("filename", "file", "path"), recursive=False),
                "Family": _report_lookup(row, ("family", "experiment_family"), recursive=False),
                "Schema": _report_lookup(row, ("schema", "schema_type"), recursive=False),
                "Records": _report_lookup(row, ("record_count", "results_count", "total_records"), recursive=False),
                "Unique keys": _report_lookup(row, ("unique_record_count", "unique_keys", "unique_stage_pmid"), recursive=False),
                "Unknown": _report_lookup(row, ("unknown_count", "unknown_predictions"), recursive=False),
                "Prediction paths": _report_lookup(row, ("prediction_paths", "detected_prediction_paths"), recursive=False),
                "Source": _report_lookup(row, ("source_script", "generating_script", "producer"), recursive=False),
                "Excluded": _report_lookup(row, ("excluded", "is_excluded"), recursive=False),
            }
        )
    lines.extend(["", format_markdown_table(display_rows, list(display_rows[0].keys()))])

    duplicate_groups = _report_lookup(bundle.get("global_metrics", {}), ("duplicate_groups",), default=[], recursive=False)
    if duplicate_groups:
        lines.extend(["", "### Duplicate groups", "", _report_markdown_escape(duplicate_groups)])
    findings = _report_integrity_rows(bundle.get("integrity", {}))
    if findings:
        lines.extend(["", f"Integrity checks produced **{len(findings)}** reportable findings. See `integrity_findings.csv` for details."])
    return "\n".join(lines)


def render_condition_overview_section(bundle: Mapping[str, Any]) -> str:
    catalog = _report_as_table(bundle.get("catalog", []))
    metrics = _report_condition_metric_rows(bundle)
    metric_index = {_report_condition_name(row): row for row in metrics}
    rows: Table = []
    for condition in catalog or metrics:
        name = _report_condition_name(condition)
        metric = metric_index.get(name, condition)
        rows.append(
            {
                "Condition": name,
                "Family": _report_lookup(condition, ("family", "experiment_family"), recursive=False),
                "Judge": _report_lookup(condition, ("judge_model", "judge", "model"), recursive=False),
                "Debaters": _report_lookup(condition, ("debater_model", "debaters"), recursive=False),
                "Manual": _report_lookup(condition, ("has_manual", "uses_manual", "manual"), recursive=False),
                "Assigned tags": _report_lookup(condition, ("has_assigned_tags", "uses_assigned_tags"), recursive=False),
                "Output/fallback": _report_lookup(condition, ("output_method", "parser", "fallback_method"), recursive=False),
                "Strict accuracy": _report_metric(metric, ("strict_accuracy", "accuracy_strict", "overall_accuracy", "accuracy")),
                "Valid-only accuracy": _report_metric(metric, ("valid_only_accuracy", "valid_accuracy", "accuracy_valid")),
                "Balanced accuracy": _report_metric(metric, ("balanced_accuracy", "balanced_acc")),
                "Unknown rate": _report_metric(metric, ("unknown_rate", "invalid_rate")),
            }
        )
    lines = ["## 2. Condition overview", ""]
    if rows:
        lines.append(format_markdown_table(rows, list(rows[0].keys())))
    else:
        lines.append("_No normalized conditions were available._")
    lines.extend(
        [
            "",
            "> Strict accuracy counts `Unknown` as incorrect. Valid-only accuracy excludes unresolved outputs and must be read together with coverage. Balanced accuracy prevents the 2:1 negative-class majority from obscuring class-specific failures.",
        ]
    )
    return "\n".join(lines)


def render_analysis_section(title: str, section: Mapping[str, Any]) -> str:
    lines = [f"## {title}", ""]
    if not section:
        lines.append("_This analysis section could not be computed from the available conditions._")
        return "\n".join(lines)

    summary_rows: Table = []
    for key in ("condition_metrics", "metrics", "summary", "stage_metrics"):
        value = section.get(key)
        table = _report_as_table(value)
        if table:
            summary_rows.extend(table)
    if summary_rows:
        flat = convert_rows_for_csv(summary_rows[:30])
        columns = _report_available_columns(
            flat,
            (
                "condition",
                "family",
                "stage",
                "total_records",
                "valid_count",
                "unknown_count",
                "strict_accuracy",
                "valid_only_accuracy",
                "balanced_accuracy",
                "false_positive_rate",
                "false_negative_rate",
            ),
        )[:12]
        lines.extend(["### Metrics", "", format_markdown_table(flat, columns), ""])

    comparisons = _report_find_tables(
        section,
        ("comparison", "paired_result", "manual_effect", "judge_size_effect", "label_swap"),
    )
    if comparisons:
        display: Table = []
        for comparison in comparisons[:30]:
            left, right = _report_pair_names(comparison)
            ci = _report_ci(comparison)
            display.append(
                {
                    "A": left,
                    "B": right,
                    "Exact pairs": _report_count(comparison, ("exact_matched_count", "matched_count", "n_pairs", "paired_n")),
                    "Accuracy Δ (B−A)": _report_difference(comparison),
                    "95% CI": None if ci is None else f"{_report_fmt_percent(ci[0], signed=True)} to {_report_fmt_percent(ci[1], signed=True)}",
                    "McNemar p": _report_lookup(comparison, ("mcnemar_p_value", "mcnemar_p", "p_value"), recursive=False),
                    "Status": _report_causal_status(comparison),
                }
            )
        lines.extend(["### Paired comparisons", "", format_markdown_table(display, list(display[0].keys())), ""])

    for heading, terms in (
        ("Bias and position diagnostics", ("bias", "position", "verbosity", "selection")),
        ("Confidence and log-probability diagnostics", ("logprob", "confidence_metric", "calibration_metric")),
        ("Prediction patterns", ("prediction_pattern", "three_way_pattern", "flip_pattern")),
    ):
        rows = _report_find_tables(section, terms)
        if rows:
            flat = convert_rows_for_csv(rows[:30])
            columns = _report_available_columns(flat, ())[:12]
            lines.extend([f"### {heading}", "", format_markdown_table(flat, columns), ""])

    takeaways = _report_collect_strings(section, ("takeaway", "finding", "conclusion"))
    if not takeaways:
        takeaways = generate_section_takeaways(section)
    lines.extend(["### Takeaways", ""])
    if takeaways:
        lines.extend(f"- {item}" for item in takeaways[:12])
    else:
        lines.append("- No deterministic takeaway could be generated from the available metrics.")

    limitations = _report_collect_strings(section, ("limitation", "caveat", "warning", "confound"))
    if limitations:
        lines.extend(["", "### Section-specific limitations", ""])
        lines.extend(f"- {item}" for item in limitations[:10])
    return "\n".join(lines)


def render_limitations_section(bundle: Mapping[str, Any]) -> str:
    limitations = [
        "Runs are paired only after `(stage, pmid, normalized candidate_tag, ground_truth)` verification; `(stage, pmid)` alone is insufficient because positive candidate tags may differ.",
        "The dataset has 1,000 positive and 2,000 negative records. Always-No reaches 66.7% ordinary accuracy but only 50% balanced accuracy.",
        "`Unknown` is never converted to `No`. Strict accuracy counts it as incorrect; valid-only accuracy can be selective and must include coverage.",
        "Legacy and named Pydantic comparisons can differ in prompts, available inputs, parsing, retries, fallback behavior, candidate choice, and transcript construction. They are implementation comparisons, not pure formatting ablations.",
        "ABA and BAB transcripts were generated separately, so their difference combines speaking order/turn allocation with argument-content quality.",
        "Original BAB versus swapped-label BAB is a clean displayed-label test only after identical physical content and order have been verified.",
        "Teacher-forced Yes/No, true/false, and A/B scores are follow-up framing scores rather than token probabilities from the original explanation and need not be mutually calibrated.",
        "When fallback determines the final prediction from Yes/No scores, confidence–prediction agreement is circular; all, fallback-only, and non-fallback subsets must be reported separately.",
        "Speaker A, first position, last position, and receiving two turns are confounded in some debate formats; do not label their aggregate effect as a pure A/B bias.",
        "Multiple related tests increase false-positive risk. Benjamini–Hochberg-adjusted results are supplied alongside effect sizes and confidence intervals.",
        "The 2B rejudge is the same nominal size as the debaters, so it no longer represents the original weak-judge scalable-oversight setup.",
    ]
    dynamic: List[str] = []
    for section in bundle.get("sections", {}).values() if isinstance(bundle.get("sections"), Mapping) else []:
        dynamic.extend(_report_collect_strings(section, ("limitation", "caveat", "warning", "confound")))
    limitations.extend(_report_dedupe(dynamic))
    return "\n".join(["## Limitations", ""] + [f"- {item}" for item in _report_dedupe(limitations)])


def render_markdown_report(bundle: Mapping[str, Any]) -> str:
    generated = bundle.get("generated_at_utc", datetime.now(timezone.utc).isoformat())
    lines = [
        "# Complete analysis of PubMed/MeSH result files",
        "",
        f"Generated: `{generated}`",
        "",
        "This report recomputes all metrics from normalized records. Source result JSON files are read-only. Numerical differences are described as controlled findings only when candidate identity and reused content were verified.",
        "",
        render_inventory_section(bundle),
        "",
        render_condition_overview_section(bundle),
        "",
        "## Preregistered expectations",
        "",
        "The following expectations come from the project proposal and analysis plan; they are not findings.",
        "",
    ]
    expectations = _report_as_table(bundle.get("expectations", []))
    if expectations:
        display = [
            {
                "Variation": row.get("variation"),
                "Expectation": row.get("expectation"),
                "Counter-hypothesis": row.get("counter_hypothesis"),
                "Primary metrics": row.get("primary_metrics"),
            }
            for row in expectations
        ]
        lines.append(format_markdown_table(display, list(display[0].keys())))
    else:
        lines.append("_No expectation table was available._")

    sections = bundle.get("sections", {})
    ordered = (
        ("legacy_progression", "3. Legacy baseline → statement → interactive"),
        ("manual_ablation", "4. Baseline without manual vs with manual"),
        ("pydantic_implementations", "5. Older Pydantic implementation comparisons"),
        ("large_judge_rejudging", "6. Original 0.8B judge vs rejudged 2B judge"),
        ("interactive_orders_and_labels", "7. ABA, BAB, and swapped BAB labels"),
    )
    if not isinstance(sections, Mapping):
        sections = {}
    for key, title in ordered:
        lines.extend(["", render_analysis_section(title, sections.get(key, {}))])

    global_metrics = bundle.get("global_metrics", {})
    logprob_rows = _report_as_table(global_metrics.get("logprob_metrics", [])) if isinstance(global_metrics, Mapping) else []
    lines.extend(["", "## 8. Cross-condition confidence/log-probability overview", ""])
    if logprob_rows:
        flat = convert_rows_for_csv(logprob_rows)
        columns = _report_available_columns(
            flat,
            ("condition", "framing", "n", "threshold_accuracy", "roc_auc", "brier_score", "negative_log_likelihood", "expected_calibration_error", "framing_disagreement_rate", "fallback_rate"),
        )[:12]
        lines.append(format_markdown_table(flat, columns))
    else:
        lines.append("_No robust teacher-forced confidence fields were available._")

    synthesis = bundle.get("synthesis", {})
    lines.extend(["", "## 9. Cross-experiment synthesis", ""])
    if isinstance(synthesis, Mapping):
        ranking = _report_as_table(synthesis.get("condition_ranking", []))
        if ranking:
            lines.extend(["### Descriptive condition ranking", "", format_markdown_table(ranking, list(ranking[0].keys())), ""])
        for heading, key in (
            ("Controlled findings", "controlled_findings"),
            ("Descriptive or confounded observations", "descriptive_findings"),
            ("Bias summary", "bias_summary"),
            ("Confidence summary", "confidence_summary"),
            ("Comparison with expectations", "expectation_assessment"),
        ):
            items = synthesis.get(key, [])
            if items:
                lines.extend([f"### {heading}", ""])
                lines.extend(f"- {item}" for item in items)
                lines.append("")
    else:
        lines.append("_No synthesis was available._")

    lines.extend([render_limitations_section(bundle), ""])
    return "\n".join(lines).rstrip() + "\n"


def create_accuracy_plots(bundle: Mapping[str, Any], output_paths: Mapping[str, Path]) -> List[Path]:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    plot_dir = _report_plots_dir(output_paths)
    plot_dir.mkdir(parents=True, exist_ok=True)
    created: List[Path] = []
    rows = _report_condition_metric_rows(bundle)
    usable = []
    for row in rows:
        strict = _report_metric(row, ("strict_accuracy", "accuracy_strict", "overall_accuracy", "accuracy"))
        valid = _report_metric(row, ("valid_only_accuracy", "valid_accuracy", "accuracy_valid"))
        balanced = _report_metric(row, ("balanced_accuracy", "balanced_acc"))
        if any(value is not None for value in (strict, valid, balanced)):
            usable.append((_report_condition_name(row), strict, valid, balanced))
    if usable:
        width = 0.25
        x = list(range(len(usable)))
        fig_width = max(10.0, 0.65 * len(usable))
        fig, axis = plt.subplots(figsize=(fig_width, 6.0))
        for offset, index, label, color in (
            (-width, 1, "Strict", "#4C78A8"),
            (0.0, 2, "Valid only", "#72B7B2"),
            (width, 3, "Balanced", "#F58518"),
        ):
            values = [item[index] if item[index] is not None else float("nan") for item in usable]
            axis.bar([position + offset for position in x], values, width=width, label=label, color=color)
        axis.axhline(2.0 / 3.0, color="black", linestyle="--", linewidth=1.0, label="Always-No ordinary accuracy")
        axis.axhline(0.5, color="gray", linestyle=":", linewidth=1.0, label="Chance balanced accuracy")
        axis.set_ylim(0.0, 1.0)
        axis.set_ylabel("Accuracy")
        axis.set_title("Accuracy by normalized condition")
        axis.set_xticks(x)
        axis.set_xticklabels([item[0] for item in usable], rotation=45, ha="right")
        axis.legend(ncol=2)
        fig.tight_layout()
        path = plot_dir / "condition_accuracy.png"
        fig.savefig(path, dpi=180)
        plt.close(fig)
        created.append(path)

    stage_rows = _report_as_table(bundle.get("tables", {}).get("stage_metrics", []))
    if stage_rows:
        conditions = sorted({_report_condition_name(row) for row in stage_rows})
        stages = sorted({str(_report_lookup(row, ("stage", "stage_name"), default="Unknown", recursive=False)) for row in stage_rows})
        if conditions and stages:
            width = 0.8 / max(1, len(stages))
            fig, axis = plt.subplots(figsize=(max(10.0, 0.65 * len(conditions)), 6.0))
            for stage_index, stage in enumerate(stages):
                values = []
                for condition in conditions:
                    match = next(
                        (
                            row for row in stage_rows
                            if _report_condition_name(row) == condition
                            and str(_report_lookup(row, ("stage", "stage_name"), default="Unknown", recursive=False)) == stage
                        ),
                        None,
                    )
                    values.append(_report_metric(match or {}, ("accuracy", "strict_accuracy", "valid_only_accuracy")) or 0.0)
                offsets = [index - 0.4 + width / 2 + stage_index * width for index in range(len(conditions))]
                axis.bar(offsets, values, width=width, label=stage)
            axis.set_ylim(0.0, 1.0)
            axis.set_ylabel("Accuracy")
            axis.set_title("Stage accuracy by condition")
            axis.set_xticks(range(len(conditions)))
            axis.set_xticklabels(conditions, rotation=45, ha="right")
            axis.legend(fontsize="small")
            fig.tight_layout()
            path = plot_dir / "stage_accuracy.png"
            fig.savefig(path, dpi=180)
            plt.close(fig)
            created.append(path)

    comparisons = _report_as_table(bundle.get("tables", {}).get("pairwise_comparisons", []))
    effects = [(f"{_report_pair_names(row)[0]} → {_report_pair_names(row)[1]}", _report_difference(row)) for row in comparisons]
    effects = [(label, effect) for label, effect in effects if effect is not None]
    if effects:
        fig, axis = plt.subplots(figsize=(10.0, max(4.0, 0.4 * len(effects))))
        positions = list(range(len(effects)))
        colors = ["#54A24B" if effect >= 0 else "#E45756" for _, effect in effects]
        axis.barh(positions, [effect for _, effect in effects], color=colors)
        axis.axvline(0.0, color="black", linewidth=1.0)
        axis.set_yticks(positions)
        axis.set_yticklabels([label for label, _ in effects], fontsize="small")
        axis.set_xlabel("Paired accuracy difference (B − A)")
        axis.set_title("Matched accuracy changes")
        fig.tight_layout()
        path = plot_dir / "paired_accuracy_changes.png"
        fig.savefig(path, dpi=180)
        plt.close(fig)
        created.append(path)
    return created


def create_bias_plots(bundle: Mapping[str, Any], output_paths: Mapping[str, Path]) -> List[Path]:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    rows = _report_as_table(bundle.get("tables", {}).get("bias_metrics", []))
    plot_dir = _report_plots_dir(output_paths)
    plot_dir.mkdir(parents=True, exist_ok=True)
    created: List[Path] = []

    error_rows = []
    for row in rows:
        fpr = _report_metric(row, ("false_positive_rate", "fpr"))
        fnr = _report_metric(row, ("false_negative_rate", "fnr"))
        if fpr is not None and fnr is not None:
            error_rows.append((_report_condition_name(row), fpr, fnr))
    if error_rows:
        fig, axis = plt.subplots(figsize=(7.0, 7.0))
        axis.scatter([row[1] for row in error_rows], [row[2] for row in error_rows], color="#4C78A8")
        for name, fpr, fnr in error_rows:
            axis.annotate(name, (fpr, fnr), fontsize="x-small", xytext=(3, 3), textcoords="offset points")
        axis.plot([0, 1], [0, 1], color="gray", linestyle="--", linewidth=1.0)
        axis.set_xlim(0.0, 1.0)
        axis.set_ylim(0.0, 1.0)
        axis.set_xlabel("False-positive rate (Yes/PRO errors)")
        axis.set_ylabel("False-negative rate (No/CON errors)")
        axis.set_title("Error asymmetry by condition")
        fig.tight_layout()
        path = plot_dir / "fpr_vs_fnr.png"
        fig.savefig(path, dpi=180)
        plt.close(fig)
        created.append(path)

    preference_aliases = (
        ("Displayed A", ("displayed_a_selection_rate", "a_selection_rate")),
        ("First speaker", ("first_speaker_selection_rate", "first_selection_rate")),
        ("Two-turn speaker", ("two_turn_selection_rate", "two_turn_speaker_selection_rate")),
        ("Longer side", ("longer_side_selection_rate", "longer_argument_selection_rate")),
    )
    preference_rows = []
    for row in rows:
        for label, aliases in preference_aliases:
            rate = _report_metric(row, aliases)
            if rate is not None:
                preference_rows.append((f"{_report_condition_name(row)} — {label}", rate))
    if preference_rows:
        fig, axis = plt.subplots(figsize=(10.0, max(4.0, 0.35 * len(preference_rows))))
        positions = list(range(len(preference_rows)))
        axis.barh(positions, [rate for _, rate in preference_rows], color="#B279A2")
        axis.axvline(0.5, color="black", linestyle="--", linewidth=1.0)
        axis.set_xlim(0.0, 1.0)
        axis.set_yticks(positions)
        axis.set_yticklabels([label for label, _ in preference_rows], fontsize="x-small")
        axis.set_xlabel("Mapped selection rate")
        axis.set_title("Position, label, and verbosity selections")
        fig.tight_layout()
        path = plot_dir / "selection_preferences.png"
        fig.savefig(path, dpi=180)
        plt.close(fig)
        created.append(path)

    pattern_rows = _report_as_table(bundle.get("tables", {}).get("prediction_patterns", []))
    flip_counts = []
    for row in pattern_rows:
        label = _report_lookup(row, ("pattern", "transition", "flip_direction", "name"), recursive=False)
        count = _report_count(row, ("count", "n", "records"))
        if label is not None and count is not None:
            flip_counts.append((str(label), count))
    if flip_counts:
        fig, axis = plt.subplots(figsize=(9.0, max(4.0, 0.35 * len(flip_counts))))
        positions = list(range(len(flip_counts)))
        axis.barh(positions, [count for _, count in flip_counts], color="#ECA82C")
        axis.set_yticks(positions)
        axis.set_yticklabels([label for label, _ in flip_counts], fontsize="small")
        axis.set_xlabel("Matched records")
        axis.set_title("ABA/BAB/swapped-label prediction patterns")
        fig.tight_layout()
        path = plot_dir / "interactive_prediction_patterns.png"
        fig.savefig(path, dpi=180)
        plt.close(fig)
        created.append(path)
    return created


def create_logprob_plots(bundle: Mapping[str, Any], output_paths: Mapping[str, Path]) -> List[Path]:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    plot_dir = _report_plots_dir(output_paths)
    plot_dir.mkdir(parents=True, exist_ok=True)
    created: List[Path] = []
    rows = _report_as_table(bundle.get("tables", {}).get("logprob_metrics", []))
    quality = []
    for row in rows:
        auc = _report_metric(row, ("roc_auc", "auc", "confidence_auc"))
        brier = _report_float(_report_lookup(row, ("brier_score", "brier"), recursive=True))
        ece = _report_float(_report_lookup(row, ("expected_calibration_error", "ece"), recursive=True))
        if any(value is not None for value in (auc, brier, ece)):
            framing = _report_lookup(row, ("framing", "confidence_path", "score_type"), default="", recursive=False)
            quality.append((f"{_report_condition_name(row)} {framing}".strip(), auc, brier, ece))
    if quality:
        fig, axes = plt.subplots(1, 3, figsize=(15.0, max(5.0, 0.25 * len(quality))))
        labels = [row[0] for row in quality]
        positions = list(range(len(quality)))
        for axis, index, title, color, reference in (
            (axes[0], 1, "ROC AUC (higher better)", "#4C78A8", 0.5),
            (axes[1], 2, "Brier score (lower better)", "#F58518", None),
            (axes[2], 3, "ECE (lower better)", "#E45756", None),
        ):
            values = [row[index] if row[index] is not None else float("nan") for row in quality]
            axis.barh(positions, values, color=color)
            if reference is not None:
                axis.axvline(reference, color="black", linestyle="--", linewidth=1.0)
            axis.set_title(title)
            axis.set_yticks(positions)
            axis.set_yticklabels(labels if axis is axes[0] else [], fontsize="xx-small")
        fig.tight_layout()
        path = plot_dir / "logprob_quality.png"
        fig.savefig(path, dpi=180)
        plt.close(fig)
        created.append(path)

    calibration = _report_as_table(bundle.get("tables", {}).get("calibration_rows", []))
    grouped: Dict[str, List[Tuple[float, float]]] = defaultdict(list)
    for row in calibration:
        predicted = _report_metric(row, ("mean_confidence", "predicted_probability", "bin_confidence"))
        observed = _report_metric(row, ("empirical_accuracy", "observed_frequency", "bin_accuracy"))
        if predicted is not None and observed is not None:
            grouped[_report_condition_name(row)].append((predicted, observed))
    if grouped:
        fig, axis = plt.subplots(figsize=(7.0, 7.0))
        axis.plot([0, 1], [0, 1], color="black", linestyle="--", label="Perfect calibration")
        for name, points in sorted(grouped.items()):
            points.sort()
            axis.plot([point[0] for point in points], [point[1] for point in points], marker="o", label=name)
        axis.set_xlim(0.0, 1.0)
        axis.set_ylim(0.0, 1.0)
        axis.set_xlabel("Mean predicted probability")
        axis.set_ylabel("Observed frequency / accuracy")
        axis.set_title("Teacher-forced confidence calibration")
        axis.legend(fontsize="x-small")
        fig.tight_layout()
        path = plot_dir / "confidence_calibration.png"
        fig.savefig(path, dpi=180)
        plt.close(fig)
        created.append(path)

    selective = _report_as_table(bundle.get("tables", {}).get("selective_rows", []))
    grouped_selective: Dict[str, List[Tuple[float, float]]] = defaultdict(list)
    for row in selective:
        coverage = _report_metric(row, ("coverage", "retained_fraction", "selection_fraction"))
        accuracy = _report_metric(row, ("selective_accuracy", "accuracy", "retained_accuracy"))
        if coverage is not None and accuracy is not None:
            grouped_selective[_report_condition_name(row)].append((coverage, accuracy))
    if grouped_selective:
        fig, axis = plt.subplots(figsize=(8.0, 6.0))
        for name, points in sorted(grouped_selective.items()):
            points.sort()
            axis.plot([point[0] for point in points], [point[1] for point in points], marker="o", label=name)
        axis.set_xlim(0.0, 1.0)
        axis.set_ylim(0.0, 1.0)
        axis.set_xlabel("Coverage retained")
        axis.set_ylabel("Selective accuracy")
        axis.set_title("Accuracy after confidence-based abstention")
        axis.legend(fontsize="x-small")
        fig.tight_layout()
        path = plot_dir / "selective_accuracy.png"
        fig.savefig(path, dpi=180)
        plt.close(fig)
        created.append(path)
    return created


def create_all_plots(
    bundle: Mapping[str, Any],
    context: Mapping[str, Any],
    output_paths: Mapping[str, Path],
) -> List[Path]:
    if _report_context_flag(context, ("no_plots", "skip_plots")):
        if isinstance(bundle, dict):
            bundle.setdefault("notes", []).append("Plots were skipped by command-line configuration.")
        return []
    try:
        created = []
        created.extend(create_accuracy_plots(bundle, output_paths))
        created.extend(create_bias_plots(bundle, output_paths))
        created.extend(create_logprob_plots(bundle, output_paths))
        if isinstance(bundle, dict):
            bundle["generated_files"] = _report_dedupe(
                list(bundle.get("generated_files", [])) + [str(path) for path in created]
            )
        return created
    except (ImportError, ModuleNotFoundError) as exc:
        note = f"Plots were skipped because an optional plotting dependency is unavailable: {exc}"
        warnings.warn(note)
        if isinstance(bundle, dict):
            bundle.setdefault("notes", []).append(note)
        return []
    except Exception as exc:
        note = f"Plot generation failed non-fatally: {type(exc).__name__}: {exc}"
        warnings.warn(note)
        if isinstance(bundle, dict):
            bundle.setdefault("notes", []).append(note)
        return []


def write_all_analysis_outputs(
    bundle: Mapping[str, Any],
    report_markdown: str,
    context: Mapping[str, Any],
    output_paths: Mapping[str, Path],
) -> None:
    output_root = _report_output_root(output_paths)
    output_root.mkdir(parents=True, exist_ok=True)
    report_path = _report_output_path(
        output_paths,
        ("report", "report_markdown", "analysis_report"),
        "analysis_report.md",
    )
    json_path = _report_output_path(
        output_paths,
        ("json", "analysis_data", "data_json"),
        "analysis_data.json",
    )
    _report_atomic_text(report_path, report_markdown)

    filenames = {
        "file_inventory": "file_inventory.csv",
        "condition_metrics": "condition_metrics.csv",
        "stage_metrics": "stage_metrics.csv",
        "bias_metrics": "bias_metrics.csv",
        "pairwise_comparisons": "pairwise_comparisons.csv",
        "logprob_metrics": "logprob_metrics.csv",
        "prediction_patterns": "prediction_patterns.csv",
        "integrity_findings": "integrity_findings.csv",
        "provenance": "provenance.csv",
        "calibration_rows": "calibration_rows.csv",
        "selective_rows": "selective_accuracy.csv",
        "condition_overview": "condition_overview.csv",
    }
    tables = bundle.get("tables", {}) if isinstance(bundle, Mapping) else {}
    written = [str(report_path), str(json_path)]
    for table_name, filename in filenames.items():
        path = _report_output_path(output_paths, (table_name, f"{table_name}_csv"), filename)
        rows = tables.get(table_name, []) if isinstance(tables, Mapping) else []
        write_csv_table(path, _report_as_table(rows))
        written.append(str(path))

    if isinstance(bundle, dict):
        bundle["generated_files"] = _report_dedupe(list(bundle.get("generated_files", [])) + written)
    write_json_artifact(json_path, bundle)


def print_run_summary(bundle: Mapping[str, Any], output_paths: Mapping[str, Path]) -> None:
    inventory = _report_as_table(bundle.get("inventory", []))
    excluded = sum(bool(_report_lookup(row, ("excluded", "is_excluded"), default=False, recursive=False)) for row in inventory)
    analyzed = max(0, len(inventory) - excluded)
    integrity_rows = _report_integrity_rows(bundle.get("integrity", {}))
    fatal = sum(
        1 for row in integrity_rows
        if str(_report_lookup(row, ("severity", "level", "status"), default="", recursive=False)).lower() in {"fatal", "error"}
    )
    report_path = _report_output_path(
        output_paths,
        ("report", "report_markdown", "analysis_report"),
        "analysis_report.md",
    )
    json_path = _report_output_path(
        output_paths,
        ("json", "analysis_data", "data_json"),
        "analysis_data.json",
    )
    print("Result analysis complete.")
    print(f"  Physical JSON files discovered: {len(inventory):,}")
    print(f"  Files included in analysis:      {analyzed:,}")
    print(f"  Files excluded/deduplicated:     {excluded:,}")
    print(f"  Integrity findings:              {len(integrity_rows):,} ({fatal:,} error/fatal)")
    print(f"  Markdown report:                 {report_path}")
    print(f"  Machine-readable data:           {json_path}")
    print(f"  CSV/plot directory:              {_report_output_root(output_paths)}")
    if fatal:
        print("  WARNING: fatal/error integrity findings exist; inspect integrity_findings.csv before interpreting comparisons.")


# =============================================================================
# 17. Main orchestration
# =============================================================================


def main() -> None:
    args = parse_args()
    context = build_run_context(args)
    validate_execution_location(context)
    output_paths = prepare_output_directories(context)

    json_paths = discover_result_json_files(context)
    payloads = load_all_result_payloads(json_paths, strict=context["strict"])
    inventory = build_file_inventory(payloads)
    duplicate_groups = detect_normalized_duplicate_files(inventory)
    canonical_paths = choose_canonical_analysis_files(inventory, duplicate_groups)

    script_paths = discover_source_scripts(context)
    script_features = inspect_source_script_features(script_paths)
    provenance = reconcile_result_and_script_provenance(inventory, script_features)
    known_issues = identify_known_prompt_and_transcript_issues(provenance)

    normalized_rows, normalization_findings = normalize_all_files(
        payloads,
        inventory,
        canonical_paths,
    )
    catalog = build_condition_catalog(normalized_rows)
    integrity = run_integrity_checks(normalized_rows, inventory)

    condition_metrics, stage_metrics = compute_condition_metrics(normalized_rows)
    reference_metrics = compute_majority_reference_metrics(normalized_rows)
    bias_metrics = compute_condition_bias_metrics(normalized_rows)
    logprob_metrics, calibration_rows, selective_rows = compute_all_logprob_metrics(
        normalized_rows
    )

    global_metrics = {
        "condition_metrics": condition_metrics,
        "stage_metrics": stage_metrics,
        "reference_metrics": reference_metrics,
        "bias_metrics": bias_metrics,
        "logprob_metrics": logprob_metrics,
        "calibration_rows": calibration_rows,
        "selective_rows": selective_rows,
        "duplicate_groups": duplicate_groups,
        "normalization_findings": normalization_findings,
        "known_issues": known_issues,
    }

    legacy_section = analyze_legacy_progression(
        normalized_rows,
        catalog,
        integrity,
        context,
    )
    manual_section = analyze_manual_ablation(
        normalized_rows,
        catalog,
        integrity,
        context,
    )
    pydantic_section = analyze_pydantic_comparisons(
        normalized_rows,
        catalog,
        integrity,
        context,
    )
    large_judge_section = analyze_large_judge_section(
        normalized_rows,
        catalog,
        integrity,
        context,
    )
    interactive_section = analyze_interactive_orders_and_labels(
        normalized_rows,
        catalog,
        integrity,
        context,
    )

    expectations = build_preregistered_expectations()
    synthesis = build_cross_experiment_synthesis(
        global_metrics,
        legacy_section,
        manual_section,
        pydantic_section,
        large_judge_section,
        interactive_section,
    )

    bundle = assemble_analysis_bundle(
        inventory,
        catalog,
        integrity,
        global_metrics,
        legacy_section,
        manual_section,
        pydantic_section,
        large_judge_section,
        interactive_section,
        synthesis,
        expectations,
    )
    report_markdown = render_markdown_report(bundle)
    create_all_plots(bundle, context, output_paths)
    write_all_analysis_outputs(bundle, report_markdown, context, output_paths)
    print_run_summary(bundle, output_paths)



# BEGIN LATEST RESULTS EXTENSION
from analyze_results_latest_extension import install_latest_results_support as _install_latest_results_support
_install_latest_results_support(globals())
del _install_latest_results_support
# END LATEST RESULTS EXTENSION

if __name__ == "__main__":
    main()
