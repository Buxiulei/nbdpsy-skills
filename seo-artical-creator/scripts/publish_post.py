#!/usr/bin/env python3
"""使用 external API 发布博客文章。
支持发布/更新/草稿/幂等（409 slug conflict 跳过）。

用法：
    python3 publish_post.py [--file X.md | --drafts-dir DIR] [--draft] [--update]
        [--author 胡佰亿] [--api-base URL] [--dry-run]

无参数时默认 --drafts-dir {workspace}/drafts。
输出：stdout JSON {"published": [...], "skipped": [...], "failed": [...]}
"""
import argparse
import json
import os
import re
import sys
from pathlib import Path

# 同目录 vendored 副本
import nbdpsy_common

def parse_frontmatter(text: str):
    """解析 YAML frontmatter。"""
    m = re.match(r"^---\n(.*?)\n---\n(.*)$", text, re.S)
    if not m:
        raise ValueError("缺 frontmatter")
    try:
        import yaml  # type: ignore
        meta = yaml.safe_load(m.group(1))
    except ModuleNotFoundError:
        sys.exit("需要 python3-yaml（pyyaml）")
    return meta or {}, m.group(2)


def strip_leading_h1(body: str) -> str:
    """剥掉首行 H1，避免重复渲染。"""
    lines = body.lstrip("\n").split("\n")
    if lines and lines[0].startswith("# "):
        lines = lines[1:]
    return "\n".join(lines).lstrip("\n")


def build_payload(md_text: str, fallback_slug: str, author: str, draft: bool) -> dict:
    """从 markdown 构建 API payload。

    Args:
        md_text: frontmatter + 正文
        fallback_slug: 如果 frontmatter 缺 slug，用这个
        author: 默认署名（frontmatter author_name 优先）
        draft: status = "draft" 还是 "published"

    Returns:
        dict，只包含非空键
    """
    meta, body = parse_frontmatter(md_text)

    payload = {}

    # 必须字段
    if "title" in meta:
        payload["title"] = meta["title"]

    payload["slug"] = meta.get("slug", fallback_slug)

    if "excerpt" in meta:
        payload["excerpt"] = meta["excerpt"]

    # 正文剥 H1
    content_md = strip_leading_h1(body)
    if content_md:
        payload["content_markdown"] = content_md

    if "category_slug" in meta:
        payload["category_slug"] = meta["category_slug"]

    # tags → tag_names
    if "tags" in meta:
        tags = meta["tags"]
        if isinstance(tags, list):
            payload["tag_names"] = tags

    # 署名：frontmatter author_name > --author > 胡佰亿
    author_name = meta.get("author_name") or author or "胡佰亿"
    payload["author_name"] = author_name.strip()

    # status
    payload["status"] = "draft" if draft else "published"

    # 可选字段（有则加）
    if "cover_image_url" in meta:
        payload["cover_image_url"] = meta["cover_image_url"]

    if "video_url" in meta:
        payload["video_url"] = meta["video_url"]

    if "citations" in meta:
        payload["citations"] = meta["citations"]

    if "faq" in meta:
        faq_list = meta["faq"]
        if isinstance(faq_list, list):
            payload["faq"] = [{"q": x.get("q"), "a": x.get("a")} for x in faq_list if x.get("q") and x.get("a")]

    return payload


def post_request(url: str, key: str, payload: dict):
    """POST 请求到 external API。

    Returns:
        requests.Response
    """
    import requests
    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json; charset=utf-8"
    }
    return requests.post(url, json=payload, headers=headers)


def put_request(url: str, key: str, payload: dict):
    """PUT 请求到 external API。

    Returns:
        requests.Response
    """
    import requests
    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json; charset=utf-8"
    }
    return requests.put(url, json=payload, headers=headers)


