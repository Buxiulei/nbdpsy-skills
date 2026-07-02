#!/usr/bin/env python3
"""把 shared/ 下共享文件同步到各 skill 的 scripts/，保持 skill 目录自包含。"""
import shutil, sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
SKILLS = ["seo-artical-creator", "xiaohongshu-creator", "text-to-video", "content-reviewer"]

def main():
    changed = []
    for src in (ROOT / "shared").glob("*.py"):
        for skill in SKILLS:
            dst_dir = ROOT / skill / "scripts"
            if not dst_dir.parent.is_dir():
                continue  # skill 尚未创建（如 content-reviewer 在 Task 15 才建）
            dst_dir.mkdir(exist_ok=True)
            dst = dst_dir / src.name
            if not dst.exists() or dst.read_bytes() != src.read_bytes():
                shutil.copy2(src, dst)
                changed.append(str(dst.relative_to(ROOT)))
    print("\n".join(changed) if changed else "已全部同步，无变更")

if __name__ == "__main__":
    main()
