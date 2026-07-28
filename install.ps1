# NBDpsy skills 一键安装（Windows）。用法: .\install.ps1 [claude|codex|agents|all] [-SkillsOnly]（默认 all；-SkillsOnly 跳过自动装依赖）
# 远程: irm https://raw.githubusercontent.com/Buxiulei/nbdpsy-skills/master/install.ps1 | iex
param(
    [string]$Target = "all",
    [switch]$SkillsOnly
)

$ErrorActionPreference = "Stop"

$RepoUrl = "https://github.com/Buxiulei/nbdpsy-skills.git"
$Skills = @("nbdpsy-seo-artical-creator", "nbdpsy-xiaohongshu-creator", "nbdpsy-text-to-video", "nbdpsy-youtube-transport", "nbdpsy-content-reviewer", "nbdpsy-content-pipeline", "nbdpsy-guide")

# 旧版（无 nbdpsy- 前缀）名，安装时顺带清理
$LegacySkills = @('seo-artical-creator','xiaohongshu-creator','text-to-video','content-reviewer','content-pipeline')
# 定位 skill 源目录：脚本同级有 skill 目录则用本地；否则临时 clone（远程 irm | iex 时 $PSScriptRoot 为空）
$Src = $PSScriptRoot
$SrcKind = "local-repo"
if ([string]::IsNullOrEmpty($Src) -or -not (Test-Path (Join-Path $Src $Skills[0]))) {
    $Tmp = Join-Path $env:TEMP ([System.Guid]::NewGuid().ToString())
    New-Item -ItemType Directory -Path $Tmp | Out-Null
    Write-Host "→ 临时克隆 $RepoUrl ..."
    git clone --depth 1 $RepoUrl (Join-Path $Tmp "repo") *> $null
    if ($LASTEXITCODE -ne 0) { throw "git clone 失败（网络或权限问题）" }
    $Src = Join-Path $Tmp "repo"
    $SrcKind = "github-clone"
}

# 版本标记：每个安装目的地落一份 .nbdpsy-skills-install.json，供 doctor 上报本机装的是哪版
# 取值失败一律写 unknown、写盘失败只提示不中断——标记是锦上添花，装不上也得把 skill 装完
function Write-InstallMarker {
    param([string]$Dest)
    $ver = "unknown"; $commit = "unknown"; $now = "unknown"
    try {
        $pluginJson = Join-Path $Src ".claude-plugin\plugin.json"
        if (Test-Path $pluginJson) {
            $m = [regex]::Match((Get-Content -Path $pluginJson -Raw), '"version"\s*:\s*"([^"]*)"')
            if ($m.Success -and $m.Groups[1].Value) { $ver = $m.Groups[1].Value }
        }
    } catch { }
    $PrevEAP = $ErrorActionPreference
    try {
        $ErrorActionPreference = "Continue"
        $c = & git -C $Src rev-parse --short HEAD 2>$null
        if ($LASTEXITCODE -eq 0 -and $c) { $commit = ([string]($c | Select-Object -First 1)).Trim() }
    } catch {
    } finally {
        $ErrorActionPreference = $PrevEAP
    }
    try { $now = (Get-Date -Format o) -replace '\.\d+', '' } catch { }
    try {
        $json = "{`n  ""version"": ""$ver"",`n  ""commit"": ""$commit"",`n  ""installed_at"": ""$now"",`n  ""source"": ""$SrcKind""`n}`n"
        # 绝对路径：.NET API 不认 PowerShell 的当前位置
        $markerPath = Join-Path ((Resolve-Path -LiteralPath $Dest).Path) ".nbdpsy-skills-install.json"
        # UTF-8 无 BOM：Set-Content -Encoding UTF8 在 PS 5.1 会写 BOM，导致 doctor 端 json.load 解析失败
        [System.IO.File]::WriteAllText($markerPath, $json, (New-Object System.Text.UTF8Encoding($false)))
        Write-Host "  ✓ 版本标记 v$ver（$commit）"
    } catch {
        Write-Host "  ! 版本标记写入失败（不影响 skill 安装）"
    }
}

function Copy-ToDest {
    param(
        [string]$Dest,
        [string]$Label
    )
    if ([string]::IsNullOrEmpty($Dest)) { throw "Dest 为空，拒绝执行删除/拷贝" }
    New-Item -ItemType Directory -Path $Dest -Force | Out-Null
    Write-Host "→ 安装到 $Label（$Dest）"
    foreach ($s in $LegacySkills) {
        $legacyPath = Join-Path $Dest $s
        if (Test-Path $legacyPath) {
            Remove-Item -Path $legacyPath -Recurse -Force
            Write-Host "  ✗ 清理旧名 $s"
        }
    }
    foreach ($s in $Skills) {
        $destSkill = Join-Path $Dest $s
        if (Test-Path $destSkill) {
            Remove-Item -Path $destSkill -Recurse -Force
        }
        Copy-Item -Path (Join-Path $Src $s) -Destination $destSkill -Recurse -Force
        Write-Host "  ✓ $s"
    }
    Write-InstallMarker -Dest $Dest
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
Write-Host "完成 ✓ 正在自动安装依赖 + 检测凭据..."
if ($SkillsOnly -or $env:NBDPSY_SKIP_SETUP -eq "1") {
    Write-Host "已跳过（-SkillsOnly）。如需稍后配置：py `"$Src\setup.py`""
} else {
    $PythonCmd = $null
    if (Get-Command python -ErrorAction SilentlyContinue) {
        $PythonCmd = "python"
    } elseif (Get-Command py -ErrorAction SilentlyContinue) {
        $PythonCmd = "py"
    }
    if ($PythonCmd) {
        $PrevEAP = $ErrorActionPreference
        $ErrorActionPreference = "Continue"
        try {
            & $PythonCmd "$Src\setup.py"
        } catch {
            Write-Host "环境安装向导执行出错（不影响 skill 已安装）：$_"
        }
        $ErrorActionPreference = $PrevEAP
        Write-Host "如报缺凭据：找管理员要「凭据配置包」，然后 py nbdpsy_common.py secret import <文件> 一键导入"
    } else {
        Write-Host "未检测到 Python，请先安装（winget install Python.Python.3.12），再手动运行：py `"$Src\setup.py`""
    }
}
