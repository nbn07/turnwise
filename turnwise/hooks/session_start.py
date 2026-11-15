#!/usr/bin/env python3
"""SessionStart: put the turnwise rules at the start of the conversation."""
import json, os, sys

try:
    from common import ROOT, config
    json.load(sys.stdin)
    if config()["rules"] and not os.environ.get("TURNWISE_OFF"):
        rules = open(os.path.join(ROOT, "rules.md")).read()
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": rules}}))
except Exception:
    pass
