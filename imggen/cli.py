"""命令行入口。

示例:
  python -m imggen.cli models                     # 查看全部渠道及可用状态
  python -m imggen.cli "一只穿西装的柯基"          # 走默认链
  python -m imggen.cli "赛博朋克城市" -p gemini    # 指定渠道
  python -m imggen.cli "猫" -p pollinations,gemini # 按顺序 fallback
  python -m imggen.cli "猫" -o cat.png --size 768x512
  python -m imggen.cli serve                      # 启动网关服务(API+网页)
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

    # C1: 默认走完整自动链（剔除不可用、自动补免费通道、冷却沉底），与服务端一致
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
                print("没有任何已启用且可用的通道，请在 config.yaml 启用/填写凭证")
            else:
                print("全部通道失败:")
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

    # 统一归档到会话目录（与服务端一致）；-o 时额外复制到指定路径
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
    print("成功渠道: %s | 会话: %s" % (target, sid))
    if tried:
        print("之前试过并跳过: %s" % ", ".join(tried))
    for p in paths:
        print("已保存:", p)
    return 0


def main():
    parser = argparse.ArgumentParser(prog="imggen", description="统一生图 CLI")
    sub = parser.add_subparsers(dest="cmd")

    g = sub.add_parser("gen", help="生成图片（默认命令，可省略 gen）")
    g.add_argument("prompt")
    g.add_argument("-p", "--provider", help="渠道，多个用逗号分隔做 fallback")
    g.add_argument("-o", "--output", help="额外复制到该文件路径")
    g.add_argument("-s", "--session", default="default", help="归档到哪个会话，默认 default")
    g.add_argument("--size", default="1024x1024")
    g.add_argument("-n", type=int, default=1)
    g.add_argument("--seed", type=int, default=None)
    g.add_argument("--negative", default="")

    sub.add_parser("models", help="列出渠道")
    sub.add_parser("serve", help="启动 API + 网页网关")

    # 支持省略 gen：imggen "prompt" ...
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
