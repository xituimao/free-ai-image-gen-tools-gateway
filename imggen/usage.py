"""Unified usage log: records calls from all access methods (API / MCP / CLI / Web) for console display.

Log file: <storage_dir>/usage.jsonl, one JSON per line.
Write operations use fcntl.flock exclusive lock to ensure multi-process concurrency safety (not just single-process thread lock).
"""
import contextlib
import json
import os
import threading
import time

try:
    import fcntl
    _HAS_FCNTL = True
except ImportError:
    # Platforms like Windows that do not support fcntl degrade to thread lock only (safe within a single process)
    fcntl = None
    _HAS_FCNTL = False


class UsageLogger(object):
    MAX_SCAN = 50000  # Maximum lines scanned per query to prevent oversized log files from exhausting memory

    def __init__(self, path):
        self.path = path
        self._lock = threading.Lock()
        os.makedirs(os.path.dirname(path), exist_ok=True)

    @contextlib.contextmanager
    def _file_lock(self, exclusive=False):
        """Cross-process file lock: writes use exclusive lock, reads use shared lock.
        Platforms that do not support fcntl (e.g., Windows) degrade to no file lock (still have thread lock)."""
        # Open with a+ to ensure the file exists and not truncate
        f = open(self.path, "a+", encoding="utf-8")
        try:
            if _HAS_FCNTL:
                mode = fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH
                fcntl.flock(f.fileno(), mode)
            yield f
        finally:
            try:
                if _HAS_FCNTL:
                    fcntl.flock(f.fileno(), fcntl.LOCK_UN)
            except Exception:
                pass
            f.close()

    def log(self, transport, client, action, trusted=False, **fields):
        """Write one usage log entry.

        transport: api / mcp / cli / web
        action: generate / configure / history / providers / upload / test / compare / heartbeat
        trusted: whether the accessor name is trusted (web/mcp/cli server-injected=True, external API self-reported=False)
        fields commonly used: provider, session_id, prompt, status(success/fail),
                    error, duration_ms, n, bytes, model
        """
        rec = {"ts": time.time(),
               "transport": transport or "api",
               "client": (client or "anonymous").strip() or "anonymous",
               "action": action, "trusted": bool(trusted)}
        rec.update(fields)
        line = json.dumps(rec, ensure_ascii=False)
        with self._lock:
            with self._file_lock(exclusive=True) as f:
                f.seek(0, os.SEEK_END)
                f.write(line + "\n")
                f.flush()

    def _read_all(self):
        """Read all log lines, return (rows, scanned). scanned is the actual number of lines scanned."""
        rows = []
        scanned = 0
        if not os.path.exists(self.path):
            return rows, scanned
        with self._lock:
            with self._file_lock(exclusive=False) as f:
                f.seek(0)
                for line in f:
                    scanned += 1
                    if scanned > self.MAX_SCAN:
                        break
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rows.append(json.loads(line))
                    except Exception:
                        continue
        return rows, scanned

    def _iter(self):
        rows, _ = self._read_all()
        for r in rows:
            yield r

    def query(self, client=None, transport=None, action=None,
              search="", sort="ts_desc", limit=200, offset=0):
        rows, scanned = self._read_all()
        if client:
            rows = [r for r in rows if r.get("client") == client]
        if transport:
            rows = [r for r in rows if r.get("transport") == transport]
        if action:
            rows = [r for r in rows if r.get("action") == action]
        if search:
            s = search.lower()
            rows = [r for r in rows if s in (r.get("prompt") or "").lower()
                    or s in (r.get("provider") or "").lower()
                    or s in (r.get("client") or "").lower()
                    or s in (r.get("action") or "").lower()]
        rev = sort in ("ts_desc", "duration_desc", "n_desc")
        key = {
            "ts_desc": lambda r: r.get("ts", 0),
            "ts_asc": lambda r: r.get("ts", 0),
            "client_asc": lambda r: r.get("client", ""),
            "client_desc": lambda r: r.get("client", ""),
            "transport_asc": lambda r: r.get("transport", ""),
            "action_asc": lambda r: r.get("action", ""),
            "duration_desc": lambda r: r.get("duration_ms", 0) or 0,
            "n_desc": lambda r: r.get("n", 0) or 0,
        }.get(sort, lambda r: r.get("ts", 0))
        rows.sort(key=key, reverse=rev)
        total = len(rows)
        page = rows[offset:offset + limit]
        return {"total": total, "scanned": scanned,
                "has_more": offset + len(page) < total,
                "truncated": scanned > self.MAX_SCAN,
                "data": page}

    def clients(self, active_window=300):
        """Aggregate statistics and status per access method. Accesses within active_window seconds are considered online."""
        agg = {}
        now = time.time()
        for r in self._iter():
            c = r.get("client", "anonymous")
            a = agg.setdefault(c, {"client": c, "count": 0, "success": 0,
                                    "fail": 0, "transports": set(),
                                    "actions": set(), "last_ts": 0,
                                    "last_action": "", "last_provider": "",
                                    "trusted": False})
            a["count"] += 1
            if r.get("status") == "success":
                a["success"] += 1
            elif r.get("status") == "fail":
                a["fail"] += 1
            if r.get("transport"):
                a["transports"].add(r["transport"])
            if r.get("action"):
                a["actions"].add(r["action"])
            if r.get("ts", 0) > a["last_ts"]:
                a["last_ts"] = r.get("ts", 0)
                a["last_action"] = r.get("action", "")
                a["last_provider"] = r.get("provider", "")
                a["trusted"] = bool(r.get("trusted", False))
        out = []
        for a in agg.values():
            rate = round(a["success"] * 100.0 / a["count"], 1) if a["count"] else 0
            online = (now - a["last_ts"]) <= active_window
            out.append({
                "client": a["client"], "count": a["count"],
                "success": a["success"], "fail": a["fail"],
                "success_rate": rate,
                "transports": sorted(a["transports"]),
                "actions": sorted(a["actions"]),
                "last_ts": a["last_ts"], "last_action": a["last_action"],
                "last_provider": a["last_provider"],
                "trusted": a["trusted"],
                "online": online,
            })
        out.sort(key=lambda x: x["last_ts"], reverse=True)
        return out
