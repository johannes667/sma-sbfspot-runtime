import os
from datetime import datetime
from typing import List

from config import LOG_FILE

MAX_LOG_LINES = 5000


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def sanitize(message: object) -> str:
    text = str(message).replace("\r", " ").strip()
    # Keep the log readable and avoid huge SBFspot dumps in the WebGUI.
    if len(text) > 2000:
        text = text[:2000] + " ..."
    return text


def log_event(level: str, message: object) -> None:
    os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
    level = (level or "INFO").upper()
    line = f"[{now_iso()}] [{level}] {sanitize(message)}\n"
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line)
        # Simple rotation: keep the last MAX_LOG_LINES lines.
        try:
            with open(LOG_FILE, "r", encoding="utf-8", errors="ignore") as f:
                lines = f.readlines()
            if len(lines) > MAX_LOG_LINES:
                tmp = LOG_FILE + ".tmp"
                with open(tmp, "w", encoding="utf-8") as f:
                    f.writelines(lines[-MAX_LOG_LINES:])
                os.replace(tmp, LOG_FILE)
        except Exception:
            pass
    except Exception:
        # Logging must never crash the collector.
        pass


def read_log_lines(limit: int = 300) -> List[str]:
    limit = max(1, min(int(limit or 300), MAX_LOG_LINES))
    try:
        with open(LOG_FILE, "r", encoding="utf-8", errors="ignore") as f:
            return [line.rstrip("\n") for line in f.readlines()[-limit:]]
    except Exception:
        return []


def clear_log() -> None:
    os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
    with open(LOG_FILE, "w", encoding="utf-8") as f:
        f.write(f"[{now_iso()}] [INFO] Log wurde geleert\n")
