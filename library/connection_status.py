# SPDX-License-Identifier: GPL-3.0-or-later
"""
Simple shared connection status for Turing Smart Screen.
Used by display loop, tray menu, and configurator UI.
"""
import json
import os
import threading
import time
from pathlib import Path

_lock = threading.Lock()
_state = {
    "connected": False,
    "reconnecting": False,
    "message": "Iniciando...",
    "last_change": time.time(),
}

_STATUS_FILE = Path(__file__).resolve().parent.parent / "connection_status.json"


def _write_status_file():
    try:
        data = dict(_state)
        tmp = _STATUS_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        tmp.replace(_STATUS_FILE)
    except Exception:
        pass


# Seconds after which a persisted status is considered stale (monitor not running).
STALE_AFTER = 20


def set_status(connected: bool = None, reconnecting: bool = None, message: str = None):
    with _lock:
        if connected is not None:
            _state["connected"] = bool(connected)
        if reconnecting is not None:
            _state["reconnecting"] = bool(reconnecting)
        if message is not None:
            _state["message"] = str(message)
        _state["last_change"] = time.time()
        _write_status_file()


def touch():
    """Refresh the heartbeat without altering the current state."""
    with _lock:
        _state["last_change"] = time.time()
        _write_status_file()


def get_status():
    with _lock:
        return dict(_state)


def is_stale(status=None, max_age: float = STALE_AFTER) -> bool:
    s = status or get_status()
    try:
        return (time.time() - float(s.get("last_change", 0))) > max_age
    except Exception:
        return True


def read_status_file():
    try:
        if _STATUS_FILE.exists():
            s = json.loads(_STATUS_FILE.read_text(encoding="utf-8"))
            if isinstance(s, dict):
                s["stale"] = is_stale(s)
                return s
    except Exception:
        pass
    s = get_status()
    s["stale"] = True
    return s


def status_text(status=None):
    s = status or get_status()
    if is_stale(s):
        return "Monitor apagado"
    if s.get("connected"):
        return "Conectado"
    if s.get("reconnecting"):
        return "Reconectando..."
    return s.get("message") or "Desconectado"
