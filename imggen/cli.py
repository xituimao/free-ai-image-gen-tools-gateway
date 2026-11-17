"""Command line entry.

Example:
  python -m imggen.cli models                     # View all channels and their availability
  python -m imggen.cli "a corgi wearing a suit"          # Use default chain
  python -m imggen.cli "cyberpunk city" -p gemini    # Specify channel
  python -m imggen.cli "cat" -p pollinations,gemini # Fallback in order
  python -m imggen.cli "cat" -o cat.png --size 768x512
  python -m imggen.cli serve                      # Start gateway service (API+web)
"""
import argparse
import asyncio
import os
import sys
import time

import httpx

from .config import get_config
from .registry import build_registry
from .providers.base import ImageRequest, ProviderError


def sniff_ext(b):
    if b[:3] == b"\xff\xd8\xff":
        return "jpg"
    if b[:8] == b"\x89PNG\r\n\x1a\n":
        return "png"
    if b[:4] == b"RIFF" and b[8:12] == b"WEBP":
        return "webp"
    return "png"


def cmd_models(reg):
    rows = reg.list_models()
    print("%-38s %-12s %-8s %s" % ("model id", "provider", "kind", "available"))
    print("-" * 78)
    for m in rows:
        print("%-38s %-12s %-8s %s" % (
            m["id"], m["provider"], m["kind"],
            "YES" if m["available"] else "-"))


async def run_gen(args):
    t0 = time.time()
    cfg = get_config()
    timeout = (cfg.get("server") or {}).get("timeout", 120)
    reg = build_registry(cfg)
    _root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    _srv = cfg.get("server") or {}
    storage_dir = _srv.get("storage_dir") or os.path.join(_root, "storage")
    if not os.path.isabs(storage_dir):
        storage_dir = os.path.join(_root, storage_dir)
    from .usage import UsageLogger
    ulog = UsageLogger(os.path.join(storage_dir, "usage.jsonl"))
    try:
        w, h = (int(x) for x in args.size.lower().replace("*", "x").split("x"))
    except Exception:
        w, h = 1024, 1024

    # C1: Default full auto chain (excluding unavailable, automatically adding free channels, cooling sink), consistent with service
    chain = args.provider.split(",") if args.provider else reg.build_auto_chain()
    req = ImageRequest(prompt=args.prompt, negative_prompt=args.negative,
                       width=w, height=h, n=args.n, seed=args.seed)
    async with httpx.AsyncClient(timeout=timeout) as client:
        errors, tried = [], []
        for target in chain:
            try:
                images = await reg.dispatch(client, target, req)
                break
            except Exception as e:
                tried.append(target)
                errors.append("%s -> %s" % (target, e))
        else:
            if not chain:
                print("No available enabled channel, please enable/fill credentials in config.yaml")
            else:
                print("All channels failed:")
                for e in errors:
                    print("  ", e)
            try:
                ulog.log("cli", "cli", "generate", trusted=True, status="fail",
                         session_id=args.session or "default",
                         duration_ms=int((time.time() - t0) * 1000),
                         prompt=args.prompt[:200],
                         error="no channel" if not chain else "all failed")
            except Exception:
                pass
            return 1

    # Uniformly archive to session directory (consistent with server); -o additionally copies to specified path
    from .storage import Storage
    storage = Storage(storage_dir)
    sid = args.session or "default"
    rec = storage.archive_generation(sid, images, {
        "prompt": args.prompt, "negative": args.negative or "",
        "width": w, "height": h, "seed": args.seed,
        "provider": target.split("/", 1)[0], "model": target})
    try:
        ulog.log("cli", "cli", "generate", trusted=True,
                 provider=target.split("/", 1)[0], session_id=sid,
                 status="success", duration_ms=int((time.time() - t0) * 1000),
                 n=len(images), prompt=args.prompt[:200])
    except Exception:
        pass

    img_dir = os.path.join(storage.sdir, sid, "images")
    paths = []
    for i, b in enumerate(images):
        if args.output and len(images) == 1:
            with open(args.output, "wb") as f:
                f.write(b)
            paths.append(args.output)
        else:
            paths.append(os.path.join(img_dir, rec["files"][i]))
    print("Successfully archived: %s | session: %s" % (target, sid))
    if tried:
        print("Previously tried and skipped: %s" % ", ".join(tried))
    for p in paths:
        print("Saved:", p)
    return 0


def main():
    parser = argparse.ArgumentParser(prog="imggen", description="Unified Image Generation CLI")
    sub = parser.add_subparsers(dest="cmd")

    g = sub.add_parser("gen", help="Generate image (default command, can omit gen)")
    g.add_argument("prompt")
    g.add_argument("-p", "--provider", help="Channel, multiple separated by commas for fallback")
    g.add_argument("-o", "--output", help="Additionally copy to this file path")
    g.add_argument("-s", "--session", default="default", help="Archive to which session, default default")
    g.add_argument("--size", default="1024x1024")
    g.add_argument("-n", type=int, default=1)
    g.add_argument("--seed", type=int, default=None)
    g.add_argument("--negative", default="")

    sub.add_parser("models", help="List channels")
    sub.add_parser("serve", help="Start API + web gateway")

    # Support omitting gen: imggen "prompt" ...
    if len(sys.argv) > 1 and sys.argv[1] not in ("gen", "models", "serve"):
        sys.argv.insert(1, "gen")

    args = parser.parse_args()
    if args.cmd == "serve":
        from .server import main as srv_main
        srv_main()
    elif args.cmd == "models":
        reg = build_registry()
        cmd_models(reg)
    elif args.cmd == "gen":
        sys.exit(asyncio.run(run_gen(args)))
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
