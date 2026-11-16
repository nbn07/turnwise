# Contributing to turnwise

Thanks for helping. Issues labelled [`good first issue`](https://github.com/nbn07/turnwise/labels/good%20first%20issue) are small and self-contained, and several of them need data rather than code.

## Run the tests

```
python3 turnwise/tests/test_turnwise.py
python3 bench/tests/test_harness.py
python3 bench/tests/test_sessions.py
python3 bench/tests/test_dependent.py
```

CI runs them on Linux and macOS with Python 3.9 and 3.12, and on Windows without blocking the run.

## Rules for the plugin

- **Standard library only.** No dependencies, no network calls, no model calls.
- **Hooks fail open.** On any error a hook does nothing, so turnwise can never break a session.
- **Numbers need evidence.** A claim in a README needs a run behind it, in `report/` or linked from the PR. Say how many trials you ran, and report results that go against turnwise too.
- **Paths shown to the agent use forward slashes**, and files are read and written as UTF-8.

## Sharing measurements

Raw transcripts contain your file paths, project names and Claude Code's system prompt. Do not attach them. Share the summary output of `cost_anatomy.py` or the benchmark's `summary.csv` instead, after reading it.

## Pull requests

Keep each PR to one change, add or update a test, and describe how you checked it.
