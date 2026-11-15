#!/usr/bin/env python3
"""Show or change turnwise settings (stored in ~/.claude/turnwise/config.json).

Usage:
  config.py                      show settings
  config.py guard on|off         stale-session guard (off by default)
  config.py switch_guard on|off  model-switch warning (on by default)
  config.py warm_note on|off     in a large session, ask the agent to keep a handoff note up to date (off by default)
  config.py trim on|off          shorten large Bash and MCP results (off by default)
  config.py rules on|off         inject the working rules at session start (on by default)
  config.py threshold N          smallest context, in tokens, the guard and warm_note act on (default 80000)
  config.py note_every N         how much the context must grow before warm_note asks again (default 20000)
"""
import os, sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "hooks"))
from common import CONFIG, DEFAULTS, config, save  # noqa: E402

cfg = config()
a = sys.argv[1:]
if len(a) == 2 and a[0] in ("guard", "switch_guard", "rules", "trim", "warm_note") and a[1] in ("on", "off"):
    cfg[a[0]] = a[1] == "on"
elif len(a) == 2 and a[0] == "threshold" and a[1].isdigit():
    cfg["threshold_tokens"] = int(a[1])
elif len(a) == 2 and a[0] == "note_every" and a[1].isdigit() and int(a[1]) > 0:
    cfg["note_every_tokens"] = int(a[1])
elif a:
    sys.exit(__doc__)
if a:
    save(CONFIG, {k: cfg[k] for k in DEFAULTS})
for k in DEFAULTS:
    v = cfg[k]
    print(f"{k:<18} {'on' if v is True else 'off' if v is False else v}")