def publish_one(path: Path, *, api_base: str, key: str, author: str, draft: bool, update: bool, dry_run: bool) -> dict:
    """发布单个文件。

    Returns:
        {"outcome": "published|skipped|failed", "slug": str, "id": str/None, "error": str/None}
    """
    try:
        md_text = path.read_text(encoding="utf-8")
        fallback_slug = path.stem
        payload = build_payload(md_text, fallback_slug, author, draft)
        slug = payload["slug"]

        if dry_run:
            print(f"[DRY-RUN] {path.name} → {slug}", file=sys.stderr)
            print(json.dumps(payload, ensure_ascii=False, indent=2), file=sys.stderr)
            return {"outcome": "published", "slug": slug, "id": None}

        if update:
            url = f"{api_base}/api/external/blog/posts/{slug}"
            print(f"更新 {slug}...", file=sys.stderr)
            resp = put_request(url, key, payload)
        else:
            url = f"{api_base}/api/external/blog/posts"
            print(f"发布 {slug}...", file=sys.stderr)
            resp = post_request(url, key, payload)

        if resp.status_code == 409:
            # slug conflict → 幂等跳过
            print(f"  → 跳过（slug 已存在）", file=sys.stderr)
            return {"outcome": "skipped", "slug": slug}

        if resp.status_code >= 400:
            try:
                err_data = resp.json()
                error = err_data.get("error", resp.text[:200])
            except:
                error = resp.text[:200]
            print(f"  → 失败: {error}", file=sys.stderr)
            return {"outcome": "failed", "slug": slug, "error": error}

        try:
            data = resp.json()
            if data.get("success"):
                post_id = data.get("data", {}).get("id")
                print(f"  → 成功 id={post_id}", file=sys.stderr)
                return {"outcome": "published", "slug": slug, "id": post_id}
            else:
                error = data.get("error", "unknown error")
                print(f"  → 失败: {error}", file=sys.stderr)
                return {"outcome": "failed", "slug": slug, "error": error}
        except Exception as e:
            print(f"  → 解析失败: {e}", file=sys.stderr)
            return {"outcome": "failed", "slug": slug, "error": str(e)}

    except Exception as e:
        slug = path.stem
        print(f"  → 异常: {e}", file=sys.stderr)
        return {"outcome": "failed", "slug": slug, "error": str(e)}


def main():
    ap = argparse.ArgumentParser(description="使用 external API 发布博客文章")
    ap.add_argument("--file", type=Path, help="单个 markdown 文件")
    ap.add_argument("--drafts-dir", type=Path, help="drafts 目录（默认 workspace/drafts）")
    ap.add_argument("--draft", action="store_true", help="以草稿发布")
    ap.add_argument("--update", action="store_true", help="用 PUT 更新而非 POST 创建")
    ap.add_argument("--author", default="胡佰亿", help="默认署名")
    ap.add_argument("--api-base", default=None, help="API base URL（默认从 NBDPSY_API_BASE 或 https://database.nbdpsy.com）")
    ap.add_argument("--dry-run", action="store_true", help="只打 payload，不发请求")

    args = ap.parse_args()

    # 获取 API Key
    key = nbdpsy_common.get_secret("NBDPSY_BLOG_API_KEY")
    if not key:
        print("MISSING:NBDPSY_BLOG_API_KEY 请先运行 setup 凭据向导或 nbdpsy_common.py secret set", file=sys.stderr)
        sys.exit(1)

    # API Base
    api_base = args.api_base or os.environ.get("NBDPSY_API_BASE", "https://database.nbdpsy.com")

    # 确定要发布的文件
    if args.file:
        files = [args.file]
    elif args.drafts_dir:
        files = sorted(args.drafts_dir.glob("*.md"))
    else:
        workspace = nbdpsy_common.resolve_workspace()
        drafts_dir = workspace / "drafts"
        files = sorted(drafts_dir.glob("*.md")) if drafts_dir.is_dir() else []

    if not files:
        print("未找到要发布的文件", file=sys.stderr)
        sys.exit(1)

    # 发布每个文件
    published = []
    skipped = []
    failed = []

    for fpath in files:
        result = publish_one(fpath, api_base=api_base, key=key, author=args.author,
                            draft=args.draft, update=args.update, dry_run=args.dry_run)
        outcome = result["outcome"]

        if outcome == "published":
            published.append({"slug": result["slug"], "id": result.get("id"), "status": "draft" if args.draft else "published"})
        elif outcome == "skipped":
            skipped.append(result["slug"])
        elif outcome == "failed":
            failed.append({"slug": result["slug"], "error": result.get("error")})

    # 输出 JSON
    output = {
        "published": published,
        "skipped": skipped,
        "failed": failed
    }
    print(json.dumps(output, ensure_ascii=False))

    # 非 dry-run 且有失败时 exit 1
    if failed and not args.dry_run:
        sys.exit(1)


if __name__ == "__main__":
    main()
