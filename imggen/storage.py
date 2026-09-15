"""会话化存储。

统一资源根（server.storage_dir，本机/云均可配绝对路径），其下按会话分子目录：
  storage/sessions/<sid>/images/*.jpg|png|webp
  storage/sessions/<sid>/history.jsonl
  storage/sessions/<sid>/meta.json

- 每次生成（无论 b64/url）都把图片归档进当前会话并追加一条历史；
- 上传图片同样归入当前会话；
- 历史支持按提示词/渠道搜索与多种排序。
"""
import json
import os
import re
import time
import uuid

SAFE_SID = re.compile(r"^[A-Za-z0-9_\-]{1,64}$")
ALLOWED_EXT = {"jpg", "jpeg", "png", "webp"}
DEFAULT_SID = "default"


def sniff_ext(b):
    if b[:3] == b"\xff\xd8\xff":
        return "jpg"
    if b[:8] == b"\x89PNG\r\n\x1a\n":
        return "png"
    if b[:4] == b"RIFF" and b[8:12] == b"WEBP":
        return "webp"
    return "png"


class StorageError(Exception):
    pass


class Storage:
    def __init__(self, root):
        self.root = os.path.realpath(os.path.abspath(root))
        self.sdir = os.path.join(self.root, "sessions")
        os.makedirs(self.sdir, exist_ok=True)
        self._paths(DEFAULT_SID)

    # ---------- 内部工具 ----------

    def safe_sid(self, sid):
        sid = sid or DEFAULT_SID
        if not SAFE_SID.match(str(sid)):
            raise StorageError("非法 session_id（仅允许字母/数字/_/-，最长64）")
        return sid

    def _paths(self, sid):
        sid = self.safe_sid(sid)
        base = os.path.join(self.sdir, sid)
        img = os.path.join(base, "images")
        os.makedirs(img, exist_ok=True)
        hp = os.path.join(base, "history.jsonl")
        mp = os.path.join(base, "meta.json")
        if not os.path.isfile(hp):
            open(hp, "a").close()
        if not os.path.isfile(mp):
            self._write_json(mp, {"id": sid, "title": sid, "created": int(time.time())})
        return base, img, hp, mp

    @staticmethod
    def _write_json(path, obj):
        with open(path, "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False)

    @staticmethod
    def _read_json(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    @staticmethod
    def _append(hp, rec):
        with open(hp, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    # ---------- 会话管理 ----------

    def create_session(self, title=None, sid=None):
        sid = self.safe_sid(sid) if sid else uuid.uuid4().hex[:12]
        self._paths(sid)
        if title:
            _, _, _, mp = self._paths(sid)
            meta = self._read_json(mp)
            meta["title"] = title
            self._write_json(mp, meta)
        return self.session_meta(sid)

    def rename_session(self, sid, title):
        _, _, _, mp = self._paths(sid)
        meta = self._read_json(mp)
        meta["title"] = title
        self._write_json(mp, meta)
        return self.session_meta(sid)

    def session_meta(self, sid):
        _, _, _, mp = self._paths(sid)
        meta = self._read_json(mp)
        recs = self.read_history(sid)
        meta["records"] = len(recs)
        meta["images"] = sum(len(r.get("files", [])) for r in recs)
        meta["last_ts"] = recs[-1]["ts"] if recs else meta.get("created")
        return meta

    def list_sessions(self):
        out = []
        for n in os.listdir(self.sdir):
            if os.path.isdir(os.path.join(self.sdir, n)):
                try:
                    out.append(self.session_meta(n))
                except Exception:
                    pass
        out.sort(key=lambda m: m.get("last_ts", 0), reverse=True)
        return out

    # ---------- 归档 ----------

    def archive_generation(self, sid, images, meta):
        """images: list[bytes]；meta: prompt/negative/width/height/seed/provider/model。"""
        _, img, hp, _ = self._paths(sid)
        files, total = [], 0
        for b in images:
            ext = sniff_ext(b)
            fn = "gen_%s.%s" % (uuid.uuid4().hex[:10], ext)
            with open(os.path.join(img, fn), "wb") as f:
                f.write(b)
            files.append(fn)
            total += len(b)
        rec = {
            "id": uuid.uuid4().hex[:10], "ts": int(time.time()), "source": "generate",
            "prompt": meta.get("prompt"), "negative": meta.get("negative", ""),
            "width": meta.get("width"), "height": meta.get("height"),
            "n": len(files), "seed": meta.get("seed"),
            "provider": meta.get("provider"), "model": meta.get("model"),
            "files": files, "bytes": total,
        }
        self._append(hp, rec)
        return rec

    def archive_upload(self, sid, data, ext, caption=""):
        ext = ext.lower()
        if ext == "jpeg":
            ext = "jpg"
        if ext not in ALLOWED_EXT:
            raise StorageError("仅支持 jpg/png/webp")
        _, img, hp, _ = self._paths(sid)
        fn = "up_%s.%s" % (uuid.uuid4().hex[:10], ext)
        with open(os.path.join(img, fn), "wb") as f:
            f.write(data)
        rec = {
            "id": uuid.uuid4().hex[:10], "ts": int(time.time()), "source": "upload",
            "prompt": caption, "provider": "(本地上传)", "model": "upload",
            "width": None, "height": None, "n": 1, "seed": None,
            "files": [fn], "bytes": len(data),
        }
        self._append(hp, rec)
        return rec

    # ---------- 历史读取 / 搜索 / 排序 ----------

    def read_history(self, sid):
        _, _, hp, _ = self._paths(sid)
        out = []
        with open(hp, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    out.append(json.loads(line))
                except ValueError:
                    pass
        return out

    _SORTS = {
        "ts_desc": ("ts", True), "ts_asc": ("ts", False),
        "provider_asc": ("provider", False), "provider_desc": ("provider", True),
        "size_desc": ("width", True), "size_asc": ("width", False),
        "n_desc": ("n", True), "n_asc": ("n", False),
    }

    def query_history(self, sid, search="", sort="ts_desc", limit=None):
        recs = self.read_history(sid)
        if search:
            s = search.lower()
            recs = [r for r in recs
                    if s in (r.get("prompt") or "").lower()
                    or s in (r.get("provider") or "").lower()]
        k, rev = self._SORTS.get(sort, ("ts", True))

        def gk(r):
            v = r.get(k)
            return v if v is not None else ("" if k == "provider" else 0)

        out = sorted(recs, key=gk, reverse=rev)
        if limit and limit > 0:
            out = out[:limit]
        return out

    # ---------- 图片访问 ----------

    def image_path(self, sid, name):
        _, img, _, _ = self._paths(sid)
        root = os.path.realpath(img)
        safe = os.path.realpath(os.path.join(img, os.path.basename(name)))
        if not (safe == root or safe.startswith(root + os.sep)):
            return None
        return safe if os.path.isfile(safe) else None
