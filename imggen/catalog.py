"""渠道目录：每个第三方生图服务的元数据（中文名、计费类型、凭证字段、官网）。

供「渠道管理」页做状态汇总与在线配置，也供历史记录标注"哪家渠道出的图"。
"""

# type: free 免费 / quota 免费额度 / cheap 低价 / paid 付费 / relay 中转
CATALOG = {
    "pollinations": {
        "label": "Pollinations", "type": "free",
        "cred": [], "url": "https://pollinations.ai",
        "desc": "HTTP 直出、无需 key，默认保底通道"},
    "gemini": {
        "label": "Google Gemini", "type": "quota",
        "cred": [{"f": "api_key", "label": "AI Studio API Key"}],
        "url": "https://aistudio.google.com/apikey",
        "desc": "Nano Banana，文字渲染强"},
    "siliconflow": {
        "label": "硅基流动", "type": "cheap",
        "cred": [{"f": "api_key", "label": "SiliconFlow Key"}],
        "url": "https://siliconflow.cn",
        "desc": "FLUX.2 flex / Z-Image，约 ¥0.035 起"},
    "openai": {
        "label": "OpenAI", "type": "paid",
        "cred": [{"f": "api_key", "label": "OpenAI Key"}],
        "url": "https://platform.openai.com",
        "desc": "gpt-image-1"},
    "relay": {
        "label": "自定义中转", "type": "relay",
        "cred": [{"f": "api_key", "label": "中转 Key（可选）"}],
        "url": "",
        "desc": "任意 OpenAI 兼容第三方"},
    "bailian": {
        "label": "阿里百炼", "type": "cheap",
        "cred": [{"f": "api_key", "label": "DashScope Key"}],
        "url": "https://bailian.console.aliyun.com",
        "desc": "通义万相 / Z-Image，新用户送额度"},
    "hf_space": {
        "label": "HuggingFace Space", "type": "free",
        "cred": [{"f": "hf_token", "label": "HF Token", "optional": True}],
        "url": "https://huggingface.co/spaces",
        "desc": "云端跑 FLUX/SD 开源模型，token 可选"},
    "perchance": {
        "label": "Perchance", "type": "free",
        "cred": [], "url": "https://perchance.org",
        "desc": "免费逆向通道，尽力而为"},
    "bing": {
        "label": "Bing Image Creator", "type": "free",
        "cred": [{"f": "cookie_u", "label": "Cookie _U"}],
        "url": "https://www.bing.com/images/create",
        "desc": "DALL-E 3，需登录后的 _U"},
}

TYPE_LABEL = {
    "free": "免费", "quota": "免费额度", "cheap": "低价",
    "paid": "付费", "relay": "中转",
}


def get_meta(name):
    return CATALOG.get(name, {"label": name, "type": "other",
                              "cred": [], "url": "", "desc": ""})
