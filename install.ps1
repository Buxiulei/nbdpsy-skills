# NBDpsy skills 一键安装（Windows）。用法: .\install.ps1 [claude|codex|agents|all]（默认 all）
# 远程: irm https://raw.githubusercontent.com/Buxiulei/nbdpsy-skills/master/install.ps1 | iex
param(
    [string]$Target = "all"
)

$ErrorActionPreference = "Stop"

$RepoUrl = "https://github.com/Buxiulei/nbdpsy-skills.git"
$Skills = @("seo-artical-creator", "xiaohongshu-creator", "text-to-video", "content-reviewer", "content-pipeline")

# 定位 skill 源目录：脚本同级有 skill 目录则用本地；否则临时 clone（远程 irm | iex 时 $PSScriptRoot 为空）
$Src = $PSScriptRoot
if ([string]::IsNullOrEmpty($Src) -or -not (Test-Path (Join-Path $Src $Skills[0]))) {
    $Tmp = Join-Path $env:TEMP ([System.Guid]::NewGuid().ToString())
    New-Item -ItemType Directory -Path $Tmp | Out-Null
    Write-Host "→ 临时克隆 $RepoUrl ..."
    git clone --depth 1 $RepoUrl (Join-Path $Tmp "repo") *> $null
    $Src = Join-Path $Tmp "repo"
}

function Copy-ToDest {
    param(
        [string]$Dest,
        [string]$Label
    )
    New-Item -ItemType Directory -Path $Dest -Force | Out-Null
    Write-Host "→ 安装到 $Label（$Dest）"
    foreach ($s in $Skills) {
        $destSkill = Join-Path $Dest $s
        if (Test-Path $destSkill) {
            Remove-Item -Path $destSkill -Recurse -Force
        }
        Copy-Item -Path (Join-Path $Src $s) -Destination $destSkill -Recurse -Force
        Write-Host "  ✓ $s"
    }
}

$ClaudeDir = Join-Path $env:USERPROFILE ".claude\skills"
$AgentsDir = Join-Path $env:USERPROFILE ".agents\skills"
$CodexHome = if ($env:CODEX_HOME) { $env:CODEX_HOME } else { Join-Path $env:USERPROFILE ".codex" }
$CodexDir = Join-Path $CodexHome "skills"

switch ($Target) {
    "claude" { Copy-ToDest -Dest $ClaudeDir -Label "Claude Code" }
    "agents" { Copy-ToDest -Dest $AgentsDir -Label "Agent 标准目录" }
    "codex"  {
        Copy-ToDest -Dest $AgentsDir -Label "Agent 标准目录"
        Copy-ToDest -Dest $CodexDir -Label "Codex 旧路径（实拷贝，Windows 不建符号链接）"
    }
    "all" {
        Copy-ToDest -Dest $ClaudeDir -Label "Claude Code"
        Copy-ToDest -Dest $AgentsDir -Label "Agent 标准目录"
        Copy-ToDest -Dest $CodexDir -Label "Codex 旧路径（实拷贝，Windows 不建符号链接）"
    }
    default {
        Write-Host "用法: install.ps1 [claude|codex|agents|all]"
        exit 1
    }
}

Write-Host ""
Write-Host "完成 ✓ 下一步（首次必跑）："
Write-Host "  py `"$Src\setup.py`"   # 检测系统装依赖 + 凭据向导"
