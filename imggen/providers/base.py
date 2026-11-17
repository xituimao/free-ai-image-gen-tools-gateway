"""Provider base class and unified data structures."""


class ImageRequest(object):
    """Normalized representation of a single image generation request."""

    def __init__(self, prompt, negative_prompt="", width=1024, height=1024,
                 n=1, model=None, seed=None, extra=None):
        self.prompt = prompt
        self.negative_prompt = negative_prompt or ""
        self.width = int(width)
        self.height = int(height)
        self.n = int(n) if n else 1
        self.model = model              # provider internal sub-model
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
    """Base class for all channel adapters.

    Subclasses must implement :meth:`available` and :meth:`generate`.
    ``generate`` returns list[bytes], length equals requested n (if channel doesn't support multiple images,
    base class will automatically loop and pad).
    """

    # Channel type: free=completely free no key needed / key=credentials required
    kind = "key"
    # Whether multiple images supported per request
    supports_n = False

    def __init__(self, name, conf, timeout=120):
        self.name = name
        self.conf = conf or {}
        self.timeout = timeout

    def available(self):
        """Whether this channel is currently available (switch + credentials complete)."""
        raise NotImplementedError

    def list_models(self):
        """List of sub-models exposed by this channel, used by /v1/models and the console."""
        m = self.conf.get("models")
        if m:
            return list(m)
        dm = self.conf.get("default_model")
        return [dm] if dm else []

    def _generate_once(self, client, req):
        """Generate one image or one batch, return list[bytes]. Subclasses implement.""""""
        raise NotImplementedError

    async def generate(self, client, req):
        images = await self._generate_once(client, req)
        # When channel doesn't support batching, use while loop to pad; with fixed seed,
        # offset per image to avoid duplicates.
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
