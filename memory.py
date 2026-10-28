"""Scoped, append-only companion history, Markdown readable in Obsidian.

Legacy memory/spoken.jsonl is deliberately never opened. Private history cannot be
selected through a guild question; caller supplies a validated, trusted scope.
"""
from collections import deque
from datetime import datetime
from pathlib import Path
import json
import re
import threading

from runtime_paths import DATA_ROOT, data_path, reject_links

ROOT = DATA_ROOT
VAULT = data_path("companion_vault")
# Kept for compatibility, but never read or written by this module.
STORE = ROOT / "memory" / "spoken.jsonl"
LOCK = threading.RLock()
_SCOPE = re.compile(r"(?:local|dm_[1-9][0-9]{0,24}|guild_[1-9][0-9]{0,24}_thread_[1-9][0-9]{0,24}_user_[1-9][0-9]{0,24})\Z")


def _path(scope):
    if not isinstance(scope, str) or not _SCOPE.fullmatch(scope):
        raise ValueError("Invalid memory scope")
    area = "groups" if scope.startswith("guild_") else "private"
    base = VAULT.resolve()
    target = VAULT / area / (scope + ".md")
    reject_links(target)
    if VAULT.is_symlink() or target.parent.is_symlink() or target.is_symlink():
        raise ValueError("Linked memory path rejected")
    if not target.resolve().is_relative_to(base):
        raise ValueError("Memory outside vault")
    return target


def append(text, kind="", channel="local", role="assistant", *, scope="local", user_id=None):
    path = _path(scope)
    row = {"ts": datetime.now().isoformat(timespec="seconds"), "scope": scope,
           "role": "assistant" if role == "assistant" else "user", "kind": str(kind)[:40],
           "channel": str(channel)[:40], "text": str(text)[:12000]}
    # JSON is contained in fenced Markdown, not executable Markdown directives.
    # Backticks in content are JSON-escaped to stop closing the fence.
    encoded = json.dumps(row, ensure_ascii=False).replace("`", "\\u0060")
    with LOCK:
        path.parent.mkdir(parents=True, exist_ok=True)
        new = not path.exists()
        with path.open("a", encoding="utf-8") as stream:
            if new:
                stream.write("# 陪伴對話紀錄\n\n")
            stream.write("```json\n" + encoded + "\n```\n\n")


def recent(n=6, *, scope="local", legacy_assistant_roles=()):
    path = _path(scope)
    if not path.exists():
        return []
    # Bound reading to 256 KiB even if a long-lived log is large.
    with LOCK, path.open("rb") as stream:
        stream.seek(0, 2)
        size = stream.tell()
        stream.seek(max(0, size - 262144))
        raw = stream.read(262144).decode("utf-8", errors="replace")
    found = deque(maxlen=max(0, min(int(n), 30)))
    legacy_roles = {r for r in legacy_assistant_roles if isinstance(r, str)
                    and r.casefold() not in ("user", "system", "developer", "tool")}
    for line in raw.splitlines():
        if not line.startswith("{"):
            continue
        try:
            row = json.loads(line)
            if not isinstance(row, dict):
                continue
            if row.get("scope") == scope and isinstance(row.get("text"), str):
                role = row.get("role")
                if isinstance(role, str) and (role in ("user", "assistant") or role in legacy_roles):
                    found.append({**row, "role": "user" if role == "user" else "assistant"})
        except (ValueError, TypeError):
            continue
    return list(found)


_ROOM = re.compile(r"guild_[1-9][0-9]{0,24}_thread_[1-9][0-9]{0,24}\Z")
PEOPLE_FACTS_PER_PERSON = 8


def _people_path(room):
    if not isinstance(room, str) or not _ROOM.fullmatch(room):
        raise ValueError("Invalid room key")
    base = VAULT.resolve()
    target = VAULT / "people" / (room + ".md")
    reject_links(target)
    if VAULT.is_symlink() or target.parent.is_symlink() or target.is_symlink():
        raise ValueError("Linked memory path rejected")
    if not target.resolve().is_relative_to(base):
        raise ValueError("Memory outside vault")
    return target


def _load_people(room):
    path = _people_path(room)
    if not path.exists():
        return {}
    try:
        raw = path.read_text(encoding="utf-8")
        start, end = raw.find("```json\n"), raw.rfind("\n```")
        data = json.loads(raw[start + 8:end]) if start >= 0 and end > start else {}
        return data if isinstance(data, dict) else {}
    except (ValueError, OSError):
        return {}


