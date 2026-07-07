#!/usr/bin/env python3
"""
merge_chunks.py

Merge the per-chunk result files of one evaluation into a single *_full.json,
which is what submit_rejudge.sh expects as its --source.

The merge is de-duplicated on (stage, pmid) -- exactly the checkpoint key used
by debate_utils.load_checkpoint -- so overlaps (should there be any) collapse
to one record. Writing is atomic (temp file + os.replace), matching the
crash-proof style of debate_utils.save_results_atomically.

Usage:
    python3 merge_chunks.py interactive_results
    python3 merge_chunks.py statement_results
    python3 merge_chunks.py <base_name> [directory]

Produces:  <base_name>_full.json
"""

import os
import re
import sys
import json
import glob
import tempfile

CHUNK_RE_TMPL = r"^{base}_chunk(\d+)\.json$"


def save_atomically(path, data):
    dir_name = os.path.dirname(path) or "."
    with tempfile.NamedTemporaryFile("w", dir=dir_name, delete=False,
                                     encoding="utf-8") as tf:
        json.dump(data, tf, indent=4, ensure_ascii=False)
        tmp = tf.name
    try:
        os.replace(tmp, path)
    except Exception:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise


def main():
    if len(sys.argv) < 2:
        sys.exit("Usage: python3 merge_chunks.py <base_name> [directory]")
    base = sys.argv[1]
    directory = os.path.abspath(sys.argv[2] if len(sys.argv) > 2 else os.getcwd())

    rx = re.compile(CHUNK_RE_TMPL.format(base=re.escape(base)))
    files = []
    for path in glob.glob(os.path.join(directory, "%s_chunk*.json" % base)):
        m = rx.match(os.path.basename(path))
        if m:
            files.append((int(m.group(1)), path))
    files.sort()

    if not files:
        sys.exit("No %s_chunk*.json files found in %s" % (base, directory))

    merged = []
    seen = set()
    dupes = 0
    metadata = {}
    for cid, path in files:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        metadata = data.get("metadata", metadata)
        for r in data.get("results", []):
            key = (r.get("stage"), r.get("pmid"))
            if key in seen:
                dupes += 1
                continue
            seen.add(key)
            merged.append(r)
        print("  + chunk%d: %d records" % (cid, len(data.get("results", []))))

    out_path = os.path.join(directory, "%s_full.json" % base)
    metadata = dict(metadata)
    metadata["merged_from"] = [os.path.basename(p) for _, p in files]
    metadata["merged_records"] = len(merged)
    save_atomically(out_path, {"metadata": metadata, "results": merged})

    print("Merged %d records (%d duplicate keys dropped) -> %s"
          % (len(merged), dupes, os.path.basename(out_path)))


if __name__ == "__main__":
    main()
