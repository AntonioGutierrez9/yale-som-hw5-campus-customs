"""Append-only audit trail: output/audit_trail.json (a JSON array, one entry per agent-loop step)."""

from __future__ import annotations

import json
import logging
import os
import re
import threading
from datetime import datetime, timezone
from pathlib import Path

from models import AuditEntry

AUDIT_PATH = Path(__file__).resolve().parent.parent / "output" / "audit_trail.json"
log = logging.getLogger("campus_customs.audit")
_lock = threading.Lock()

_SECRET_PATTERNS = [
    # "PORTKEY_API_KEY=...", "token: ...", "password is ...", "Authorization: Bearer ..."
    # (the (?![a-z]) keeps counters like "tokens_in" readable)
    (re.compile(r"(?i)(password|passcode|token|api[ _-]?key|secret|authorization)(?![a-z])[\"']?\s*(?:is|:|=)\s*"
                r"(?:bearer\s+)?[\"']?[^\s\"',}]+"),
     r"\1: [redacted]"),
    (re.compile(r"(?i)\bbearer\s+\S+"), "Bearer [redacted]"),
    (re.compile(r"\b(sk|pk)-[A-Za-z0-9_-]{8,}\b"), "[key]"),
    (re.compile(r"\b[A-Za-z0-9_-]{32,}\b"), "[token]"),  # long random strings: keys, hashes
]


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def short(value: object, limit: int = 200) -> str:
    """One line, secrets removed, cut to `limit` characters."""
    if hasattr(value, "model_dump"):  # Pydantic objects (e.g. a delegation result) -> plain JSON
        value = value.model_dump(exclude_none=True)
    text = value if isinstance(value, str) else json.dumps(value, default=str, ensure_ascii=False)
    for pattern, replacement in _SECRET_PATTERNS:
        text = pattern.sub(replacement, text)
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def append(entry: AuditEntry) -> None:
    """Add one entry to the end of the JSON array.

    Only the closing bracket is rewritten, so earlier entries are never changed
    or removed, and the file stays valid JSON after every write. If the file is
    damaged we stop rather than overwrite it.
    """
    line = json.dumps(entry.model_dump(exclude_none=True), ensure_ascii=False)
    try:
        with _lock:
            AUDIT_PATH.parent.mkdir(parents=True, exist_ok=True)
            if not AUDIT_PATH.exists() or AUDIT_PATH.stat().st_size == 0:
                AUDIT_PATH.write_bytes(f"[\n{line}\n]\n".encode("utf-8"))
                return
            with open(AUDIT_PATH, "r+b") as f:
                f.seek(0, os.SEEK_END)
                size = f.tell()
                f.seek(max(0, size - 64))
                tail = f.read()
                close = tail.rfind(b"]")
                if close == -1:
                    raise ValueError("audit_trail.json doesn't end with ']'")
                empty = tail[:close].rstrip().endswith(b"[") and size <= 64
                f.seek(size - len(tail) + close)
                f.write(((line if empty else ",\n" + line) + "\n]\n").encode("utf-8"))
                f.truncate()
    except (OSError, ValueError) as exc:  # the agents keep working; the problem is logged
        log.error("Could not write audit trail: %s", exc)
