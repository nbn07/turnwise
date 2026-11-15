# turnwise

A Claude Code plugin that shows where a session's money goes and warns you before the two most expensive avoidable moves: resuming a large session after its prompt cache has expired, and switching models mid-session.

It is a session-cost guard and meter, not a general token saver. Every claim below links to how it was measured, including the ones that did not hold up.

## Install

In Claude Code 2.1.275 or later:

```
/plugin marketplace add nbn07/turnwise
/plugin install turnwise@turnwise
```

Everything is Python standard library: no proxy, no account, no network calls, no model calls.

To see where your money went without installing anything:

```bash
python3 turnwise/scripts/cost_anatomy.py
```

## What was measured

| Finding | Result | Where |
|---|---|---|
| Resuming a stale session against starting fresh from a handoff note | About $1.00 against $0.09 for the same follow-up bug fix, all passing. One trial in each of two sessions | [Session results](report/SESSION-RESULTS.md) |
| Switching to a cheaper model against staying, for a small job | $0.45–$0.53 against $0.13–$0.16, all passing. One trial in each of two sessions | [Session results](report/SESSION-RESULTS.md) |
| A fresh session finishing work that depends on an earlier decision | Passed 3 of 3 with the agent's own note, 3 of 3 with a pointer to the old transcript, 0 of 3 with the script note alone | [Dependent follow-up results](report/DEPENDENT-RESULTS.md) |
| Share of real spend that went on those cache rebuilds | 12% after idle gaps, 7% after model switches, across $25 of one person's desktop sessions | [Cost anatomy](research/cost-anatomy.md) |
| Working rules: speed and output | 9% fewer turns, 12% less output, 13% faster on five short coding tasks; 30 of 30 solved with and without | [Pilot results](report/PILOT-RESULTS.md) |
| Working rules: cost | Depends on the task. Feature-writing tasks: −8% and −34%. Bug fixes, a question and a rename: no saving. Overall on the five short tasks: −4.2%, interval −8.8% to +0.5%. **Not established as a general saving** | [Pilot results](report/PILOT-RESULTS.md) |
| Against Ponytail and Caveman's voice plugin, same eight tasks, 100 interleaved runs | All solved everything. Cost per solved task against no plugin: turnwise −12.4%, Ponytail −5.7%, Caveman voice +11.6%. Short, tightly specified tasks only; see the limits | [Comparison results](report/COMPARISON-RESULTS.md) |

An earlier, sequential run of the pilot showed a 13.6% cost saving. Re-run with the arms interleaved, it was 4.2% and not distinguishable from zero. The pilot report keeps both and explains the difference.

## What is here

- [turnwise/](turnwise/): the plugin, its tests, and its own README with every feature and its default.
- [bench/](bench/): the harness that produced the numbers, runnable by anyone with a Claude Code login.
- [report/](report/): the results.
- [research/](research/): the cost breakdown that shaped the design, the design itself, and a survey of other tools.

## Limits, briefly

Small samples, one model (Opus 5.5), one Claude Code version (2.1.325), macOS only. The guards inform; they do not act for you. Every feature has now been observed working in a live session at least once. See the plugin README for the full list.

## License

MIT
