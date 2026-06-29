#!/usr/bin/env python3
"""把 pillar drafts 目录下的 *.md 幂等插入 blog_posts 并**直接发布**（默认署名胡佰亿）。

工作流：生成即发布 → 提醒管理员上网页核查 → 有问题管理员后台下架/改（署名或内容）。
（如需先入库为草稿、不发布，加 --draft。）

- 默认 status='published' + author_name=胡佰亿（frontmatter 的 author_name 优先）+ published_at=NOW()。
  注意：文章带胡佰亿真人署名（E-E-A-T），发布即对外可见，管理员须及时网页核查。
- frontmatter → 列映射：title/slug/excerpt/meta_description；citations/faq → JSONB；
  category_slug 解析为 category_id；tags 不插（留管理员后台补）。
- 正文剥掉首行 `# 标题`（页面 hero 已渲染标题，避免重复 H1）。
- 幂等：slug 已存在则跳过（绝不覆盖——线上可能已被管理员编辑）。
- 用法：
    python3 insert-pillar-drafts.py --dsn "host=localhost user=root dbname=psychology_counseling" \
        [--drafts-dir <目录>] [--author 胡佰亿] [--draft] [--cleanup]
    --draft：以草稿入库（不发布）；--cleanup：插入后立即删除（本地验证用，测试自清理）
- 生产执行：经 ssh 在生产机跑（生产是唯一真实来源，先确保迁移已部署）。
"""
import argparse
import json
import os
import re
import subprocess
import sys
import urllib.request
from pathlib import Path

# 默认 drafts 目录：脚本在 .claude/skills/seo-artical-creator/scripts/ 下，
# 仓库根的 seo-geo/content/drafts 距此 4 级 parent。
DEFAULT_DRAFTS = Path(__file__).resolve().parents[4] / "seo-geo" / "content" / "drafts"


def parse_frontmatter(text: str):
    m = re.match(r"^---\n(.*?)\n---\n(.*)$", text, re.S)
    if not m:
        raise ValueError("缺 frontmatter")
    try:
        import yaml  # type: ignore
        meta = yaml.safe_load(m.group(1))
    except ModuleNotFoundError:
        sys.exit("需要 python3-yaml（pyyaml）")
    return meta, m.group(2)


def strip_leading_h1(body: str) -> str:
    lines = body.lstrip("\n").split("\n")
    if lines and lines[0].startswith("# "):
        lines = lines[1:]
    return "\n".join(lines).lstrip("\n")


def sql_quote(s: str) -> str:
    # dollar-quoting，标签避开正文可能出现的 $$
    tag = "$nbd1$"
    while tag in s:
        tag = tag[:-1] + "x$"
    return f"{tag}{s}{tag}"


def run_psql(dsn: str, sql: str) -> str:
    r = subprocess.run(
        ["psql", dsn, "-v", "ON_ERROR_STOP=1", "-t", "-A", "-c", sql],
        capture_output=True, text=True,
    )
    if r.returncode != 0:
        sys.exit(f"psql 失败: {r.stderr[:800]}")
    return r.stdout.strip()