def remember_people(room, mentioned, statement, *, speaker_id, speaker_is_owner):
    """記住同頻道被標註的人：名字＋誰說了關於他的哪句話（不讀私聊）。"""
    if not mentioned:
        return
    statement = re.sub(r"\s+", " ", str(statement or "")).strip()[:200]
    with LOCK:
        people = _load_people(room)
        now = datetime.now().isoformat(timespec="seconds")
        for pid, name in mentioned:
            key = str(int(pid))
            rec = people.get(key) or {"names": [], "facts": []}
            name = re.sub(r"[`\n\r]", "", str(name or ""))[:40]
            if name and name not in rec["names"]:
                rec["names"] = (rec["names"] + [name])[-3:]
            if statement:
                fact = {"ts": now, "by": "owner" if speaker_is_owner else "member",
                        "by_id": str(int(speaker_id)), "text": statement}
                if not rec["facts"] or rec["facts"][-1].get("text") != statement:
                    rec["facts"] = (rec["facts"] + [fact])[-PEOPLE_FACTS_PER_PERSON:]
            people[key] = rec
        path = _people_path(room)
        path.parent.mkdir(parents=True, exist_ok=True)
        encoded = json.dumps(people, ensure_ascii=False, indent=1).replace("`", "\\u0060")
        path.write_text("# 頻道人物備忘\n\n```json\n" + encoded + "\n```\n", encoding="utf-8")


def people_block(room, ids, *, text="", limit=6):
    """只回傳本則訊息提到的人（被@或直接寫出已知名字）的備忘，避免塞入無關人物。"""
    people = _load_people(room)
    wanted = [str(int(i)) for i in ids]
    lowered = str(text or "").lower()
    for pid, rec in people.items():
        if any(len(n) >= 2 and n.lower() in lowered for n in rec.get("names", [])):
            wanted.append(pid)
    rows = []
    for pid in list(dict.fromkeys(wanted))[:limit]:
        rec = people.get(pid)
        if not rec:
            continue
        rows.append({"id": pid, "names": rec.get("names", []),
                     "notes": [{"by": f["by"], "text": f["text"]} for f in rec.get("facts", [])]})
    return json.dumps(rows, ensure_ascii=False) if rows else ""


def _photo_reference_path(scope):
    checked = _path(scope)
    target = checked.with_name(checked.stem + "_photo_refs.json")
    reject_links(target)
    if target.is_symlink():
        raise ValueError("Linked reference index rejected")
    return target


def remember_photo_source(scope, *, channel_id, message_id, author_id, attachment_ids):
    """只保存来源ID，不保存CDN链接、姓名、照片或识别身份。"""
    if not isinstance(attachment_ids, (list, tuple)) or not 1 <= len(attachment_ids) <= 2:
        raise ValueError("Invalid reference attachments")
    values = [str(v) for v in (channel_id, message_id, author_id)]
    ids = [str(i) for i in attachment_ids]
    if any(not re.fullmatch(r"[1-9][0-9]{0,24}", v) for v in values + ids):
        raise ValueError("Invalid reference IDs")
    path = _photo_reference_path(scope)
    row = dict(zip(("channel_id", "message_id", "author_id"), values))
    row["attachment_ids"] = ids
    with LOCK:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(row, ensure_ascii=False), encoding="utf-8-sig")


def photo_source(scope):
    path = _photo_reference_path(scope)
    with LOCK:
        if not path.exists():
            return None
        with path.open("rb") as handle:
            raw = handle.read(4097)
        if len(raw) > 4096:
            raise ValueError("Reference index too large")
        row = json.loads(raw.decode("utf-8-sig"))
    if not isinstance(row, dict) or set(row) != {"channel_id", "message_id", "author_id", "attachment_ids"}:
        raise ValueError("Invalid reference index")
    ids = row["attachment_ids"]
    if not isinstance(ids, list) or not 1 <= len(ids) <= 2:
        raise ValueError("Invalid reference attachments")
    if any(not isinstance(v, str) or not re.fullmatch(r"[1-9][0-9]{0,24}", v)
           for v in [row["channel_id"], row["message_id"], row["author_id"]] + ids):
        raise ValueError("Invalid reference IDs")
    return row


def history_block(n=6, *, scope="local", legacy_assistant_roles=()):
    rows = recent(n, scope=scope, legacy_assistant_roles=legacy_assistant_roles)
    # Histories are quoted data, never a system instruction or a trusted identity.
    return json.dumps([{"role": r["role"], "text": r["text"][:4000]} for r in rows], ensure_ascii=False) if rows else ""
