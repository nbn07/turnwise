# turnwise against Ponytail and Caveman

Run on 2026-11-15. Model `claude-opus-5-5`, Claude Code 2.1.325, headless, default effort. Four arms interleaved on eight tasks, three runs each (four on one task): 100 runs. Rows are in [bench/results/competitors/summary.csv](../bench/results/competitors/summary.csv).

```bash
python3 bench/harness/analyze.py --summary bench/results/competitors/summary.csv --b ponytail
```

## Result

**Every arm solved every task. On cost per solved task, turnwise's rules came out 12% below the baseline, Ponytail 6% below, and Caveman's voice plugin 12% above.**

| Arm | Solved | Cost per solved task against baseline | 95% interval | Turns | Output tokens |
|---|---:|---:|---|---:|---:|
| Baseline (no plugin) | 25 of 25 | | | | |
| turnwise rules | 25 of 25 | −12.4% | −17.0% to −7.3% | −24.4% | −19.8% |
| Ponytail 5.3.3 | 25 of 25 | −5.7% | −10.0% to −1.0% | −11.9% | −22.4% |
| Caveman 4.1.0, voice only | 24 of 24 | +11.6% | +7.1% to +16.8% | −7.8% | −10.0% |

turnwise against Ponytail directly: turnwise 7.1% lower (−11.3% to −2.7%).

One Caveman run is left out of its row: the computer went to sleep in the middle of it, the cache expired, and the run cost $0.36 through no fault of the tool. With that run included, Caveman reads +16.1%. No other run was affected.

## Short and long tasks

| Tasks | turnwise | Ponytail | Caveman |
|---|---:|---:|---:|
| Five short tasks | −5.5% | −1.5% | +14.8% |
| Three longer tasks | −19.7% | −10.2% | +17.5% |

For turnwise this matches the earlier runs, which were made separately: −4.2% on the short tasks and −16.5% on the longer ones.

## Per task, cost against baseline

| Task | turnwise | Ponytail | Caveman |
|---|---:|---:|---:|
| Bug fix, small repo | −5.8% | −8.4% | +16.7% |
| Bug fix, large file | −5.4% | +7.1% | +22.5% |
| Feature with tests | −12.7% | −13.7% | +0.1% |
| Codebase question | −2.0% | +7.0% | +17.2% |
| Rename across files | +12.3% | +19.3% | +41.1% |
| Three bugs, large file | −24.4% | −1.9% | +16.5% |
| Three bugs, click | −5.0% | +3.3% | +19.1% |
| Bug plus feature | −23.7% | −20.5% | +17.2% (sleep-hit run included) |

With three runs per task, single rows are unstable. "Three bugs, large file" shows −24% for turnwise here and showed +8% in the earlier run of the same task.

## Why the numbers come out this way

**A plugin's footprint costs money on every session, and on tasks this short it decides the result.** The opening context, before any work:

| Arm | Opening context | Above baseline |
|---|---:|---:|
| Baseline | 18,779 tokens | |
| turnwise | 19,494 | +715 |
| Ponytail | 20,508 | +1,729 |
| Caveman | 22,545 | +3,766 |

That footprint is the tool's rules plus the listing of every skill and command the plugin registers. Caveman registers about twenty skills. All of it is written to the cache at the start of each session.

- **Caveman did what it says: output fell 10%.** But it wrote 30% more to the cache, and on tasks that cost around ten cents the extra opening context outweighs the shorter replies. It was also slightly faster than the baseline.
- **Ponytail cut output the most (−22%)** and saved clearly on the two feature tasks. Its larger footprint cost it on the short ones.
- **turnwise cut turns the most (−24%)** with the smallest footprint. It still loses on the rename, as in every earlier run.
- **All three lose on the rename task.** It is done in three or four requests with no room to save, so each tool's result there is simply its footprint.

## What this does not show

- **This is not Caveman 4.0.** Only its voice plugin was loaded. Its input compression, model picking and cache keep-warm need its own installer or an account and were not tested. Its voice is aimed at chat-style answers; these tasks produce mostly code and tool calls.
- **These tasks are not Ponytail's ground.** It is built to stop an agent over-building on open-ended requests. Every task here is tightly specified, with little to over-build. Its own benchmark includes open-ended build tasks and reports a larger saving.
- **Short sessions punish footprint.** In a session of a hundred requests, a few thousand tokens of opening context matter far less, and savings per request matter more. Nothing here was longer than about a dozen requests.
- **I built turnwise and chose the tasks.** The rules were written before any of these tasks existed and were not tuned on them, but the choice of tasks is mine and both pilot results on them were known before this run.
- **Three or four runs per task, eight tasks, one model, one Claude Code version.** The overall intervals cover run-to-run variation on these tasks only.
- **Both competitors' one-time status-line prompt was cleared before the run**, so no session carried it.
- **Both competitors were active in every run:** their rules text is in all 25 of each arm's transcripts and in the requests sent to the model.

## What it supports saying

On short, tightly specified coding tasks with Opus 5.5, turnwise's rules cost less per solved task than Ponytail or Caveman's voice, and the gap comes mostly from being smaller. It does not support saying turnwise is better than either tool in general.

## Cost

$11.59 for the 100 runs.
