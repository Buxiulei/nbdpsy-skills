import json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / "nbdpsy-seo-artical-creator" / "scripts"))

import pytest
import requests

PILLAR = Path(__file__).parent / "fixtures" / "pillar.md"


def test_build_payload_strips_h1_and_maps():
    import publish_post
    payload = publish_post.build_payload(PILLAR.read_text(encoding="utf-8"), fallback_slug="pillar", author="胡佰亿", draft=False)
    assert payload["title"] and payload["slug"]
    assert not payload["content_markdown"].lstrip().startswith("# ")   # 首行 H1 已剥
    assert payload["status"] == "published" and payload["author_name"]
    assert isinstance(payload.get("citations", []), list)
    assert payload.get("meta_description")  # pillar.md 含 meta_description

def test_draft_flag():
    import publish_post
    p = publish_post.build_payload("---\ntitle: T\nslug: s\n---\n正文", fallback_slug="s", author="A", draft=True)
    assert p["status"] == "draft"

def test_slug_conflict_goes_skipped(monkeypatch):
    import publish_post
    class R:
        status_code = 409
        text = "slug 已存在"
        def json(self): return {"success": False, "error": "slug 已存在", "code": "slug_conflict"}
    monkeypatch.setattr(publish_post, "send_request", lambda *a, **k: R())
    result = publish_post.publish_one(PILLAR, api_base="https://x", key="k", author="A", draft=True, update=False, dry_run=False)
    assert result["outcome"] == "skipped"


# ---- null 泄漏：可选字段键存在但值为 None（YAML 空值）不应发出 ----

def test_optional_none_fields_are_omitted_from_payload():
    import publish_post
    md = (
        "---\n"
        "title: T\n"
        "slug: s\n"
        "excerpt:\n"
        "category_slug:\n"
        "meta_title:\n"
        "meta_description:\n"
        "cover_image_url:\n"
        "video_url:\n"
        "citations:\n"
        "---\n"
        "正文"
    )
    payload = publish_post.build_payload(md, fallback_slug="s", author="A", draft=False)
    for key in ("excerpt", "category_slug", "meta_title", "meta_description", "cover_image_url", "video_url", "citations"):
        assert key not in payload, f"{key} 应因值为 None 被剔除，实际 payload={payload}"


# ---- meta_title 与 meta_description 字段映射 ----

def test_meta_title_and_description_included_in_payload():
    import publish_post
    md = (
        "---\n"
        "title: T\n"
        "slug: s\n"
        "meta_title: SEO标题\n"
        "meta_description: SEO描述文本\n"
        "---\n"
        "正文"
    )
    payload = publish_post.build_payload(md, fallback_slug="s", author="A", draft=False)
    assert payload.get("meta_title") == "SEO标题"
    assert payload.get("meta_description") == "SEO描述文本"


# ---- 409 语义核对：非 slug_conflict 的 409 应算 failed ----

def test_409_with_other_code_is_failed(monkeypatch):
    import publish_post
    class R:
        status_code = 409
        text = "too many requests"
        def json(self): return {"success": False, "error": "too many requests", "code": "rate_limited"}
    monkeypatch.setattr(publish_post, "send_request", lambda *a, **k: R())
    result = publish_post.publish_one(PILLAR, api_base="https://x", key="k", author="A", draft=True, update=False, dry_run=False)
    assert result["outcome"] == "failed"
    assert "too many requests" in result["error"]


# ---- publish_one 成功路径 ----

def test_publish_one_success_returns_id_and_slug(monkeypatch):
    import publish_post
    class R:
        status_code = 201
        def json(self): return {"success": True, "data": {"id": 42, "slug": "fuzaxing-chuangshang-cptsd-zhinan"}}
    monkeypatch.setattr(publish_post, "send_request", lambda *a, **k: R())
    result = publish_post.publish_one(PILLAR, api_base="https://x", key="k", author="A", draft=False, update=False, dry_run=False)
    assert result["outcome"] == "published"
    assert result["id"] == 42
    assert result["slug"]


