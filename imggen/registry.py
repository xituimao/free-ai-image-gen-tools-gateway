"""Provider 注册表：按配置实例化全部渠道，负责名称路由。"""
import time

from .catalog import get_meta, TYPE_LABEL
from .config import get_config
from .providers.base import ImageRequest, ProviderError
from .providers.pollinations import PollinationsProvider
from .providers.gemini import GeminiProvider
from .providers.bailian import BailianProvider
from .providers.hf_space import HFSpaceProvider
from .providers.perchance import PerchanceProvider
from .providers.bing import BingProvider
from .providers.openai_compat import OpenAICompatProvider


class Registry(object):
    def __init__(self, conf):
        self.conf = conf
        self.timeout = (conf.get("server") or {}).get("timeout", 120)
        self.providers = {}
        self.cooldown = {}      # provider -> 冷却截止时间戳
        self._build()

    def _build(self):
        prov = self.conf.get("providers") or {}

        def put(name, cls, sub_conf):
            self.providers[name] = cls(name, sub_conf, self.timeout)

        if "pollinations" in prov:
            put("pollinations", PollinationsProvider, prov["pollinations"])
        if "gemini" in prov:
            put("gemini", GeminiProvider, prov["gemini"])
        if "bailian" in prov:
            put("bailian", BailianProvider, prov["bailian"])
        if "hf_space" in prov:
            put("hf_space", HFSpaceProvider, prov["hf_space"])
        if "perchance" in prov:
            put("perchance", PerchanceProvider, prov["perchance"])
        if "bing" in prov:
            put("bing", BingProvider, prov["bing"])

        # OpenAI 兼容渠道展开：每个子渠道一个实例，直接用子渠道名
        oc = prov.get("openai_compatible") or {}
        for sub_name, sub_conf in oc.items():
            self.providers[sub_name] = OpenAICompatProvider(
                sub_name, sub_conf, self.timeout)

    # ---------- 路由 ----------

    def resolve(self, model_id):
        """把 'provider/sub-model' 解析为 (provider, sub_model)。

        provider 名做最长匹配，因为子模型名本身可能含斜杠
        （如 black-forest-labs/FLUX.2-flex）。
        """
        if not model_id:
            return None, None
        if model_id in self.providers:
            return self.providers[model_id], None
        best = None
        for name in self.providers:
            if model_id.startswith(name + "/"):
                if best is None or len(name) > len(best):
                    best = name
        if best:
            return self.providers[best], model_id[len(best) + 1:]
        raise ProviderError("未知 provider/model: %s" % model_id, status=404)

    def default_chain(self):
        """配置里写死的优先骨架（只保留实际存在的名字）。"""
        chain = (self.conf.get("server") or {}).get("default_chain") or []
        return [n for n in chain if n in self.providers]

    def _is_available(self, name):
        try:
            return self.providers[name].available()
        except Exception:
            return False

    def build_auto_chain(self):
        """自动模式的完整优先列表，规则：

        1. default_chain 里的通道按配置顺序排前面（用户的显式优先级）；
        2. 其余“当前可用(已配置凭证/免费)”的通道自动补到后面，免费的优先，
           —— 因此新配的渠道不用手动加列表也会被自动模式用到；
        3. 不可用（没启用/缺 key）的通道直接剔除，不做无意义尝试；
        4. 处于失败冷却期的通道排到最后。
        """
        import time
        skeleton = self.default_chain()
        result, in_list = [], set()

        def push(name):
            if name in in_list:
                return
            if not self._is_available(name):
                return
            in_list.add(name)
            result.append(name)

        for n in skeleton:
            push(n)

        rest = [n for n in self.providers if n not in in_list]
        # 免费通道优先，其次按配置出现顺序
        rest.sort(key=lambda n: 0 if self.providers[n].kind == "free" else 1)
        for n in rest:
            push(n)

        # 失败冷却：冷却中的移到末尾
        now = time.time()
        warm = [n for n in result if self.cooldown.get(n, 0) <= now]
        cooling = [n for n in result if self.cooldown.get(n, 0) > now]
        return warm + cooling

    def mark_failure(self, name, seconds=30):
        import time
        # 只记录 provider 部分
        prov = name.split("/", 1)[0]
        self.cooldown[prov] = time.time() + seconds

    def mark_success(self, name):
        prov = name.split("/", 1)[0]
        self.cooldown.pop(prov, None)

    def cooling_info(self):
        """冷却中的通道及剩余秒，供控制台显示恢复进度。"""
        now = time.time()
        out = []
        for name, until in self.cooldown.items():
            left = int(until - now)
            if left > 0:
                out.append({"provider": name, "left": left})
        return out

    def provider_status(self):
        """渠道管理用：每个第三方渠道的状态汇总（凭证只回是否已设置，不回明文）。"""
        now = time.time()
        auto = self.build_auto_chain()
        out = []
        for name, p in self.providers.items():
            meta = get_meta(name)
            conf = getattr(p, "conf", {}) or {}
            try:
                avail = bool(p.available())
            except Exception:
                avail = False
            until = self.cooldown.get(name, 0)
            left = int(until - now) if until > now else 0
            creds = []
            for c in meta.get("cred", []):
                f = c["f"]
                creds.append({"field": f, "label": c.get("label", f),
                              "optional": c.get("optional", False),
                              "set": bool(conf.get(f))})
            out.append({
                "name": name, "label": meta.get("label", name),
                "desc": meta.get("desc", ""), "url": meta.get("url", ""),
                "type": meta.get("type", "other"),
                "type_label": TYPE_LABEL.get(meta.get("type"), ""),
                "enabled": conf.get("enabled", True),
                "available": avail, "cooldown_left": left,
                "default_model": conf.get("default_model"),
                "models": p.list_models(), "creds": creds,
                "in_chain": name in auto,
            })
        # 可用优先，其次免费
        out.sort(key=lambda x: (not x["available"], x["type"] != "free"))
        return out

    def provider_summary(self):
        rows = self.provider_status()
        return {
            "total": len(rows),
            "available": sum(1 for r in rows if r["available"]),
            "unconfigured": sum(1 for r in rows if not r["available"]),
            "cooling": sum(1 for r in rows if r["cooldown_left"] > 0),
        }

    def list_models(self):
        """供 /v1/models：列出每个渠道的全部可选模型及可用状态。"""
        out = []
        for name, p in self.providers.items():
            avail = False
            try:
                avail = p.available()
            except Exception:
                avail = False
            subs = p.list_models()
            if subs:
                for sm in subs:
                    mid = name + "/" + sm if sm else name
                    out.append({"id": mid, "provider": name, "sub_model": sm,
                                "available": avail, "kind": p.kind})
            else:
                out.append({"id": name, "provider": name, "sub_model": None,
                            "available": avail, "kind": p.kind})
        return out

    async def dispatch(self, client, model_id, req):
        p, sub = self.resolve(model_id)
        if p is None:
            raise ProviderError("未指定 provider 且无法解析: %r" % model_id)
        req.model = sub
        if not p.available():
            raise ProviderError("渠道 %s 当前不可用（未启用或缺少凭证）" % p.name)
        return await p.generate(client, req)


def build_registry(conf=None, force_reload=False):
    conf = conf or get_config(force_reload=force_reload)
    return Registry(conf)
