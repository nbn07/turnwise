#!/usr/bin/env python3
"""Compare two arms from bench/results/summary.csv. Stdlib only.

  python3 bench/harness/analyze.py [--a baseline] [--b turnwise] [--summary PATH]

Reports, per task and overall: runs, pass rate, mean cost, and the change from arm A to arm B with a
95% bootstrap interval. The overall figure is the change in cost per solved task, with each task
weighted equally by taking its mean first (so a task that happened to get more runs does not count more).
The bootstrap resamples runs within each task and arm, 10,000 times, with a fixed seed.
"""
import argparse, collections, csv, os, random, statistics

HERE = os.path.dirname(os.path.abspath(__file__))
INVALID = {"feature-humanize-metric"}      # v1 prompt was wrong; see bench/README.md
METRICS = [("cost_usd", "cost $"), ("turns", "turns"), ("output", "output tokens"), ("cache_write", "cache-write tokens"),
           ("cache_read", "cache-read tokens"), ("duration_s", "seconds")]


def load(path):
    data = collections.defaultdict(lambda: collections.defaultdict(list))
    with open(path, newline="") as f:
        for r in csv.DictReader(f):
            if r["task"] not in INVALID:
                data[r["task"]][r["arm"]].append(r)
    return data


def values(rows, key):
    return [float(r[key] or 0) for r in rows]


def change(a, b):
    return 100 * (b - a) / a if a else float("nan")


def interval(samples_a, samples_b, rng, n=10000):
    """95% bootstrap interval for the % change in the sum of per-task means."""
    out = []
    for _ in range(n):
        ta = sum(statistics.fmean(rng.choices(s, k=len(s))) for s in samples_a)
        tb = sum(statistics.fmean(rng.choices(s, k=len(s))) for s in samples_b)
        out.append(change(ta, tb))
    out.sort()
    return out[int(0.025 * n)], out[int(0.975 * n) - 1]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--a", default="baseline")
    ap.add_argument("--b", default="turnwise")
    ap.add_argument("--summary", default=os.path.join(os.path.dirname(HERE), "results", "summary.csv"))
    args = ap.parse_args()
    data = load(args.summary)
    tasks = [t for t in data if data[t].get(args.a) and data[t].get(args.b)]
    if not tasks:
        raise SystemExit(f"no task has runs in both {args.a} and {args.b}")
    rng = random.Random(20261114)

    print(f"{args.a} -> {args.b}   ({len(tasks)} tasks)\n")
    print(f"{'task':<34}{'runs':>7}{'passed':>9}{'mean cost':>16}{'change':>8}   {'95% interval':<18}{'cost range ' + args.a:>22}")
    for t in tasks:
        ra, rb = data[t][args.a], data[t][args.b]
        ca, cb = values(ra, "cost_usd"), values(rb, "cost_usd")
        lo, hi = interval([ca], [cb], rng)
        print(f"{t:<34}{len(ra):>3}/{len(rb):<3}{sum(int(r['passed']) for r in ra):>4}/{sum(int(r['passed']) for r in rb):<4}"
              f"{statistics.fmean(ca):>8.4f}/{statistics.fmean(cb):<7.4f}{change(statistics.fmean(ca), statistics.fmean(cb)):>7.1f}%   "
              f"[{lo:+.1f}%, {hi:+.1f}%]".ljust(18) + f"   {min(ca):.3f}-{max(ca):.3f}")

    print(f"\n{'overall (tasks weighted equally)':<34}{args.a:>12}{args.b:>12}{'change':>9}   95% interval")
    for key, label in METRICS:
        sa = [values(data[t][args.a], key) for t in tasks]
        sb = [values(data[t][args.b], key) for t in tasks]
        ta, tb = sum(map(statistics.fmean, sa)), sum(map(statistics.fmean, sb))
        lo, hi = interval(sa, sb, rng)
        mark = "" if lo <= 0 <= hi else "   <- interval excludes zero"
        print(f"  {label:<32}{ta:>12.4f}{tb:>12.4f}{change(ta, tb):>8.1f}%   [{lo:+.1f}%, {hi:+.1f}%]{mark}")

    def solved(arm):
        rows = [r for t in tasks for r in data[t][arm]]
        return sum(int(r["passed"]) for r in rows), len(rows), sum(float(r["cost_usd"]) for r in rows)
    for arm in (args.a, args.b):
        ok, n, spent = solved(arm)
        print(f"\n{arm}: {ok}/{n} solved, ${spent:.2f} spent" + (f", ${spent / ok:.4f} per solved task" if ok else ""), end="")
    models = {r["model"] for t in tasks for arm in (args.a, args.b) for r in data[t][arm]}
    versions = {r["claude_version"] for t in tasks for arm in (args.a, args.b) for r in data[t][arm]}
    print(f"\n\nmodel: {', '.join(sorted(models))} · Claude Code: {', '.join(sorted(versions))}")


if __name__ == "__main__":
    main()
