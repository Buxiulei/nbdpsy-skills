#!/usr/bin/env python3
"""拉取 NBDpsy 咨询师公开资料（只读），供「咨询师推介笔记」场景取材。

用 nbdpsy 免鉴权公开 API 获取咨询师概览 / 单人详情，stdout 输出 JSON。
风格对齐同目录 fetch_post.py（DEFAULT_API_BASE、NBDPSY_API_BASE 可覆盖、data 信封解构）。

🔴 隐私红线：详情响应里的 contracted_price（签约价）属用户隐私口径，
本脚本在返回前**显式删除**该字段——绝不落盘、绝不进笔记。对外价格只用
price_per_session（正式咨询标价）与 communication_price（预沟通价）。
"""
import json
import os
import sys
import argparse
import requests


DEFAULT_API_BASE = os.environ.get("NBDPSY_API_BASE", "https://database.nbdpsy.com")
REQUEST_TIMEOUT = 15


def fetch_json(url):
    """从 URL 获取 JSON 数据。"""
    response = requests.get(url, timeout=REQUEST_TIMEOUT)
    response.raise_for_status()
    return response.json()


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


def main():
    parser = argparse.ArgumentParser(description="拉取 NBDpsy 咨询师公开资料（只读）")

    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--list", action="store_true", help="列出全部咨询师概览")
    group.add_argument("--emp", type=str, help="按 emp_no 拉取单人详情（含 profile_sections）")

    args = parser.parse_args()

    try:
        if args.list:
            result = list_counselors()
        else:
            result = fetch_counselor(args.emp)
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except Exception as e:
        print(f"错误: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
