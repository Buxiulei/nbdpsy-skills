import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "xiaohongshu-creator" / "scripts"))

FAKE = {
    "data": {
        "title": "标题",
        "slug": "s1",
        "excerpt": "摘要",
        "content_markdown": "# H1\n\n正文内容",
        "author_name": "胡佰亿",
        "category": {"slug": "psych-101"},
        "citations": [{"title": "t", "url": "u", "source": "s"}],
        "faq": [{"q": "问", "a": "答"}],
        "published_at": "2026-01-01T00:00:00Z"
    }
}


def test_fetch_writes_markdown(tmp_path, monkeypatch):
    import fetch_post
    monkeypatch.setattr(fetch_post, "fetch_json", lambda url: FAKE)
    out = fetch_post.fetch_one("s1", out_dir=tmp_path, api_base="https://x")
    text = Path(out["path"]).read_text(encoding="utf-8")
    assert text.startswith("---\n") and "content_markdown" not in text and "正文内容" in text
    import yaml
    fm = yaml.safe_load(text.split("---")[1])
    assert fm["slug"] == "s1" and fm["category_slug"] == "psych-101" and fm["citations"]


def test_cached_skips_network(tmp_path, monkeypatch):
    import fetch_post
    (tmp_path / "s1.md").write_text("已有", encoding="utf-8")
    monkeypatch.setattr(fetch_post, "fetch_json", lambda url: (_ for _ in ()).throw(AssertionError("不应打网络")))
    out = fetch_post.fetch_one("s1", out_dir=tmp_path, api_base="https://x")
    assert out["cached"] is True
