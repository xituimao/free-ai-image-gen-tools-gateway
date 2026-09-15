"""Provider 基类与统一数据结构。"""


class ImageRequest(object):
    """一次生图请求的归一化表示。"""

    def __init__(self, prompt, negative_prompt="", width=1024, height=1024,
                 n=1, model=None, seed=None, extra=None):
        self.prompt = prompt
        self.negative_prompt = negative_prompt or ""
        self.width = int(width)
        self.height = int(height)
        self.n = int(n) if n else 1
        self.model = model              # provider 内部子模型
        self.seed = seed
        self.extra = extra or {}

    def __repr__(self):
        return "ImageRequest(prompt=%r, size=%dx%d, n=%d, model=%r)" % (
            self.prompt, self.width, self.height, self.n, self.model)


class ProviderError(Exception):
    def __init__(self, message, status=502, detail=None):
        super().__init__(message)
        self.status = status
        self.detail = detail


class BaseProvider(object):
    """所有渠道适配器的基类。

    子类需实现 :meth:`available` 与 :meth:`generate`。
    ``generate`` 返回 list[bytes]，长度等于请求的 n（若渠道不支持多图，
    基类会自动循环补齐）。
    """

    # 渠道类型: free=完全免费无需key / key=需要凭证
    kind = "key"
    # 是否支持一次请求出多张
    supports_n = False

    def __init__(self, name, conf, timeout=120):
        self.name = name
        self.conf = conf or {}
        self.timeout = timeout

    def available(self):
        """该渠道当前是否可用（开关 + 凭证是否齐全）。"""
        raise NotImplementedError

    def list_models(self):
        """该渠道暴露的子模型列表，供 /v1/models 与控制台使用。"""
        m = self.conf.get("models")
        if m:
            return list(m)
        dm = self.conf.get("default_model")
        return [dm] if dm else []

    def _generate_once(self, client, req):
        """实际出一张/一批，返回 list[bytes]。子类实现。"""
        raise NotImplementedError

    async def generate(self, client, req):
        images = await self._generate_once(client, req)
        # 渠道不支持批量时用 while 补齐；固定 seed 时逐张偏移，避免出重复图
        if not self.supports_n:
            base_seed = req.seed
            i = 0
            while len(images) < req.n:
                i += 1
                if base_seed is not None:
                    req.seed = base_seed + i
                images.extend(await self._generate_once(client, req))
            req.seed = base_seed
        return images[:req.n] if len(images) >= req.n else images
