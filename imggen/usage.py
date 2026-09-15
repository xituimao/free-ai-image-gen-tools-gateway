"""统一使用日志：记录所有接入方（API / MCP / CLI / Web）的调用，供控制台展示。

日志文件：<storage_dir>/usage.jsonl，每行一条 JSON。
写操作用 fcntl.flock 排他锁，保证多进程并发安全（不只是单进程线程锁）。
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
    # Windows 等不支持 fcntl 的平台，降级为仅线程锁（单进程内安全）
    fcntl = None
    _HAS_FCNTL = False


class UsageLogger(object):
    MAX_SCAN = 50000  # 单次查询最多扫描行数，防止超大日志文件撑爆内存

    def __init__(self, path):
        self.path = path
        self._lock = threading.Lock()
        os.makedirs(os.path.dirname(path), exist_ok=True)

    @contextlib.contextmanager
    def _file_lock(self, exclusive=False):
        """跨进程文件锁：写用排他锁，读用共享锁。
        不支持 fcntl 的平台（如 Windows）降级为无文件锁（仍有线程锁）。"""
        # 用 a+ 打开以确保文件存在，且不截断
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
        """写一条使用日志。

        transport: api / mcp / cli / web
        action: generate / configure / history / providers / upload / test / compare / heartbeat
        trusted: 接入方名是否可信（web/mcp/cli 服务端注入=True，外部 api 自报=False）
        fields 常用: provider, session_id, prompt, status(success/fail),
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
        """读取全部日志行，返回 (rows, scanned)。scanned 为实际扫描行数。"""
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
        """聚合每个接入方的统计与状态。active_window 秒内有调用视为在线。"""
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
