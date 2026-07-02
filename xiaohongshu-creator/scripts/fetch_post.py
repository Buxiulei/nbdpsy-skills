#!/usr/bin/env python3
"""拉取长文博客文章并生成 Markdown 文件。

使用 nbdpsy 公开 API 获取文章，生成带 YAML frontmatter 的 Markdown 文件。
支持缓存：本地已存在同名文件时不打网络。
"""
import json
import sys
import argparse
import requests
import yaml
from pathlib import Path

# 导入 nbdpsy_common（同目录）
try:
    from nbdpsy_common import resolve_workspace
except ImportError:
    def resolve_workspace():
        return Path.home() / "nbdpsy-content"


DEFAULT_API_BASE = "https://database.nbdpsy.com"
REQUEST_TIMEOUT = 15


def fetch_json(url):
    """从 URL 获取 JSON 数据。"""
    response = requests.get(url, timeout=REQUEST_TIMEOUT)
    response.raise_for_status()
    return response.json()


def fetch_one(slug: str, *, out_dir: Path = None, api_base: str = DEFAULT_API_BASE) -> dict:
    """拉取单篇文章。

    Args:
        slug: 文章 slug
        out_dir: 输出目录（默认为 workspace/drafts）
        api_base: API 基础 URL

    Returns:
        {"path": "...", "slug": "...", "title": "...", "cached": bool}
    """
    if out_dir is None:
        out_dir = resolve_workspace() / "drafts"

    out_dir = Path(out_dir)
    out_file = out_dir / f"{slug}.md"

    # 检查缓存
    if out_file.exists():
        content = out_file.read_text(encoding="utf-8")
        # 尝试解析 frontmatter（若格式正确）
        title = ""
        if content.startswith("---"):
            try:
                parts = content.split("---")
                if len(parts) >= 3:
                    data = yaml.safe_load(parts[1])
                    title = data.get("title", "")
            except Exception:
                pass
        return {
            "path": str(out_file),
            "slug": slug,
            "title": title,
            "cached": True
        }

    # 从 API 获取文章
    url = f"{api_base}/api/public/blog/posts/{slug}"
    resp = fetch_json(url)
    data = resp["data"]

    # 构建 frontmatter
    frontmatter = {
        "title": data["title"],
        "slug": data["slug"],
        "excerpt": data["excerpt"],
        "category_slug": data["category"]["slug"],
        "author_name": data["author_name"],
        "published_at": data["published_at"],
        "citations": data.get("citations", []),
        "faq": data.get("faq", []),
    }

    # 生成 Markdown 文件
    out_dir.mkdir(parents=True, exist_ok=True)
    fm_text = yaml.safe_dump(frontmatter, allow_unicode=True, default_flow_style=False)
    content = f"---\n{fm_text}---\n\n{data['content_markdown']}"

    out_file.write_text(content, encoding="utf-8")

    return {
        "path": str(out_file),
        "slug": slug,
        "title": data["title"],
        "cached": False
    }


def list_posts(n: int = 10, api_base: str = DEFAULT_API_BASE) -> list:
    """列出最新文章。

    Args:
        n: 返回数量（默认 10）
        api_base: API 基础 URL

    Returns:
        [{"slug": "...", "title": "...", "published_at": "..."}]
    """
    url = f"{api_base}/api/public/blog/posts?limit={n}"
    resp = fetch_json(url)
    # API 返回 {"data": {"page": ..., "page_size": ..., "posts": [...]}}
    posts = resp["data"].get("posts", [])

    return [
        {
            "slug": p["slug"],
            "title": p["title"],
            "published_at": p["published_at"]
        }
        for p in posts
    ]


def main():
    parser = argparse.ArgumentParser(
        description="拉取 NBDpsy 博客文章"
    )
    parser.add_argument(
        "--slug",
        type=str,
        help="文章 slug（拉取单篇）"
    )
    parser.add_argument(
        "--out",
        type=Path,
        help="输出目录（默认 workspace/drafts）"
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="列出最新文章"
    )
    parser.add_argument(
        "--api",
        type=str,
        default=DEFAULT_API_BASE,
        help=f"API 基础 URL（默认 {DEFAULT_API_BASE}）"
    )
    parser.add_argument(
        "n",
        type=int,
        nargs="?",
        default=10,
        help="列出数量（默认 10）"
    )

    args = parser.parse_args()

    try:
        if args.slug:
            result = fetch_one(args.slug, out_dir=args.out, api_base=args.api)
            print(json.dumps(result, ensure_ascii=False))
            return 0
        elif args.list:
            result = list_posts(args.n, api_base=args.api)
            print(json.dumps(result, ensure_ascii=False))
            return 0
        else:
            parser.print_help()
            return 1
    except Exception as e:
        print(f"错误: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
