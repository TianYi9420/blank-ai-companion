"""Local runtime helpers; no legacy popup or scheduled task entry point."""
import json
import random
from datetime import datetime
from pathlib import Path
import companion
ROOT = Path(__file__).resolve().parent
CONFIG_PATH = ROOT / "config.json"
STATE_PATH = ROOT / "state.json"
def load_config():
    path = CONFIG_PATH if CONFIG_PATH.exists() else ROOT / "config.example.json"
    return companion.runtime_config(json.loads(path.read_text(encoding="utf-8-sig")))
def load_state():
    try:
        return json.loads(STATE_PATH.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return {}
def save_state(state):
    STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8-sig")
def log(message):
    folder = ROOT / "logs"
    folder.mkdir(exist_ok=True)
    line = f"[{datetime.now().isoformat(timespec='seconds')}] {message}"
    print(line)
    with (folder / f"{datetime.now().date()}.log").open("a", encoding="utf-8-sig") as stream:
        stream.write(line + "\n")
def reset_daily(state, today):
    if state.get("today") != today:
        state.update(today=today, today_count=0)
def should_fire(now, cfg, state):
    if not (cfg.get("proactive") or {}).get("enabled", False):
        return False, "disabled"
    quiet = cfg.get("quiet_hours")
    if quiet:
        cur = now.hour * 60 + now.minute
        start, end = quiet[0][0] * 60 + quiet[0][1], quiet[1][0] * 60 + quiet[1][1]
        if (start <= cur < end) if start <= end else (cur >= start or cur < end):
            return False, "quiet"
    reset_daily(state, str(now.date()))
    if state.get("today_count", 0) >= int(cfg.get("daily_limit", 4)):
        return False, "limit"
    if state.get("last_fired"):
        try:
            if (now - datetime.fromisoformat(state["last_fired"])).total_seconds() < 60 * state.get("next_gap_min", 150):
                return False, "interval"
        except (ValueError, TypeError):
            return False, "invalid state"
    return True, "ok"
def draw_gap(cfg, rng):
    low = max(15, int(cfg.get("min_interval_minutes", 150)))
    return rng.randint(low, max(low, int(cfg.get("max_interval_minutes", 360))))
def describe(topic):
    return str(topic.get("data", {}).get("text") or "")
