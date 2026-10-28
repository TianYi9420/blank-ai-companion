"""Time topic and explicit, single-sample application label; no private files."""
from datetime import datetime
import awareness


def collect(cfg):
    if (not isinstance(cfg, dict) or not isinstance(cfg.get("proactive", {}), dict)
            or cfg.get("proactive", {}).get("enabled") is not True):
        return []
    now = datetime.now()
    topics = [{"kind": "context", "key": "time:" + now.strftime("%Y-%m-%d-%H"),
               "data": {"text": "現在本地時間為" + now.strftime("%H:%M") + "，可依已設定的人格發起日常關心；不能假設使用者在線、醒著或正在做任何事"}}]
    if awareness.permitted(cfg):
        try:
            text = awareness.describe(awareness.snapshot(cfg))
            if text:
                # One combined time topic avoids changing scheduling/selection semantics.
                topics[0]["data"]["text"] += "\n" + text
        except Exception:
            pass
    return topics