def push_engines(slugs):
    """发布后主动推送到百度 + IndexNow（镜像 seo.rs，仅用 stdlib，外部 API 契约稳定）。
    从 env 取 SITE_URL / BAIDU_PUSH_TOKEN / INDEXNOW_KEY；缺凭据静默跳过，失败仅打印不抛
    （文章已发布，推送失败不应让脚本报错；可在管理后台重发布或手动补推）。"""
    site = (os.environ.get("SITE_URL") or "").strip().rstrip("/")
    if not site:
        print("  ⚠ 跳过引擎推送：未设 SITE_URL（发布已成功；可在管理后台重发布触发推送，或手动补推）")
        return
    host = site.replace("https://", "").replace("http://", "")
    urls = [f"{site}/blog/{s}" for s in slugs]

    token = (os.environ.get("BAIDU_PUSH_TOKEN") or "").strip()
    if token:
        try:
            req = urllib.request.Request(
                f"http://data.zz.baidu.com/urls?site={host}&token={token}",
                data="\n".join(urls).encode(), headers={"Content-Type": "text/plain"},
            )
            print(f"  百度: {urllib.request.urlopen(req, timeout=10).read().decode()[:200]}")
        except Exception as e:
            print(f"  ⚠ 百度推送失败（不影响已发布）: {e}")
    else:
        print("  跳过百度：未设 BAIDU_PUSH_TOKEN")

    key = (os.environ.get("INDEXNOW_KEY") or "").strip()
    if key:
        try:
            body = json.dumps({"host": host, "key": key,
                               "keyLocation": f"{site}/{key}.txt", "urlList": urls}).encode()
            req = urllib.request.Request(
                "https://api.indexnow.org/indexnow", data=body,
                headers={"Content-Type": "application/json; charset=utf-8"},
            )
            print(f"  IndexNow: http={urllib.request.urlopen(req, timeout=10).status}")
        except Exception as e:
            print(f"  ⚠ IndexNow 推送失败（不影响已发布）: {e}")
    else:
        print("  跳过 IndexNow：未设 INDEXNOW_KEY")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dsn", required=True)
    ap.add_argument("--drafts-dir", default=str(DEFAULT_DRAFTS),
                    help=f"drafts 目录（默认 {DEFAULT_DRAFTS}）")
    ap.add_argument("--author", default="胡佰亿",
                    help="默认署名 author_name（frontmatter 的 author_name 优先；默认 胡佰亿）")
    ap.add_argument("--draft", action="store_true",
                    help="以草稿入库、不发布（默认直接发布并署名）")
    ap.add_argument("--no-push", action="store_true",
                    help="发布后不推送搜索引擎（默认发布即推百度+IndexNow）")
    ap.add_argument("--cleanup", action="store_true", help="插入后删除（本地验证）")
    args = ap.parse_args()

    drafts = Path(args.drafts_dir)
    if not drafts.is_dir():
        sys.exit(f"drafts 目录不存在: {drafts}")

    inserted = []
    for f in sorted(drafts.glob("*.md")):
        meta, body = parse_frontmatter(f.read_text())
        slug = meta["slug"]
        exists = run_psql(args.dsn, f"SELECT 1 FROM blog_posts WHERE slug = {sql_quote(slug)};")
        if exists:
            print(f"跳过（slug 已存在，不覆盖）: {slug}")
            continue
        body_clean = strip_leading_h1(body)
        cat_slug = meta.get("category_slug", "")
        citations = json.dumps(meta.get("citations", []), ensure_ascii=False)
        faq = json.dumps(
            [{"q": x["q"], "a": x["a"]} for x in meta.get("faq", [])], ensure_ascii=False
        )
        # 默认发布并署名；frontmatter 的 author_name 优先于 --author
        status = "draft" if args.draft else "published"
        author = (meta.get("author_name") or args.author or "").strip()
        published_at = "NULL" if args.draft else "NOW()"
        sql = f"""
INSERT INTO blog_posts (slug, title, excerpt, content_markdown, status,
                        category_id, meta_description, citations, faq, source_type,
                        author_name, published_at)
VALUES ({sql_quote(slug)}, {sql_quote(meta['title'])}, {sql_quote(meta.get('excerpt',''))},
        {sql_quote(body_clean)}, {sql_quote(status)},
        (SELECT id FROM blog_categories WHERE slug = {sql_quote(cat_slug)}),
        {sql_quote(meta.get('meta_description',''))},
        {sql_quote(citations)}::jsonb, {sql_quote(faq)}::jsonb, 'original',
        {sql_quote(author)}, {published_at})
RETURNING id;"""
        # psql 对 INSERT...RETURNING 会同时输出行值与「INSERT 0 1」状态行，只取首行
        new_id = run_psql(args.dsn, sql).splitlines()[0].strip()
        if not new_id.isdigit():
            sys.exit(f"RETURNING 解析失败: {new_id!r}")
        inserted.append((new_id, slug))
        verb = "入草稿" if args.draft else f"发布(署名 {author})"
        print(f"✓ {verb} id={new_id} slug={slug}")

    # 发布成功后主动推送搜索引擎（草稿/清理/显式 --no-push 时跳过）
    if inserted and not args.draft and not args.cleanup and not args.no_push:
        print("=== 引擎推送（百度 + IndexNow）===")
        push_engines([slug for _, slug in inserted])

    if args.cleanup and inserted:
        ids = ",".join(i for i, _ in inserted)
        run_psql(args.dsn, f"DELETE FROM blog_posts WHERE id IN ({ids});")
        print(f"已清理验证数据 {len(inserted)} 条（--cleanup）")
    mode = "入草稿" if args.draft else "发布"
    print(f"完成：{mode} {len(inserted)} 条" + ("（已清理）" if args.cleanup else ""))


if __name__ == "__main__":
    main()
