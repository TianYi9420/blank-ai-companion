"""Explicit local migration preflight. Never converts, writes, or launches a deployment.

Only fixed diagnostic codes are returned. Inputs and unknown key names are never
included in output. Passing this check does not authorize connection or cutover.
"""
import argparse
from datetime import date, datetime
import json
import math
from pathlib import Path
import stat
from urllib.parse import urlsplit

TOP = frozenset(("discord", "llm", "imagegen", "proactive", "quiet_hours", "daily_limit",
                 "min_interval_minutes", "max_interval_minutes", "awareness",
                 "memory_sources", "sources", "research", "discord_webhook_url"))
FIELDS = {
    "discord": {"bot_token", "owner_user_id", "allowed_channels"},
    "llm": {"enabled", "endpoint", "api_token", "model", "vision_model", "timeout_seconds",
            "max_tokens", "route_chain", "chain_deadline_seconds", "retry_backoff_seconds", "allow_paid_fallback"},
    "imagegen": {"enabled", "provider", "endpoint", "api_key", "model", "anchor", "manga_anchor",
                 "persona_group", "manga_style", "quality", "size", "others_per_hour", "others_per_day",
                 "chance", "proactive_selfie_per_hour", "proactive_selfie_per_day", "scenes"},
    "proactive": {"enabled"}, "awareness": {"enabled", "share_app_label"},
    "research": {"enabled", "bilibili_enabled", "provider"},
}
PERSONA = frozenset(("name", "gender", "relationship", "appearance", "personality", "language",
                     "owner_nickname", "aliases", "legacy_assistant_roles"))
MANUAL = ["credentials_and_service_authorization_unverified", "fees_not_verified",
          "private_data_and_quota_not_imported", "anchor_files_not_verified",
          "old_process_must_be_stopped_before_cutover", "network_and_delivery_not_tested"]


def _text(value):
    return isinstance(value, str) and bool(value.strip())


def _integer(value, low, high):
    return type(value) is int and low <= value <= high


def _number(value, low, high):
    if type(value) not in (int, float):
        return False
    try:
        return math.isfinite(value) and low <= value <= high
    except OverflowError:
        return False


def _id(value):
    return isinstance(value, str) and 1 <= len(value) <= 25 and value.isascii() and value.isdecimal() and 0 < int(value) < 10 ** 25


def _endpoint(value, chat=False):
    if not _text(value) or any(c.isspace() for c in value) or any(c in value for c in ("?", "#", "\\")):
        return False
    try:
        p = urlsplit(value)
        local = p.hostname in ("127.0.0.1", "localhost", "::1")
        return bool(p.hostname and (p.scheme == "https" or p.scheme == "http" and local)
                    and p.username is None and p.password is None
                    and (p.port is None or 1 <= p.port <= 65535)
                    and (not chat or p.path.endswith("/chat/completions")))
    except (ValueError, TypeError):
        return False


def _image_endpoint(value):
    if not _endpoint(value):
        return False
    p = urlsplit(value)
    return p.hostname in ("127.0.0.1", "localhost", "::1") and p.path.rstrip("/") in ("", "/v1")


