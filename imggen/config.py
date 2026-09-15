"""配置加载：YAML + 环境变量覆盖，支持热加载。"""
import os
import threading
import yaml

_CFG_LOCK = threading.RLock()
_CONFIG = None
_CONFIG_PATH = None


def find_config():
    """按优先级寻找配置文件。"""
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    candidates = [
        os.environ.get("IMGATEWAY_CONFIG"),
        os.path.join(os.getcwd(), "config.yaml"),
        os.path.join(here, "config.yaml"),
    ]
    for p in candidates:
        if p and os.path.isfile(p):
            return p
    # 没有 config.yaml 时退回 example，保证开箱可启动（免费通道可用）
    example = os.path.join(here, "config.example.yaml")
    return example if os.path.isfile(example) else None


def load_config(path=None):
    global _CONFIG, _CONFIG_PATH
    with _CFG_LOCK:
        path = path or find_config()
        if not path or not os.path.isfile(path):
            raise FileNotFoundError("找不到配置文件，请复制 config.example.yaml 为 config.yaml")
        with open(path, "r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f) or {}
        _CONFIG = cfg
        _CONFIG_PATH = path
        _apply_env(_CONFIG)
        return _CONFIG


def get_config(force_reload=False):
    with _CFG_LOCK:
        if _CONFIG is None or force_reload:
            load_config(_CONFIG_PATH)
        return _CONFIG


def _apply_env(cfg):
    """环境变量覆盖配置（server 项与各 provider key，不写进 yaml 也能用）。"""
    srv = cfg.setdefault("server", {})
    server_env = {
        "STORAGE_DIR": "storage_dir", "HOST": "host", "PORT": "port",
        "PUBLIC_BASE_URL": "public_base_url",
        "FORWARDED_ALLOW_IPS": "forwarded_allow_ips", "TIMEOUT": "timeout",
    }
    for env, key in server_env.items():
        val = os.environ.get(env)
        if val:
            srv[key] = int(val) if key in ("port", "timeout") else val

    prov = cfg.setdefault("providers", {})

    gem = prov.get("gemini") or {}
    if os.environ.get("GEMINI_API_KEY"):
        gem["api_key"] = os.environ["GEMINI_API_KEY"]
    prov["gemini"] = gem

    bl = prov.get("bailian") or {}
    if os.environ.get("DASHSCOPE_API_KEY"):
        bl["api_key"] = os.environ["DASHSCOPE_API_KEY"]
    prov["bailian"] = bl

    oc = prov.get("openai_compatible") or {}
    env_map = {
        "siliconflow": "SILICONFLOW_API_KEY",
        "openai": "OPENAI_API_KEY",
    }
    for name, env in env_map.items():
        item = oc.get(name) or {}
        if os.environ.get(env):
            item["api_key"] = os.environ[env]
        oc[name] = item
    # 其余渠道用 <NAME>_API_KEY 形式
    for name, item in oc.items():
        env = "%s_API_KEY" % name.upper()
        if os.environ.get(env):
            item["api_key"] = os.environ[env]
    prov["openai_compatible"] = oc

    bing = prov.get("bing") or {}
    if os.environ.get("BING_COOKIE_U"):
        bing["cookie_u"] = os.environ["BING_COOKIE_U"]
    prov["bing"] = bing
