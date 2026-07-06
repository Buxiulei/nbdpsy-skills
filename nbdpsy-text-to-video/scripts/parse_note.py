#!/usr/bin/env python3
import argparse
import json
import re
import sys
from pathlib import Path
from typing import Optional


def extract_carousel_section(content: str) -> str:
    """提取 ## 配图轮播 区块（标题行容忍后缀，如「## 配图轮播（6页）」）"""
    match = re.search(r"^## 配图轮播[^\n]*\n(.+?)(?=^## |\Z)", content, re.MULTILINE | re.DOTALL)
    if not match:
        return ""
    return match.group(1)


def split_pages(carousel: str) -> list[tuple[int, str]]:
    """用 re.split 切页，返回 [(页序号, 页体)]"""
    parts = re.split(r"^### P(\d+)", carousel, flags=re.MULTILINE)
    # re.split with group returns: [before, group1, content1, group2, content2, ...]
    pages = []
    for i in range(1, len(parts), 2):
        if i + 1 < len(parts):
            page_num = int(parts[i])
            page_body = parts[i + 1]
            pages.append((page_num, page_body))
    return pages


def extract_prompt(page_body: str) -> Optional[str]:
    """提取首个三反引号围栏中的内容（容忍语言标记，如 ```text）"""
    match = re.search(r"^```[^\n]*$\n(.*?)\n^```[ \t]*$", page_body, re.DOTALL | re.MULTILINE)
    if match:
        return match.group(1).strip()
    return None


def _strip_bullet(line: str) -> str:
    """去掉行首的markdown列表符号（· - •）"""
    return re.sub(r'^[·\-•]\s*', '', line)


def extract_narration_text(page_body: str) -> str:
    """提取围栏外的页面文字（**页面文字**下的文本）

    行级扫描（不用 lookahead）：定位 **页面文字** 所在行，收集其后所有行，
    直到遇到「以 ``` 开头的行」或「以 **绘图提示词 开头的行」为止，避免页面文字
    内含内联加粗（如 "- **大标题**：说明"）时被误截断。
    若页体没有 **页面文字** 标记行，回退为页体中所有围栏外的非空文本行。
    """
    lines = page_body.split('\n')

    marker_idx = None
    for i, line in enumerate(lines):
        if line.strip().startswith("**页面文字**"):
            marker_idx = i
            break

    if marker_idx is not None:
        collected = []
        for line in lines[marker_idx + 1:]:
            stripped = line.strip()
            if stripped.startswith("```") or stripped.startswith("**绘图提示词"):
                break
            collected.append(line)
    else:
        collected = []
        in_fence = False
        for line in lines:
            stripped = line.strip()
            if stripped.startswith("```"):
                in_fence = not in_fence
                continue
            if in_fence:
                continue
            collected.append(line)

    # 去掉markdown列表符号，转纯文本，去空行
    result_lines = []
    for line in collected:
        line = line.strip()
        if not line:
            continue
        line = _strip_bullet(line)
        if line:
            result_lines.append(line)
    return '\n'.join(result_lines)


def extract_subtitle(narration_text: str) -> str:
    """提取 narration_text 的第一行"""
    if not narration_text:
        return ""
    return narration_text.split('\n')[0]


def find_image(page_num: int, images_dir: Optional[Path]) -> Optional[str]:
    """根据页序号匹配图片，返回绝对路径或 null"""
    if not images_dir or not images_dir.exists():
        return None

    # 尝试匹配 P{n}.png/jpg/jpeg（如 P1.png）和 P{0n}.png（如 P01.png）
    candidates = [
        f"P{page_num}.png",
        f"P{page_num}.jpg",
        f"P{page_num}.jpeg",
        f"P{page_num:02d}.png",
        f"P{page_num:02d}.jpg",
        f"P{page_num:02d}.jpeg",
    ]

    # 大小写不敏感搜索
    for file in images_dir.iterdir():
        if file.is_file() and file.name.lower() in [c.lower() for c in candidates]:
            return str(file.absolute())

    return None


def parse_note(
    note_path: Path,
    images_dir: Optional[Path] = None,
) -> dict:
    """解析笔记文件，返回shots.json结构"""
    content = note_path.read_text(encoding="utf-8")

    # 提取frontmatter title
    title_match = re.search(r"^title:\s*(.+?)$", content, re.MULTILINE)
    title = title_match.group(1).strip() if title_match else note_path.stem

    # 提取配图轮播区块
    carousel = extract_carousel_section(content)
    if not carousel:
        print("error: 未找到 ## 配图轮播 区块", file=sys.stderr)
        sys.exit(1)

    # 切页
    pages = split_pages(carousel)
    if not pages:
        print("error: 未找到任何页面 (### P*)", file=sys.stderr)
        sys.exit(1)

    print(f"检测到 {len(pages)} 页", file=sys.stderr)

    # 解析每页
    shots = []
    for idx, (page_num, page_body) in enumerate(pages, 1):
        prompt = extract_prompt(page_body)
        narration_text = extract_narration_text(page_body)
        subtitle = extract_subtitle(narration_text)
        image = find_image(page_num, images_dir)

        if not prompt:
            print(f"warning: P{page_num} 无提示词", file=sys.stderr)
        if not narration_text:
            print(f"warning: P{page_num} 页面文字为空", file=sys.stderr)

        shot = {
            "index": idx,
            "page": page_num,
            "prompt": prompt or "",
            "subtitle": subtitle,
            "narration_text": narration_text,
            "image": image,
            "duration": None,
        }
        shots.append(shot)
        print(f"  P{page_num}: prompt={len(prompt or '')} chars, image={image is not None}", file=sys.stderr)

    if not shots:
        sys.exit(1)

    result = {
        "video": {
            "title": title,
            "ratio": "9:16",
            "source_note": str(note_path.absolute()),
        },
        "shots": shots,
    }

    return result


def main():
    parser = argparse.ArgumentParser(description="笔记→shots.json 确定性解析")
    parser.add_argument("note", help="输入的markdown文件")
    parser.add_argument("--images-dir", help="图片目录")
    parser.add_argument("--out", help="输出文件路径（默认为输入文件同目录shots.json）")

    args = parser.parse_args()

    note_path = Path(args.note).resolve()
    if not note_path.exists():
        print(f"error: 文件不存在: {note_path}", file=sys.stderr)
        sys.exit(1)

    images_dir = Path(args.images_dir).resolve() if args.images_dir else None
    out_path = Path(args.out).resolve() if args.out else note_path.parent / "shots.json"

    # 解析
    result = parse_note(note_path, images_dir)

    # 写入文件（自动创建父目录）
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote {out_path}", file=sys.stderr)

    # stdout：纯JSON (带外包)
    output_info = {
        "out": str(out_path.absolute()),
        "shots": len(result["shots"]),
    }
    print(json.dumps(output_info, ensure_ascii=False))


if __name__ == "__main__":
    main()
