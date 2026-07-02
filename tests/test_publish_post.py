import json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / "seo-artical-creator" / "scripts"))

PILLAR = Path(__file__).parent / "fixtures" / "pillar.md"

def test_build_payload_strips_h1_and_maps():
    import publish_post
    payload = publish_post.build_payload(PILLAR.read_text(encoding="utf-8"), fallback_slug="pillar", author="胡佰亿", draft=False)
    assert payload["title"] and payload["slug"]
    assert not payload["content_markdown"].lstrip().startswith("# ")   # 首行 H1 已剥
    assert payload["status"] == "published" and payload["author_name"]
    assert isinstance(payload.get("citations", []), list)

def test_draft_flag():
    import publish_post
    p = publish_post.build_payload("---\ntitle: T\nslug: s\n---\n正文", fallback_slug="s", author="A", draft=True)
    assert p["status"] == "draft"

def test_slug_conflict_goes_skipped(monkeypatch):
    import publish_post
    class R:
        status_code = 409
        def json(self): return {"success": False, "error": "slug 已存在", "code": "slug_conflict"}
    monkeypatch.setattr(publish_post, "post_request", lambda *a, **k: R())
    result = publish_post.publish_one(PILLAR, api_base="https://x", key="k", author="A", draft=True, update=False, dry_run=False)
    assert result["outcome"] == "skipped"
