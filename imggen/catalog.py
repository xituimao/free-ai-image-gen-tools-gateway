"""Channel catalog: metadata for each third-party image generation service (name, billing type, credential fields, official website).

Used by the "Channel Management" page for status summary and online configuration, and by history records to label "which channel produced the image".
"""

# type: free / quota free quota / cheap low price / paid / relay relay
CATALOG = {
    "pollinations": {
        "label": "Pollinations", "type": "free",
        "cred": [], "url": "https://pollinations.ai",
        "desc": "Direct HTTP output, no key needed, default fallback channel"},
    "gemini": {
        "label": "Google Gemini", "type": "quota",
        "cred": [{"f": "api_key", "label": "AI Studio API Key"}],
        "url": "https://aistudio.google.com/apikey",
        "desc": "Nano Banana, strong text rendering"},
    "siliconflow": {
        "label": "SiliconFlow", "type": "cheap",
        "cred": [{"f": "api_key", "label": "SiliconFlow Key"}],
        "url": "https://siliconflow.cn",
        "desc": "FLUX.2 flex / Z-Image, from ~¥0.035"},
    "openai": {
        "label": "OpenAI", "type": "paid",
        "cred": [{"f": "api_key", "label": "OpenAI Key"}],
        "url": "https://platform.openai.com",
        "desc": "gpt-image-1"},
    "relay": {
        "label": "Custom Relay", "type": "relay",
        "cred": [{"f": "api_key", "label": "Relay Key (optional)"}],
        "url": "",
        "desc": "Any OpenAI-compatible third party"},
    "bailian": {
        "label": "DashScope", "type": "cheap",
        "cred": [{"f": "api_key", "label": "DashScope Key"}],
        "url": "https://bailian.console.aliyun.com",
        "desc": "Tongyi Wanxiang / Z-Image, new users get free quota"},
    "hf_space": {
        "label": "HuggingFace Space", "type": "free",
        "cred": [{"f": "hf_token", "label": "HF Token", "optional": True}],
        "url": "https://huggingface.co/spaces",
        "desc": "Run FLUX/SD open-source models on cloud, token optional"},
    "perchance": {
        "label": "Perchance", "type": "free",
        "cred": [], "url": "https://perchance.org",
        "desc": "Free reverse-proxy channel, best effort"},
    "bing": {
        "label": "Bing Image Creator", "type": "free",
        "cred": [{"f": "cookie_u", "label": "Cookie _U"}],
        "url": "https://www.bing.com/images/create",
        "desc": "DALL-E 3, requires logged-in _U"},
}

TYPE_LABEL = {
    "free": "Free", "quota": "Free Quota", "cheap": "Low Price",
    "paid": "Paid", "relay": "Relay",
}


def get_meta(name):
    return CATALOG.get(name, {"label": name, "type": "other",
                              "cred": [], "url": "", "desc": ""})