def inspect_config(cfg, persona):
    """Pure in-memory schema preflight; neither discovers files nor mutates input."""
    errors, notices = [], []
    def add(code):
        if code not in errors:
            errors.append(code)
    if not isinstance(cfg, dict) or not isinstance(persona, dict):
        add("invalid_document_shape")
        cfg, persona = {}, {}
    if set(cfg) - TOP:
        add("unmapped_top_level_fields")
    if set(persona) - PERSONA:
        add("unmapped_persona_fields")
    for key in ("name", "personality"):
        if not _text(persona.get(key)):
            add("persona_required_fields_missing")
    for key in PERSONA - {"aliases", "legacy_assistant_roles"}:
        if key in persona and not isinstance(persona[key], str):
            add("invalid_persona_field_types")
    for key in ("aliases", "legacy_assistant_roles"):
        items = persona.get(key, [])
        if (not isinstance(items, list) or len(items) > 12 or
                any(not _text(v) or len(v) > 80 or any(ord(c) < 32 for c in v) for v in items)):
            add("invalid_persona_labels")
        elif key == "legacy_assistant_roles" and any(v.strip().lower() in ("user", "system", "developer", "tool") for v in items):
            add("reserved_legacy_role")
    sections = {}
    for key, allowed in FIELDS.items():
        value = cfg.get(key, {})
        if not isinstance(value, dict):
            add("invalid_" + key + "_section")
            value = {}
        if set(value) - allowed:
            add("unmapped_" + key + "_fields")
        if key != "discord" and type(value.get("enabled", False)) is not bool:
            add("invalid_" + key + "_switch")
        sections[key] = value
    dc = sections["discord"]
    if not _text(dc.get("bot_token")) or not _id(dc.get("owner_user_id")):
        add("discord_identity_missing_or_invalid")
    channels = dc.get("allowed_channels", [])
    if (not isinstance(channels, list) or len(channels) > 100 or any(
        not isinstance(row, dict) or set(row) != {"guild_id", "channel_id"} or
        not all(_id(row.get(k)) for k in ("guild_id", "channel_id")) for row in channels)):
        add("channel_allowlist_requires_explicit_mapping")
    model = sections["llm"]
    if model.get("enabled") is not True:
        add("chat_disabled")
    chain = model.get("route_chain", [])
    if chain != []:
        import llm
        try:
            if llm.validate_chain_config({"llm": model}):
                add("model_chain_requires_explicit_mapping")
        except Exception:
            add("model_chain_requires_explicit_mapping")
    elif not _text(model.get("model")) or not _endpoint(model.get("endpoint"), chat=True):
        add("single_endpoint_requires_explicit_model_and_endpoint")
    if "api_token" in model and not isinstance(model["api_token"], str):
        add("invalid_model_credential_type")
    if "vision_model" in model and (not isinstance(model["vision_model"], str) or
        len(model["vision_model"]) > 256 or model["vision_model"] != model["vision_model"].strip() or
        any(ord(c) < 32 or ord(c) == 127 for c in model["vision_model"])):
        add("invalid_explicit_vision_model")
    if type(sections["research"].get("bilibili_enabled", False)) is not bool:
        add("invalid_research_subfeature_switch")
    if not _number(model.get("timeout_seconds", 90), 0.1, 120) or not _integer(model.get("max_tokens", 2000), 1, 32768):
        add("invalid_single_endpoint_limits")
    ig = sections["imagegen"]
    if ig.get("enabled") is True and (ig.get("provider") != "openai_images" or
        not all(_text(ig.get(k)) for k in ("api_key", "model")) or not _image_endpoint(ig.get("endpoint"))):
        add("image_service_requires_explicit_mapping")
    if not _number(ig.get("chance", 0), 0, 1):
        add("invalid_selfie_chance")
    scenes = ig.get("scenes", [])
    if (not isinstance(scenes, list) or len(scenes) > 100 or any(
        not isinstance(row, list) or len(row) != 2 or not all(_text(s) for s in row) for row in scenes)):
        add("invalid_private_scene_structure")
    elif ig.get("chance") and not scenes:
        add("private_scenes_require_explicit_mapping")
    for key in ("others_per_hour", "others_per_day", "proactive_selfie_per_hour", "proactive_selfie_per_day"):
        if key in ig and not _integer(ig[key], 1, 10000):
            add("invalid_image_quota_limits")
    import awareness as awareness_adapter
    for code in awareness_adapter.config_errors(cfg):
        add(code)
    if awareness_adapter.permitted(cfg):
        notices.append("application_label_sharing_requires_separate_live_authorization")
    for key in ("daily_limit", "min_interval_minutes", "max_interval_minutes"):
        low, high, default = (0, 1000, 4) if key == "daily_limit" else (15, 10080, 150 if key.startswith("min") else 360)
        if not _integer(cfg.get(key, default), low, high):
            add("invalid_proactive_limits")
    minimum, maximum = cfg.get("min_interval_minutes", 150), cfg.get("max_interval_minutes", 360)
    if type(minimum) is int and type(maximum) is int and maximum < minimum:
        add("invalid_proactive_limits")
    quiet = cfg.get("quiet_hours", [])
    if quiet is not None and quiet != [] and (not isinstance(quiet, list) or len(quiet) != 2 or any(
        not isinstance(row, list) or len(row) != 2 or not _integer(row[0], 0, 23) or
        not _integer(row[1], 0, 59) for row in quiet)):
        add("invalid_quiet_hours")
    if cfg.get("memory_sources", "off") != "off" or cfg.get("sources", {}) != {} or cfg.get("discord_webhook_url", "") != "":
        add("legacy_sources_require_explicit_retirement")
    if sections["research"].get("enabled") is True:
        notices.append("research_requires_separate_network_authorization")
    if ig.get("enabled") is True:
        notices.append("images_require_separate_network_authorization")
    if sections["proactive"].get("enabled") is True:
        notices.append("proactive_requires_separate_delivery_authorization")
    return {"schema_version": 1, "schema_result": "BLOCKED" if errors else "PASS",
            "cutover_authorized": False, "private_values_emitted": False,
            "writes_performed": False, "network_performed": False,
            "blockers": errors, "notices": notices, "manual_checks": list(MANUAL)}


