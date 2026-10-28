#!/usr/bin/env python3
"""Compare benchmark runs side by side: one column per named group of result files.

  python3 bench/summarize.py "harness r1=bench/results/harness-20261028-19*.jsonl" \
                             "browser-use=bench/results/browser-use-*.jsonl" > bench/RESULTS-table.md

Each cell: passed/runs, mean score, mean seconds. The last rows give totals.
"""
import glob
import json
import sys
from collections import defaultdict


def load(pattern):
    rows = []
    for path in sorted(glob.glob(pattern)):
        rows += [json.loads(line) for line in open(path) if line.strip()]
    return rows


def main(specs):
    groups = []
    for spec in specs:
        name, pattern = spec.split("=", 1)
        groups.append((name, load(pattern)))
    tasks = list(dict.fromkeys(r["task"] for _, rows in groups for r in rows))
    head = "| task | " + " | ".join(name for name, _ in groups) + " |"
    out = [head, "|---|" + "---:|" * len(groups)]
    for t in tasks:
        cells = []
        for _, rows in groups:
            rs = [r for r in rows if r["task"] == t]
            if not rs:
                cells.append("–")
                continue
            p = sum(r["passed"] for r in rs)
            score = sum(r["score"] for r in rs) / len(rs)
            secs = sum(r["seconds"] or 0 for r in rs) / len(rs)
            cells.append(f"{p}/{len(rs)} · {score:.2f} · {secs:.0f} s")
        out.append(f"| {t} | " + " | ".join(cells) + " |")
    totals = []
    for _, rows in groups:
        if rows:
            totals.append(f"**{sum(r['passed'] for r in rows)}/{len(rows)}** · "
                          f"{sum(r['score'] for r in rows) / len(rows):.2f} · "
                          f"{sum(r['seconds'] or 0 for r in rows) / 60:.0f} min total")
        else:
            totals.append("–")
    out.append("| **total** | " + " | ".join(totals) + " |")
    print("\n".join(out))


if __name__ == "__main__":
    main(sys.argv[1:])
