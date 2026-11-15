# turnwise pilot results

Run on 2026-11-14. Model `claude-opus-5-5`, Claude Code 2.1.325, default effort. Raw transcripts and per-run results are in [bench/results/](../bench/results/). Reproduce the analysis with:

```bash
python3 bench/harness/analyze.py
```

## Result

**Interleaved run (the one to trust): cost per solved task was 4.2% lower with turnwise, with a 95% interval of −8.8% to +0.5%. The interval includes zero, so a cost saving on these tasks is not established.** Every run was solved in both arms. turnwise did reliably use fewer turns, write less output and finish faster.

| Interleaved, 6 runs per task | Baseline | turnwise | Change | 95% interval |
|---|---:|---:|---:|---|
| Runs solved | 30 of 30 | 30 of 30 | none | |
| Cost per solved task | $0.0957 | $0.0917 | −4.2% | −8.8% to +0.5% |
| Turns (sum of task means) | 25.2 | 22.8 | −9.3% | −16.9% to −1.4% |
| Output tokens | 8,013 | 7,087 | −11.6% | −17.6% to −5.1% |
| Seconds | 94.6 | 82.0 | −13.3% | −19.3% to −7.4% |
| Cache-read tokens | 402,912 | 379,345 | −5.8% | −14.1% to +3.0% |
| Cache-write tokens | 47,310 | 47,989 | +1.4% | −1.2% to +4.1% |

| Task (interleaved) | Baseline | turnwise | Change | 95% interval |
|---|---:|---:|---:|---|
| Feature with tests (humanize) | $0.1721 | $0.1576 | −8.4% | −16.3% to −0.5% |
| Bug fix in a 4,656-line file (more-itertools) | $0.0968 | $0.0908 | −6.2% | −15.6% to +4.7% |
| Bug fix, small repo (tomli) | $0.0785 | $0.0759 | −3.4% | −18.7% to +11.1% |
| Rename across files (itsdangerous) | $0.0590 | $0.0596 | +1.2% | −4.1% to +6.2% |
| Codebase question (click) | $0.0721 | $0.0747 | +3.6% | −3.0% to +11.4% |

Only the feature task shows a saving whose interval excludes zero.

```bash
python3 bench/harness/analyze.py --summary bench/results/interleaved/summary.csv
```

### Why the first run said 13.6%

The first run did all baseline runs, then all turnwise runs. It gave −13.6% (−18.7% to −8.3%). Run interleaved, the same comparison gives −4.2%. turnwise cost almost the same both times ($0.454 and $0.459 for the five-task sum). The baseline was what moved: $0.526 in the sequential run, $0.479 interleaved. So most of the first result came from the baseline batch being expensive when it ran, not from the plugin. This is the order effect the first write-up flagged as a risk; the interleaved run confirms it was real. **The 13.6% figure should not be quoted.**

### Why fewer turns did not become a lower bill

Turns fell 9% and output fell 12%, but cost fell only 4%. On tasks this short, about a third of the cost is writing the session's opening context to the cache, which the rules cannot reduce. The rules also add about 680 tokens to that opening context, written at the cache-write price in every session. Cache-write tokens were flat to slightly up (+1.4%), which cancels much of what the shorter sessions saved.

## Longer tasks (2026-11-15)

Three multi-part tasks, three runs each, arms interleaved. Results are in `bench/results/long/`.

```bash
python3 bench/harness/analyze.py --summary bench/results/long/summary.csv
```

**Overall, cost per solved task was 16.5% lower with turnwise (95% interval −23.9% to −8.8%), with 9 of 9 solved in both arms. One task produced all of it.**

| Task | Baseline | turnwise | Change | 95% interval |
|---|---:|---:|---:|---|
| One bug plus the `metric` feature (humanize) | $0.2412 | $0.1605 | −33.5% | −41.7% to −25.6% |
| Three bugs in click's parameter types | $0.0945 | $0.0937 | −0.9% | −19.4% to +20.1% |
| Three bugs in one 4,656-line file (more-itertools) | $0.1075 | $0.1161 | +8.0% | −4.8% to +22.9% |

| Overall | Baseline | turnwise | Change | 95% interval |
|---|---:|---:|---:|---|
| Cost per solved task | $0.1478 | $0.1234 | −16.5% | −23.9% to −8.8% |
| Turns | 26.0 | 21.3 | −17.9% | −31.2% to −2.7% |
| Output tokens | 8,451 | 6,806 | −19.5% | −27.2% to −11.2% |
| Seconds | 92.2 | 76.1 | −17.4% | −25.9% to −8.5% |

What to take from it:

