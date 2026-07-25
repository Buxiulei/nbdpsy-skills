#!/usr/bin/env python3
"""拉取 NBDpsy 咨询师公开资料（只读），供「咨询师推介笔记」场景取材。

用 nbdpsy 免鉴权公开 API 获取咨询师概览 / 单人详情，stdout 输出 JSON。
风格对齐同目录 fetch_post.py（DEFAULT_API_BASE、NBDPSY_API_BASE 可覆盖、data 信封解构）。

`--emp <emp_no> --avatar-out <路径>` 额外把系统头像下载到本地（供「科普笔记末页咨询师
推介页」上图床后当 gen_images 的 anchor_url），JSON 追加 avatar_local_path。

🔴 隐私红线：详情响应里的 contracted_price（签约价）属用户隐私口径，
本脚本在返回前**显式删除**该字段——绝不落盘、绝不进笔记。对外价格只用
price_per_session（正式咨询标价）与 communication_price（预沟通价）。
"""
import json
import os
import sys
import argparse
from pathlib import Path
from urllib.parse import urlparse

import requests


DEFAULT_API_BASE = os.environ.get("NBDPSY_API_BASE", "https://database.nbdpsy.com")
REQUEST_TIMEOUT = 15


def fetch_json(url):
    """从 URL 获取 JSON 数据。"""
    response = requests.get(url, timeout=REQUEST_TIMEOUT)
    response.raise_for_status()
    return response.json()


def download_bytes(url):
    """下载二进制内容（头像图片）。与 fetch_json 并列，便于单测在请求层 monkeypatch。"""
    response = requests.get(url, timeout=REQUEST_TIMEOUT)
    response.raise_for_status()
    return response.content


def list_counselors(api_base: str = DEFAULT_API_BASE) -> list:
    """列出全部咨询师概览。

    Returns:
        [{"emp_no","name","title","is_accepting","price_per_session",
          "communication_price","specialties"}]
    """
    url = f"{api_base}/api/client/counselors"
    resp = fetch_json(url)
    counselors = resp["data"].get("counselors", [])

    return [
        {
            "emp_no": c.get("emp_no"),
            # display_name 是对外展示名（name 常为空），姓名口径以它为准
            "name": c.get("display_name") or c.get("name"),
            "title": c.get("title"),
            "is_accepting": c.get("is_accepting"),
            "price_per_session": c.get("price_per_session"),
            "communication_price": c.get("communication_price"),
            "specialties": c.get("specialties"),
        }
        for c in counselors
    ]


def fetch_counselor(emp_no: str, api_base: str = DEFAULT_API_BASE) -> dict:
    """拉取单个咨询师详情（含 profile_sections 结构化全文）。

    返回前**显式删除 contracted_price**（签约价隐私口径，绝不外泄）。
    """
    url = f"{api_base}/api/client/counselors/{emp_no}"
    resp = fetch_json(url)
    data = resp["data"]

    # 🔴 隐私红线：签约价绝不外泄。纵深防御——任意层级 key 含 contracted 一律递归删除
    # （防后端未来改名/挪进嵌套结构绕过顶层 del）
    _scrub_contracted(data)

    return data


def _scrub_contracted(obj):
    """递归删除任意层级 key 含 'contracted' 的字段（签约价隐私红线的纵深防御）。"""
    if isinstance(obj, dict):
        for k in [k for k in obj if "contracted" in k.lower()]:
            del obj[k]
        for v in obj.values():
            _scrub_contracted(v)
    elif isinstance(obj, list):
        for v in obj:
            _scrub_contracted(v)


def download_avatar(detail: dict, out_path: str, api_base: str = DEFAULT_API_BASE) -> str:
    """把详情里的系统头像下载到本地，返回落盘路径。

    `avatar_url` 后端下发的是**相对路径**（`/static/avatars/xxx.jpg`），要拼上 api_base
    才能下载；已是绝对 URL 时原样用。out_path 是已存在目录或以分隔符结尾 → 自动命名
    `avatar-<emp_no><原扩展名>`，否则当文件路径用。

    后台没头像时抛 ValueError 而不是静默返回 None——调用方是明确来要头像的，
    静默会让后续出图拿到空 anchor、白烧一次额度。
    """
    rel = detail.get("avatar_url")
    if not rel:
        raise ValueError(
            f"该咨询师（{detail.get('emp_no')}）后台未上传头像，无法做末页推介页；"
            "请运营先在管理后台补头像，或本篇不做推介末页")

    url = rel if rel.startswith(("http://", "https://")) else f"{api_base}/{rel.lstrip('/')}"
    dest = Path(out_path)
    if dest.is_dir() or out_path.endswith(("/", os.sep)):
        ext = os.path.splitext(urlparse(url).path)[1] or ".jpg"
        dest = dest / f"avatar-{detail.get('emp_no') or 'counselor'}{ext}"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(download_bytes(url))
    return str(dest.resolve())


def main():
    parser = argparse.ArgumentParser(description="拉取 NBDpsy 咨询师公开资料（只读）")

    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--list", action="store_true", help="列出全部咨询师概览")
    group.add_argument("--emp", type=str, help="按 emp_no 拉取单人详情（含 profile_sections）")
    parser.add_argument("--avatar-out", metavar="路径",
                        help="配合 --emp：把系统头像下载到该路径（目录则自动命名 "
                             "avatar-<emp_no>.<ext>），输出 JSON 追加 avatar_local_path")

    args = parser.parse_args()
    if args.avatar_out and not args.emp:
        parser.error("--avatar-out 需配合 --emp 使用（--list 概览不含 avatar_url）")

    try:
        if args.list:
            result = list_counselors()
        else:
            result = fetch_counselor(args.emp)
            if args.avatar_out:
                result["avatar_local_path"] = download_avatar(result, args.avatar_out)
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except Exception as e:
        print(f"错误: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
