#!/usr/bin/env python3
"""
03_verify_outputs.py — Sanity-check the processed JSONL files.

Usage:  python3 03_verify_outputs.py ./processed
"""

import json
import sys
from collections import Counter
from pathlib import Path


def stats(path: Path):
    print(f"\n{'='*70}\n  {path.name}\n{'='*70}")
    if not path.exists():
        print(f"  [!] Missing file"); return

    n = 0
    sources = Counter()
    field_lens = {}
    samples = []
    label_dists = {"priority": Counter(), "category": Counter(), "type": Counter()}
    skill_dist = Counter()

    with open(path) as fh:
        for line in fh:
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
            n += 1
            sources[r.get("source", "?")] += 1
            for k, v in r.items():
                if isinstance(v, str):
                    field_lens.setdefault(k, []).append(len(v))
            if "labels" in r:
                for label, val in r["labels"].items():
                    label_dists.get(label, Counter())[val] += 1
            if "required_skills" in r:
                for s in r["required_skills"]:
                    skill_dist[s] += 1
            if n <= 3:
                samples.append(r)

    print(f"  Total rows: {n:,}")
    print(f"\n  Source breakdown:")
    for src, c in sources.most_common(15):
        print(f"    {src:30s}  {c:>10,}  ({100*c/n:.1f}%)")

    if any(label_dists.values()):
        print(f"\n  Label distributions:")
        for label, dist in label_dists.items():
            if dist:
                print(f"    {label}:")
                for v, c in dist.most_common(8):
                    print(f"      {str(v):20s}  {c:>10,}")

    if skill_dist:
        print(f"\n  Top required-skill labels:")
        for s, c in skill_dist.most_common(15):
            print(f"    {s:30s}  {c:>10,}")

    print(f"\n  Field length stats (median chars):")
    for k, ls in sorted(field_lens.items()):
        if not ls: continue
        ls_sorted = sorted(ls)
        median = ls_sorted[len(ls_sorted)//2]
        p95 = ls_sorted[int(len(ls_sorted)*0.95)]
        print(f"    {k:20s}  median={median:>5}  p95={p95:>6}")

    print(f"\n  Sample row:")
    if samples:
        s = samples[0]
        for k, v in s.items():
            vstr = json.dumps(v) if not isinstance(v, str) else v
            print(f"    {k:15s}: {vstr[:120]}{'…' if len(str(vstr)) > 120 else ''}")


def main():
    out_dir = Path(sys.argv[1] if len(sys.argv) > 1 else "./processed")
    print(f"Verifying outputs in {out_dir.resolve()}")
    for fname in ["classification.jsonl", "skill_assignment.jsonl",
                  "resolution.jsonl", "instruction.jsonl"]:
        stats(out_dir / fname)


if __name__ == "__main__":
    main()
