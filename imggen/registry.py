"""Provider registry: instantiates all channels from config, responsible for name routing."""
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
        self.cooldown = {}      # provider -> cooldown expiry timestamp
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

        # OpenAI compatible channel expansion: one instance per sub-channel, directly use sub-channel name
        oc = prov.get("openai_compatible") or {}
        for sub_name, sub_conf in oc.items():
            self.providers[sub_name] = OpenAICompatProvider(
                sub_name, sub_conf, self.timeout)

    # ---------- Routing ----------

    def resolve(self, model_id):
        """Parse 'provider/sub-model' into (provider, sub_model).

        Provider name uses longest match because sub-model names may themselves contain slashes
        (e.g. black-forest-labs/FLUX.2-flex).
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
        raise ProviderError("Unknown provider/model: %s" % model_id, status=404)

    def default_chain(self):
        """Hardcoded priority skeleton from config (only keep names that actually exist)."""
        chain = (self.conf.get("server") or {}).get("default_chain") or []
        return [n for n in chain if n in self.providers]

    def _is_available(self, name):
        try:
            return self.providers[name].available()
        except Exception:
            return False

    def build_auto_chain(self):
        """Auto mode complete priority list, rules:

        1. Channels in default_chain are sorted first in config order (user's explicit priority);
        2. The remaining "currently available (credentials configured/free)" channels are auto-appended
           at the end, free ones first;
            -- thus newly configured channels will also be used by auto mode without manually adding to the list;
        3. Unavailable (not enabled/missing key) channels are removed directly, no meaningless attempts;
        4. Channels in failure cooldown period are moved to the end.
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
        # Free channels first, then by config appearance order
        rest.sort(key=lambda n: 0 if self.providers[n].kind == "free" else 1)
        for n in rest:
            push(n)

        # Failure cooldown: move cooling ones to end
        now = time.time()
        warm = [n for n in result if self.cooldown.get(n, 0) <= now]
        cooling = [n for n in result if self.cooldown.get(n, 0) > now]
        return warm + cooling

    def mark_failure(self, name, seconds=30):
        import time
        # Only record the provider part
        prov = name.split("/", 1)[0]
        self.cooldown[prov] = time.time() + seconds

    def mark_success(self, name):
        prov = name.split("/", 1)[0]
        self.cooldown.pop(prov, None)

    def cooling_info(self):
        """Channels in cooldown and remaining seconds, for console to display recovery progress."""
        now = time.time()
        out = []
        for name, until in self.cooldown.items():
            left = int(until - now)
            if left > 0:
                out.append({"provider": name, "left": left})
        return out

    def provider_status(self):
        """Channel management: status summary of each third-party channel (credentials only report whether set, not plaintext)."""
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
        # Available first, then free
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
        """For /v1/models: list all optional models per channel and their availability status."""
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
            raise ProviderError("No provider specified and unable to resolve: %r" % model_id)
        req.model = sub
        if not p.available():
            raise ProviderError("Channel %s currently unavailable (not enabled or missing credentials)" % p.name)
        return await p.generate(client, req)


def build_registry(conf=None, force_reload=False):
    conf = conf or get_config(force_reload=force_reload)
    return Registry(conf)
