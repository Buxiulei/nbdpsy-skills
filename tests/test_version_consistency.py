"""版本号守卫：三处版本字段必须彼此相等，且等于 CHANGELOG 里最大的语义化版本。

2026-08-05 一天之内被并行会话**三次**把版本文件写回旧号（1.62.x → 1.59.x），装了新版的
机器会被判成"版本过旧"。CHANGELOG 顶部那段「铁律」靠人眼守不住，这里用测试钉死两类事故：
  ① 版本文件被别的线倒退回小号；
  ② 加了新 CHANGELOG 节却忘了改版本文件。
"""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PLUGIN_JSON = ROOT / ".claude-plugin" / "plugin.json"
MARKETPLACE_JSON = ROOT / ".claude-plugin" / "marketplace.json"
CHANGELOG = ROOT / "CHANGELOG.md"

# CHANGELOG 版本节标题：`## [1.62.1]`（后面通常跟日期，不参与匹配）
HEADING_RE = re.compile(r"^##\s*\[(\d+\.\d+\.\d+)\]", re.M)

FIX_HINT = ("仓库只有一个版本序列：新版本号 = CHANGELOG 顶部那个号 +1，不是「你这条线上一个号 +1」。"
            "发版改三处：plugin.json 的 version、marketplace.json 的 metadata.version 与 "
            "plugins[].version。")


def _semver(v: str) -> tuple[int, int, int]:
    major, minor, patch = v.split(".")
    return int(major), int(minor), int(patch)


def version_fields() -> dict[str, str]:
    """全部版本字段 → {人话位置: 版本号}。位置串直接进报错信息，方便一眼定位改哪儿。"""
    plugin = json.loads(PLUGIN_JSON.read_text(encoding="utf-8"))
    market = json.loads(MARKETPLACE_JSON.read_text(encoding="utf-8"))
    fields = {"plugin.json → version": plugin["version"],
              "marketplace.json → metadata.version": market["metadata"]["version"]}
    for i, p in enumerate(market.get("plugins", [])):
        fields[f"marketplace.json → plugins[{i}].version"] = p["version"]
    return fields


def changelog_max() -> str:
    """CHANGELOG 里最大的语义化版本（按数值比，不是按出现顺序——顶部被别的线顶下去也照样对）。"""
    found = HEADING_RE.findall(CHANGELOG.read_text(encoding="utf-8"))
    assert found, f"{CHANGELOG} 里一个 `## [x.y.z]` 版本节都没有，版本守卫失去基准"
    return max(found, key=_semver)


def test_version_fields_agree_with_each_other():
    fields = version_fields()
    assert len(fields) >= 3, f"版本字段少于 3 处，是不是漏了某个文件？实际：{fields}"
    distinct = set(fields.values())
    detail = "；".join(f"{k} = {v}" for k, v in fields.items())
    assert len(distinct) == 1, (
        f"版本文件互相不一致（同一次发版必须三处同号）：{detail}。{FIX_HINT}")


def test_version_files_match_changelog_max():
    fields = version_fields()
    want = changelog_max()
    stale = {k: v for k, v in fields.items() if v != want}
    detail = "；".join(f"{k} = {v}" for k, v in stale.items())
    assert not stale, (
        f"版本文件被倒退或漏更：当前应为 {want}（CHANGELOG 里最大的版本节），"
        f"但这些字段还是旧号 —— {detail}。{FIX_HINT}")