def inspect_state(state):
    """Synthetic or explicitly provided in-memory state only; never resets counters."""
    valid = isinstance(state, dict) and {"today", "today_count"} <= state.keys()
    if valid:
        try:
            value = state["today"]
            valid = isinstance(value, str) and date.fromisoformat(value).isoformat() == value
            valid = valid and _integer(state["today_count"], 0, 1000)
            if state.get("last_fired"):
                value = datetime.fromisoformat(state["last_fired"])
                valid = valid and value.tzinfo is None
            if "next_gap_min" in state:
                valid = valid and _integer(state["next_gap_min"], 15, 10080)
            valid = valid and not state.get("_invalid_state", False)
        except (ValueError, TypeError, OverflowError):
            valid = False
    return {"schema_result": "PASS" if valid else "BLOCKED",
            "counters_reset": False, "data_imported": False}


def _read_explicit(path):
    # No runtime_paths import: the active deployment environment is never consulted.
    path = Path(path)
    if not path.is_absolute():
        raise ValueError("input_rejected")
    for part in (path, *path.parents):
        info = part.lstat()
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400):
            raise ValueError("input_rejected")
    with path.open("rb") as stream:
        data = stream.read(1048577)
    if len(data) > 1048576:
        raise ValueError("input_rejected")
    def no_duplicates(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("input_rejected")
            result[key] = value
        return result
    return json.loads(data.decode("utf-8-sig"), object_pairs_hook=no_duplicates,
                      parse_constant=lambda _: (_ for _ in ()).throw(ValueError("input_rejected")))


def main(argv=None):
    class SafeParser(argparse.ArgumentParser):
        def error(self, message):
            raise ValueError("input_rejected")
    parser = SafeParser(description="Local schema preflight only; never migrates data or starts services.")
    parser.add_argument("--config", required=True)
    parser.add_argument("--persona", required=True)
    try:
        args = parser.parse_args(argv)
        report = inspect_config(_read_explicit(args.config), _read_explicit(args.persona))
    except Exception:
        report = {"schema_result": "BLOCKED", "blockers": ["input_unreadable_or_invalid"],
                  "cutover_authorized": False, "writes_performed": False, "network_performed": False}
    print(json.dumps(report, ensure_ascii=True, sort_keys=True))
    return 0 if report["schema_result"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
