"""No desktop, browser, project index or private file collection."""
from datetime import datetime
def collect(cfg):
    if not (cfg.get("proactive") or {}).get("enabled", False):
        return []
    now = datetime.now()
    return [{"kind": "context", "key": "time:" + now.strftime("%Y-%m-%d-%H"),
             "data": {"text": "現在本地時間為" + now.strftime("%H:%M") + "，可依已設定的人格發起日常關心；不能假設使用者在線、醒著或正在做任何事"}}]
