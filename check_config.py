"""Local validation only: does not print secrets or call APIs."""
from urllib.parse import urlsplit
from pathlib import Path
import companion
from proactive import load_config

def validate(cfg):
    errors = []
    if not companion.persona_ready(): errors.append("Fill name and personality in persona.json")
    if not companion.owner_id(cfg): errors.append("Fill your own Discord owner_user_id")
    if not (cfg.get("discord") or {}).get("bot_token"): errors.append("Fill your own Discord bot_token")
    model = cfg.get("llm") or {}
    parsed = urlsplit(model.get("endpoint") or "")
    if not model.get("enabled") or not model.get("model") or not parsed.path.endswith("/chat/completions"):
        errors.append("Enable and configure your chat endpoint and model")
    if parsed.scheme != "https" and not (parsed.scheme == "http" and parsed.hostname in ("127.0.0.1", "localhost", "::1")):
        errors.append("Remote model endpoint must use HTTPS")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        errors.append("Do not put credentials in the endpoint URL")
    if not parsed.hostname:
        errors.append("Model endpoint hostname is required")
    try:
        if parsed.port is not None and not 1 <= parsed.port <= 65535:
            errors.append("Invalid model endpoint port")
    except ValueError:
        errors.append("Invalid model endpoint port")
    try:
        ig = cfg.get("imagegen") or {}
        chance = float(ig.get("chance") or 0)
        if not 0 <= chance <= 1:
            errors.append("Selfie chance must be between 0 and 1")
        if chance and not ig.get("scenes"):
            errors.append("Add scenes before enabling proactive selfies")
        for row in ig.get("scenes") or []:
            if not isinstance(row, list) or len(row) != 2 or not all(isinstance(s, str) and s.strip() for s in row):
                errors.append("Each scene must contain a label and description")
        if int(cfg.get("daily_limit", 4)) < 0:
            errors.append("Daily limit cannot be negative")
        low, high = int(cfg.get("min_interval_minutes", 150)), int(cfg.get("max_interval_minutes", 360))
        if low < 15 or high < low:
            errors.append("Invalid proactive interval")
        quiet = cfg.get("quiet_hours")
        if quiet and (len(quiet) != 2 or any(len(x) != 2 or not 0 <= int(x[0]) < 24 or not 0 <= int(x[1]) < 60 for x in quiet)):
            errors.append("Invalid quiet hours")
    except (ValueError, TypeError, OverflowError):
        errors.append("Invalid proactive settings")
    return errors
if __name__ == "__main__":
    try:
        cfg = load_config()
        companion.configure(cfg)
        errors = validate(cfg)
    except Exception as error:
        errors = ["Config error: " + type(error).__name__]
    for message in errors: print(message)
    if not errors: print("Local config checks passed; network and model access not tested")
    raise SystemExit(1 if errors else 0)
