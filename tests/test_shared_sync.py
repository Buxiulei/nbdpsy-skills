from pathlib import Path
ROOT = Path(__file__).parent.parent

def test_vendored_copies_match_canonical():
    for src in (ROOT / "shared").glob("*.py"):
        for skill_dir in ROOT.iterdir():
            dst = skill_dir / "scripts" / src.name
            if dst.is_file():
                assert dst.read_bytes() == src.read_bytes(), f"{dst} 与 shared/ 不同步，跑 python3 tools/sync_shared.py"
