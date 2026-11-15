"""Shared helpers for turnwise hooks. Stdlib only. Every hook fails open: on any error, do nothing."""
import datetime, json, os, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
from cost_anatomy import price  # noqa: E402

HOME = os.environ.get("TURNWISE_HOME") or os.path.expanduser("~/.claude/turnwise")
CONFIG = os.path.join(HOME, "config.json")
STATE = os.path.join(HOME, "state.json")
DEFAULTS = {"rules": True, "guard": False, "switch_guard": True, "trim": False, "warm_note": False, "threshold_tokens": 80000,
            "note_every_tokens": 20000}


def load(path, default):
    try:
        return {**default, **json.load(open(path))}
    except (OSError, ValueError):
        return dict(default)


def save(path, data):
    os.makedirs(HOME, exist_ok=True)
    json.dump(data, open(path, "w"), indent=1)


def config():
    return load(CONFIG, DEFAULTS)


def session_state(path):
    """Last request of a transcript: context size, model, cache lifetime, idle time, opening context size."""
    last = first = None
    for line in open(path, errors="replace"):
        if '"usage"' not in line:
            continue
        try:
            d = json.loads(line)
        except ValueError:
            continue
        if not isinstance(d, dict):
            continue
        m = d.get("message") or {}
        if d.get("type") == "assistant" and not d.get("isSidechain") and m.get("usage") and price(m.get("model")):
            last = d
            first = first or d
    if not last:
        return None

    def ctx(d):
        u = d["message"]["usage"]
        return u.get("input_tokens", 0) + u.get("cache_creation_input_tokens", 0) + u.get("cache_read_input_tokens", 0)

    u = last["message"]["usage"]
    one_hour = (u.get("cache_creation") or {}).get("ephemeral_1h_input_tokens", 0) > 0
    ts = datetime.datetime.fromisoformat(last["timestamp"].replace("Z", "+00:00"))
    idle = (datetime.datetime.now(datetime.timezone.utc) - ts).total_seconds()
    return {"context": ctx(last) + u.get("output_tokens", 0), "opening": ctx(first), "model": last["message"]["model"],
            "ttl": 3600 if one_hour else 300, "one_hour": one_hour, "idle": idle, "last_ts": last["timestamp"]}


def write_cost(tokens, model, one_hour=True):
    p = price(model)
    return tokens * p[2 if one_hour else 1] / 1e6 if p else 0.0


def span(seconds):
    m = int(seconds // 60)
    return f"{m // 60}h {m % 60}m" if m >= 60 else f"{m}m"


def block(message):
    """Stop the action and show the message to the user."""
    print(message, file=sys.stderr)
    sys.exit(2)
