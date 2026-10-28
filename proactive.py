"""Local runtime helpers; no legacy popup or scheduled task entry point."""
import json
import random
from datetime import datetime
from pathlib import Path
import companion
from runtime_paths import APP_ROOT, DATA_ROOT, data_path, reject_links
ROOT = DATA_ROOT
CONFIG_PATH = data_path("config.json")
STATE_PATH = data_path("state.json")
def load_config():
    reject_links(CONFIG_PATH)
    path = CONFIG_PATH if CONFIG_PATH.exists() else APP_ROOT / "config.example.json"
    cfg = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(cfg, dict):
        raise ValueError("Invalid runtime configuration")
    return companion.runtime_config(cfg)
def load_state():
    reject_links(STATE_PATH)
    if not STATE_PATH.exists():
        return {}
    try:
        value = json.loads(STATE_PATH.read_text(encoding="utf-8-sig"))
        if not isinstance(value, dict) or "today" not in value or "today_count" not in value:
            raise ValueError("Invalid proactive state")
        if (not isinstance(value["today"], str) or
                datetime.strptime(value["today"], "%Y-%m-%d").date().isoformat() != value["today"] or
                type(value["today_count"]) is not int or not 0 <= value["today_count"] <= 1000):
            raise ValueError("Invalid proactive state")
        if value.get("last_fired"):
            last = datetime.fromisoformat(value["last_fired"])
            if last.tzinfo is not None:
                raise ValueError("Invalid proactive timestamp")
        if "next_gap_min" in value and (type(value["next_gap_min"]) is not int or not 15 <= value["next_gap_min"] <= 10080):
            raise ValueError("Invalid proactive interval")
        return value
    except (OSError, ValueError, TypeError, OverflowError):
        # Existing but invalid state is never treated as an unused daily budget.
        return {"_invalid_state": True}
def save_state(state):
    reject_links(STATE_PATH)
    STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8-sig")
def log(message):
    # Diagnostics must never turn completed delivery into a retry request.
    line = f"[{datetime.now().isoformat(timespec='seconds')}] {message}"
    try:
        print(line)
    except Exception:
        pass
    try:
        folder = data_path("logs")
        folder.mkdir(exist_ok=True)
        with data_path("logs", f"{datetime.now().date()}.log").open("a", encoding="utf-8-sig") as stream:
            stream.write(line + "\n")
    except Exception:
        pass
def reset_daily(state, today):
    if state.get("today") != today:
        state.update(today=today, today_count=0)
def should_fire(now, cfg, state):
    if not isinstance(state, dict) or state.get("_invalid_state"):
        return False, "invalid state"
    if (cfg.get("proactive") or {}).get("enabled") is not True:
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
