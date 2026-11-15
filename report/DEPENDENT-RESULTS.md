# turnwise dependent follow-up test results

Run on 2026-11-15. Model `claude-opus-5-5`, Claude Code 2.1.325, headless. Rows are in [bench/results/dependent-v2/summary.csv](../bench/results/dependent-v2/summary.csv). How the test works is in [bench/README.md](../bench/README.md).

## The question

The earlier session test showed that starting fresh from a handoff note is much cheaper than resuming a stale session, but its follow-up task was self-contained. This test asks the harder question: **can a fresh session finish work that depends on something the earlier session decided?**

In each trial the agent chooses a made-up name for a helper function, then does an unrelated job whose reply is pinned to the word "done". The follow-up asks for the helper "using the name you picked earlier". The name is not in the code, not in the user's words, and not in the last answer.

## Result

**A fresh session finished the work in every trial where it had either the agent's own note or a pointer to the old transcript. With the script-built note alone and no transcript, it failed every time.** Three trials.

| Way | What the new session has | Passed | Mean cost | Mean requests |
|---|---|---:|---:|---:|
| Resume | The old session | 3 of 3 | $0.034 | 3.0 |
| Fresh, agent's note | The note the agent wrote when `warm_note` reminded it | 3 of 3 | $0.091 | 6.0 |
| Fresh, script note | The script-built note, which says where the old transcript is | 3 of 3 | $0.086 | 7.0 |
| Fresh, note alone | The script-built note, with the old transcript removed | 0 of 3 | $0.116 | 8.0 |

## What happened in each way

- **Note alone failed for the intended reason.** Each time the session read the note, saw the name was missing, looked for the transcript, and found it gone. Twice it added the helper under a new name and said so plainly. Once it declined to add it. None guessed silently.
- **The script note worked through the transcript.** All three sessions read the note, saw the name was missing, searched the old transcript where the note said it was, and found the line with the name. Each said in its reply where the name came from.
- **The agent's note worked directly.** The note named the helper in all three trials. In two of them the session also checked the transcript to confirm, which the pointer invites.
- **The agent wrote the note every time it was reminded:** three of three here, and two of two in the first version of this test. Each note gave the goal, the chosen name, where the relevant code is, what was not done, and the next step.

## What this does not show

- **Resuming was the cheapest way here, by a wide margin.** These sessions were small (about 20k tokens) and their caches were warm, because this test does not wait. That is the case where turnwise's advice is to carry on. The cost case for starting fresh is in the [session results](SESSION-RESULTS.md), on large sessions after the cache has expired. This test is about whether the work succeeds, not what it costs.
- **One kind of dependency.** A single fact (a name) that can be found by searching. A follow-up that depends on a long chain of reasoning, or on something never written down in one place, is harder and untested.
- **Small, short transcripts.** Searching a 20k-token session's transcript is easy. A transcript of several megabytes costs more to search, and the note's advice not to read it whole has not been tested at that size.
- **Three trials, one model, one Claude Code version.**
- **"Note alone" needs the transcript to be gone.** Normally it is still on disk, so in practice the script note behaves like the row above it. That row exists to show what the pointer is worth.

## How the test got here

The first version had three ways and did not isolate the decision. Its results are kept in `bench/results/dependent/`.

- Twice the agent's last answer named the helper ("the veritoxal helper is not added yet"), so the script-built note carried the name.
- Once the note did not carry it, and the fresh session went looking, found the old transcript on disk by itself, and took the name from there. That is where the transcript pointer in the note came from.
- One of three builds got no reminder. The first reminder was wrongly made to wait for 20k tokens of growth from zero, and that session opened just under 20k. Fixed, with a test.

## Cost

$1.26 for this version and $0.84 for the first: $2.10 in total.
