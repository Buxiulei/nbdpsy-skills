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


def test_list_posts_url_params(monkeypatch):
    import fetch_post

    # 捕获 fetch_json 的 URL 参数
    captured_url = None

    def mock_fetch_json(url):
        nonlocal captured_url
        captured_url = url
        return {
            "data": {
                "posts": [
                    {"slug": "p1", "title": "标题1", "published_at": "2026-01-01T00:00:00Z"},
                    {"slug": "p2", "title": "标题2", "published_at": "2026-01-02T00:00:00Z"},
                ]
            }
        }

    monkeypatch.setattr(fetch_post, "fetch_json", mock_fetch_json)

    result = fetch_post.list_posts(3, api_base="https://x")

    # 断言 URL 包含 page_size=3
    assert "page_size=3" in captured_url
    assert "page=1" in captured_url

    # 断言返回列表长度为 2
    assert len(result) == 2

    # 断言每项包含所需的三个键
    for post in result:
        assert "slug" in post
        assert "title" in post
        assert "published_at" in post

    # 断言具体数据
    assert result[0]["slug"] == "p1"
    assert result[1]["slug"] == "p2"