# ---- 网络异常一律转 failed ----

def test_network_exception_becomes_failed(monkeypatch):
    import publish_post
    def raise_conn(*a, **k):
        raise requests.ConnectionError("boom")
    monkeypatch.setattr(publish_post, "send_request", raise_conn)
    result = publish_post.publish_one(PILLAR, api_base="https://x", key="k", author="A", draft=False, update=False, dry_run=False)
    assert result["outcome"] == "failed"

def test_timeout_becomes_failed(monkeypatch):
    import publish_post
    def raise_timeout(*a, **k):
        raise requests.Timeout("timed out")
    monkeypatch.setattr(publish_post, "send_request", raise_timeout)
    result = publish_post.publish_one(PILLAR, api_base="https://x", key="k", author="A", draft=False, update=False, dry_run=False)
    assert result["outcome"] == "failed"


# ---- --update 走 PUT ----

def test_update_uses_put(monkeypatch):
    import publish_post
    captured = {}
    class R:
        status_code = 200
        def json(self): return {"success": True, "data": {"id": 1, "slug": "s"}}
    def fake_send(method, url, key, payload):
        captured["method"] = method
        return R()
    monkeypatch.setattr(publish_post, "send_request", fake_send)
    result = publish_post.publish_one(PILLAR, api_base="https://x", key="k", author="A", draft=False, update=True, dry_run=False)
    assert captured["method"] == "PUT"
    assert result["outcome"] == "published"


# ---- dry-run 语义 ----

def test_dry_run_bad_file_exits_1(monkeypatch, tmp_path):
    import publish_post
    bad = tmp_path / "bad.md"
    bad.write_text("没有 frontmatter 的坏文件", encoding="utf-8")
    monkeypatch.setattr(publish_post.nbdpsy_common, "get_secret", lambda k: "testkey")
    monkeypatch.setattr(sys, "argv", ["publish_post.py", "--file", str(bad), "--dry-run"])
    with pytest.raises(SystemExit) as exc:
        publish_post.main()
    assert exc.value.code == 1

def test_dry_run_good_file_marks_entries_and_exits_0(monkeypatch, capsys):
    import publish_post
    monkeypatch.setattr(publish_post.nbdpsy_common, "get_secret", lambda k: "testkey")
    monkeypatch.setattr(sys, "argv", ["publish_post.py", "--file", str(PILLAR), "--dry-run"])
    publish_post.main()  # 不应 sys.exit（无 failed）
    out = capsys.readouterr().out.strip().splitlines()[-1]
    data = json.loads(out)
    assert data["dry_run"] is True
    assert data["failed"] == []
    assert data["published"][0]["dry_run"] is True


# ---- main() 端到端：published 条目含 id/slug/status ----

def test_main_end_to_end_published_entry_has_id_slug_status(monkeypatch, capsys):
    import publish_post
    class R:
        status_code = 201
        def json(self): return {"success": True, "data": {"id": 42, "slug": "fuzaxing-chuangshang-cptsd-zhinan"}}
    monkeypatch.setattr(publish_post, "send_request", lambda *a, **k: R())
    monkeypatch.setattr(publish_post.nbdpsy_common, "get_secret", lambda k: "testkey")
    monkeypatch.setattr(sys, "argv", ["publish_post.py", "--file", str(PILLAR), "--draft"])
    publish_post.main()
    out = capsys.readouterr().out.strip().splitlines()[-1]
    data = json.loads(out)
    entry = data["published"][0]
    assert entry["id"] == 42
    assert entry["slug"]
    assert entry["status"] == "draft"


# ---- --file / --drafts-dir 互斥 ----

def test_file_and_drafts_dir_mutually_exclusive(monkeypatch):
    import publish_post
    monkeypatch.setattr(sys, "argv", ["publish_post.py", "--file", "a.md", "--drafts-dir", "d"])
    with pytest.raises(SystemExit) as exc:
        publish_post.main()
    assert exc.value.code == 2
