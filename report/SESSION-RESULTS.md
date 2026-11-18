# turnwise session test results

Run on 2026-11-14. Model `claude-opus-5-5`, cheaper model `claude-sonnet-5-5`, Claude Code 2.1.325, headless. Per-run rows are in [bench/results/sessions/summary.csv](../bench/results/sessions/summary.csv) and the transcripts in `bench/results/sessions/raw/`. How the test works is in [bench/README.md](../bench/README.md).

## Result

**In two large sessions, starting fresh from turnwise's handoff note did the same follow-up bug fix for about one eleventh of the cost of resuming the stale session, and staying on the same model did a small job for under a third of the cost of switching to a cheaper one. Every run passed its check.** The first run had one trial per session. The stale-session comparison was then repeated with five trials per session (below), which gave the same result: fresh cost about a tenth of resuming, and all 20 runs passed. The model-switch comparison still has one trial per session.

### Stale session: resume or start fresh

The follow-up task was a bug fix, started after a six-minute wait so the 5-minute prompt cache had expired.

| Session | Context | Resume | Fresh from handoff note | Fresh costs |
|---|---:|---:|---:|---:|
| click | 172,068 tokens | $0.972 | $0.086 | 9% of resume |
| more-itertools | 203,963 tokens | $1.085 | $0.090 | 8% of resume |

| | Resume | Fresh |
|---|---|---|
| Passed the project's tests | 2 of 2 | 2 of 2 |
| First request: tokens written to cache | 159,110 and 191,001 | 5,594 and 5,603 |
| Requests | 5 and 3 | 4 and 4 |
| Seconds | 25.2 and 28.6 | 13.2 and 15.9 |

The cache readings confirm the setup: each resume re-wrote the whole session, and each fresh start wrote only its small opening context. The fresh sessions needed one search to find the code again, then fixed and tested it. They did not re-read the codebase.

#### Repeat with five trials

Run on 2026-11-17 with Claude Code 2.1.327, same models and sessions, five trials per session. The order of resume and fresh alternated between trials. Rows are in [bench/results/sessions-5trial/summary.csv](../bench/results/sessions-5trial/summary.csv).

| Session | Resume: median (range) | Fresh: median (range) | Fresh costs | Passed |
|---|---:|---:|---:|---:|
| click | $0.971 ($0.932–$1.782) | $0.097 ($0.087–$0.105) | 10% of resume | 10 of 10 |
| more-itertools | $1.075 ($1.027–$1.081) | $0.100 ($0.088–$0.125) | 9% of resume | 10 of 10 |
| Both | mean $1.092 | mean $0.101 | 9% of resume | 20 of 20 |

Every resume's first request wrote 158,884 or 190,543 to 191,694 tokens to cache, and every fresh start wrote about 5,600, so the cache had expired before each run as intended. The one outlier, a $1.782 resume of click in trial 5, took 376 seconds where the others took about 20: the run stalled for more than five minutes, the cache expired again mid-run, and the session was written a second time (321,613 tokens in all). Without it, click's resumes cost $0.932 to $0.973. The test cost $14.16, including $2.23 for the two session builds.

### Model switch: switch or stay

A small job (list a file's functions), run while the session's cache was still warm.

| Session | Context | Switch to Sonnet | Stay on Opus | Stay costs |
|---|---:|---:|---:|---:|
| click | 174,823 tokens | $0.448 | $0.125 | 28% of switch |
| more-itertools | 204,183 tokens | $0.534 | $0.159 | 30% of switch |

All four runs passed. Switching re-wrote 161,167 and 190,704 tokens into the new model's cache. Staying read the session from cache and wrote about 400 tokens. The cheaper model's lower prices did not come close to paying for that rewrite on a job this small.

## What this does and does not show

- **The gap is mostly arithmetic.** A resume after expiry writes the whole context at the cache-write price. A model switch does the same for the new model. The test confirms Claude Code behaves that way and puts numbers on it.
- **The uncertain part was quality, and here it held.** A fresh session with only a script-built note found and fixed the bug both times.
- **The follow-up was self-contained.** Fixing a bug with a clear symptom needs nothing the earlier session worked out. A follow-up that depends on decisions or reasoning from the earlier session is harder for a fresh start, and the script-built note records only what was asked, which files changed, and the last answer. That case was tested afterwards: see the [dependent follow-up results](DEPENDENT-RESULTS.md).
- **The 11-to-1 ratio belongs to this setup.** Headless runs open with about 19k tokens. The desktop sessions measured earlier open with about 74k, so a fresh start costs more there. For a 150k-token desktop session the guard's own estimate is roughly $1.20 to resume against $0.60 to start fresh: about 2 to 1.
- **Headless runs use a 5-minute cache at $5 per million tokens written.** Desktop sessions use a 1-hour cache at $8, so each rebuild costs 1.6 times as much there.
- **A long stretch of work on the cheaper model can still pay for a switch.** The test covers a small job only. The break-even was not measured.
- **It shows what each choice costs, not how often people choose well.** The guard only informs.
- **Two sessions, one model.** The stale-session comparison has six trials per session across two runs; the model switch has one.

## What it means for real use

In the seven real sessions measured at the start of this project, cache rebuilds after idle gaps were 12% of spend and rebuilds after model switches were 7%. This test confirms those rebuilds are real, large, and avoidable without failing the work, at least for self-contained follow-ups. How much of that 19% a person would actually avoid depends on how often they take the cheaper path, which has not been measured.

## Cost of this test

$8.08 in total. Of that, $2.44 went on two session builds that had to be repeated after a bug in the harness's cost accounting stopped the first run early. The four model-switch results from that first run are valid and are included above.

## An accounting trap worth knowing

When Claude Code resumes a session, the `total_cost_usd` it reports covers the whole session so far, not the resumed part. The first run of this test treated it as the cost of one run and overstated four runs by the build's cost. The figures above are corrected and match the transcripts to the cent. The original file is kept as `summary.before-fix.csv`.