- **The saving is on the task that involves writing a feature, not on bug fixes.** The same was true in the short pilot, where the feature task was the only one whose interval excluded zero (−8.4%). On the two three-bug tasks here there is no saving, and one leans the other way.
- **Why the feature task differs.** The baseline read the code with several Read calls and made its changes with separate Edit calls and shell appends: 7 or 8 requests. With the rules, the agent read with two or three chained `sed -n` commands and made every change in one script: 5 or 6 requests.
- **That is a real trade.** The turnwise arm stopped using the Read and Edit tools on this task and did everything through the shell. It is cheaper, and the tests passed every time, but a scripted edit is harder for a person to review than an Edit call, and in an interactive session shell commands can prompt for permission where an edit would not.
- **These tasks are not long.** They took 5 to 12 turns and $0.08 to $0.28. The agent fixes three bugs with about the effort expected for one. The question of what the rules do in a 30-request session is still open.
- **Three tasks, three runs each.** One task carrying the result is exactly what a sample this small cannot rule out as chance in task choice. Treat the overall figure as "a saving on feature-writing tasks", not as a general number.

## First run (sequential, superseded)

Kept for the record. Arms were run one after the other.

| | Baseline | turnwise | Change | 95% interval |
|---|---:|---:|---:|---|
| Runs solved | 30 of 30 | 30 of 30 | none | |
| Cost per solved task | $0.1051 | $0.0908 | −13.6% | −18.7% to −8.3% |
| Turns (sum of task means) | 27.0 | 22.0 | −18.5% | −24.7% to −12.3% |
| Output tokens | 8,878 | 7,029 | −20.8% | −26.3% to −15.2% |
| Cache-read tokens | 443,540 | 376,896 | −15.0% | −22.4% to −6.9% |
| Cache-write tokens | 51,674 | 47,413 | −8.2% | −14.3% to −1.9% |
| Seconds | 104.6 | 87.7 | −16.2% | −23.8% to −6.8% |

Only the rules were tested. The stale-session guard, the model-switch warning, the prefix audit and adaptive trim played no part: none of them can act in a short headless run.

### Per task, first run

Six runs per task in each arm.

| Task | Baseline | turnwise | Change | 95% interval |
|---|---:|---:|---:|---|
| Bug fix in a 4,656-line file (more-itertools) | $0.1202 | $0.0892 | −25.8% | −38.2% to −9.8% |
| Bug fix, small repo (tomli) | $0.0902 | $0.0745 | −17.4% | −30.7% to −2.9% |
| Feature with tests (humanize) | $0.1818 | $0.1570 | −13.7% | −19.9% to −6.9% |
| Codebase question (click) | $0.0766 | $0.0711 | −7.2% | −15.7% to +1.7% |
| Rename across files (itsdangerous) | $0.0569 | $0.0625 | **+9.8%** | +5.3% to +15.4% |

### Where turnwise lost, first run

**The rename task cost about 10% more with turnwise, and the interval excludes zero.** The baseline already did this task in three or four requests with a single `sed` command, so there was nothing to save. The rules add about 680 tokens to the start of every session (the opening context went from 18,622 to 19,301 tokens), and on a six-cent task that overhead shows. The same will hold for any task the agent already does in the minimum number of steps.

**The question task's saving is not established.** Its interval includes zero.

### How it worked differently, first run

- **Fewer requests.** 120 against 138 across the valid runs. Each request re-reads the fixed prefix, so this is the main lever.
- **Fewer and smaller reads.** Read calls fell from 29 to 10. The turnwise arm more often got what it needed from one search with context instead of a search followed by reads.
- **Less output.** Final messages were shorter (for example 513 against 818 characters on the tomli fix), and so were tool-call arguments.
- **Verification was not skipped.** Every code-task run in both arms ran the tests or executed the code before finishing: 24 of 24 in each arm.
- **No subagents were used** in either arm, so the delegation rule was never exercised.

## Limits

- **Five short, easy tasks.** Three to nine requests each, on well-known repos the model may recognise, with one-line bugs. The intervals cover run-to-run variation on these tasks only.
- **Six runs per task is few.** The overall interval is about nine points wide. A true saving of a few percent cannot be confirmed or ruled out at this size.
- **One model, one Claude Code version, default effort.**
- **No competitor was run.**
- **Only the working rules were tested.** The guard, the model-switch warning, the prefix audit and adaptive trim cannot act in a short headless run.
- **One earlier run is excluded.** The first version of the feature task had a wrong prompt; its row (`feature-humanize-metric`, without `-v2`) is left out.
- **Costs are Claude Code's own `total_cost_usd`** at API list prices.

## What this means for turnwise

- **The rules make the agent quicker and terser on every kind of task tested.** Whether they make it cheaper depends on the task: on the two feature-writing tasks they did (−8% and −34%), on bug fixes, a question and a rename they did not.
- **A general "saves X% on coding tasks" claim is not supported.**
- **The untested part is where the design expected the money to be.** In the real interactive sessions measured earlier, cache rebuilds after idle gaps and model switches were 18% of spend, and the fixed prefix was four times larger than in these runs. None of that appears in a short headless task.

## Next

1. Cut the rules' own overhead. They cost about 680 tokens per session; the delegation and stop-loss rules were never exercised in 60 runs and could go.
2. Test on longer tasks (30 or more requests), where the opening context is a small share of cost and fewer requests should matter more.
3. Build the session track for the guard, the model-switch warning and the prefix audit.
4. Add competitor arms, interleaved.
5. Use more runs per task; six is too few to resolve an effect of a few percent.
