"""Local validation only: does not print secrets or call APIs."""
import math
from urllib.parse import urlsplit
import companion
from proactive import load_config


def _enabled_section(cfg, key):
    value = cfg.get(key, {})
    if not isinstance(value, dict) or type(value.get("enabled", False)) is not bool:
        raise ValueError("Invalid feature configuration")
    return value


def _valid_endpoint(value):
    if not isinstance(value, str) or not value or any(c.isspace() for c in value):
        return False
    try:
        parsed = urlsplit(value)
        local = parsed.hostname in ("127.0.0.1", "localhost", "::1")
        return bool(parsed.hostname and parsed.path.endswith("/chat/completions")
                    and (parsed.scheme == "https" or parsed.scheme == "http" and local)
                    and parsed.username is None and parsed.password is None
                    and not parsed.query and not parsed.fragment and "?" not in value and "#" not in value
                    and "\\" not in value and (parsed.port is None or 1 <= parsed.port <= 65535))
    except (ValueError, TypeError):
        return False


def validate(cfg):
    if not isinstance(cfg, dict):
        return ["Invalid runtime configuration"]
    errors = []
    if not companion.persona_ready():
        errors.append("Fill name and personality in persona.json")
    dc = cfg.get("discord", {})
    if not isinstance(dc, dict):
        return errors + ["Invalid Discord configuration"]
    if not companion.owner_id(cfg):
        errors.append("Fill your own Discord owner_user_id")
    if not isinstance(dc.get("bot_token"), str) or not dc.get("bot_token", "").strip():
        errors.append("Fill your own Discord bot_token")
    channels = dc.get("allowed_channels", [])
    if not isinstance(channels, list) or len(channels) > 100:
        errors.append("Invalid channel allowlist")
    else:
        for item in channels:
            if (not isinstance(item, dict) or set(item) != {"guild_id", "channel_id"} or
                    any(not isinstance(item.get(k), str) or not item[k].isdigit() or
                        not 0 < int(item[k]) < 10 ** 25 for k in ("guild_id", "channel_id"))):
                errors.append("Invalid channel allowlist")
                break
    try:
        model = _enabled_section(cfg, "llm")
        ig = _enabled_section(cfg, "imagegen")
        _enabled_section(cfg, "proactive")
        _enabled_section(cfg, "research")
        awareness = _enabled_section(cfg, "awareness")
    except ValueError:
        return errors + ["Feature switches must be booleans in configuration objects"]
    import awareness as awareness_adapter
    errors.extend(awareness_adapter.config_errors(cfg))
    if not model.get("enabled"):
        errors.append("Enable and configure your chat endpoint and model")
    chain = model.get("route_chain", [])
    if chain != []:
        import llm
        errors.extend(llm.validate_chain_config(cfg))
    elif not isinstance(model.get("model"), str) or not model.get("model", "").strip() or not _valid_endpoint(model.get("endpoint")):
        errors.append("Configure a valid chat model and HTTPS or loopback endpoint")
    try:
        chance = ig.get("chance", 0)
        if isinstance(chance, bool) or not isinstance(chance, (int, float)) or not math.isfinite(chance) or not 0 <= chance <= 1:
            raise ValueError
        if chance and not ig.get("scenes"):
            errors.append("Add scenes before enabling proactive selfies")
        for key, default in (("others_per_hour", 5), ("others_per_day", 60),
                             ("proactive_selfie_per_hour", 1), ("proactive_selfie_per_day", 3)):
            limit = ig.get(key, default)
            if type(limit) is not int or not 1 <= limit <= 10000:
                errors.append("Image quota limits must be positive bounded integers")
        scenes = ig.get("scenes", [])
        if not isinstance(scenes, list) or len(scenes) > 100:
            raise ValueError
        for row in scenes:
            if not isinstance(row, list) or len(row) != 2 or not all(isinstance(s, str) and s.strip() for s in row):
                errors.append("Each scene must contain a label and description")
                break
        limits = [(cfg.get("daily_limit", 4), 0, 1000),
                  (cfg.get("min_interval_minutes", 150), 15, 10080),
                  (cfg.get("max_interval_minutes", 360), 15, 10080)]
        if any(type(value) is not int or not low <= value <= high for value, low, high in limits):
            raise ValueError
        if limits[2][0] < limits[1][0]:
            raise ValueError
        quiet = cfg.get("quiet_hours")
        if quiet is not None and quiet != []:
            if not isinstance(quiet, list) or len(quiet) != 2:
                raise ValueError
            for row in quiet:
                if not isinstance(row, list) or len(row) != 2 or any(type(v) is not int for v in row) or not 0 <= row[0] < 24 or not 0 <= row[1] < 60:
                    raise ValueError
    except (ValueError, TypeError, OverflowError):
        errors.append("Invalid proactive or image settings")
    try:
        voice = _enabled_section(cfg, "voice")
        gif = _enabled_section(cfg, "gif")
        mc = _enabled_section(cfg, "mood")
    except ValueError:
        return list(dict.fromkeys(errors + ["Feature switches must be booleans in configuration objects"]))
    if voice.get("enabled"):
        import voicegen
        if not voicegen.available(cfg):
            errors.append("Install ffmpeg and ffprobe in PATH, or set voice.ffmpeg and voice.ffprobe")
        chance = voice.get("proactive_chance", 0)
        if isinstance(chance, bool) or not isinstance(chance, (int, float)) or not 0 <= chance <= 1:
            errors.append("voice.proactive_chance must be between 0 and 1")
    if gif.get("enabled"):
        if not str(gif.get("api_key") or "").strip():
            errors.append("Fill gif.api_key for the GIF provider")
        queries = gif.get("queries")
        if not isinstance(queries, dict) or not queries:
            errors.append("Add at least one emotion keyword under gif.queries")
        elif any(not isinstance(k, str) or not isinstance(v, str) or not v.strip() for k, v in queries.items()):
            errors.append("gif.queries must map emotion names to non-empty search text")
    if mc.get("enabled"):
        chance = mc.get("chance", 0)
        if isinstance(chance, bool) or not isinstance(chance, (int, float)) or not 0 <= chance <= 1:
            errors.append("mood.chance must be between 0 and 1")
        mapping = mc.get("sticker_map")
        if not isinstance(mapping, dict):
            errors.append("mood.sticker_map must be an object of sticker name to emotion code")
        elif mapping:
            import mood
            for name, emo in mapping.items():
                if not isinstance(name, str) or not name or emo not in mood.EMOTIONS:
                    errors.append("mood.sticker_map values must be known emotion codes")
                    break
        if not isinstance(mc.get("exclude", []), list):
            errors.append("mood.exclude must be a list")
    return list(dict.fromkeys(errors))


if __name__ == "__main__":
    try:
        cfg = load_config()
        companion.configure(cfg)
        errors = validate(cfg)
    except Exception as error:
        errors = ["Config error: " + type(error).__name__]
    for message in errors:
        print(message)
    if not errors:
        print("Local config checks passed; network and model access not tested")
    raise SystemExit(1 if errors else 0)
