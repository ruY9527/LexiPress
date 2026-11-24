# ============================================================================
# LexiPress - 一键启用 GitHub Pages 并触发部署
#
# 第一性原理：
#   Pages 站点是「仓库级资源」，当前 has_pages=False，GET /pages 返回 404。
#   它只能用带 administration:write 权限的 token 通过 REST API 创建，
#   或在网页 Settings -> Pages 手动启用。
#   SSH 免密只用于 git 传输，与 REST API 权限体系无关。
#
# 本脚本：
#   1. 检查/引导 gh CLI 登录（浏览器方式，无需手抄 token）
#   2. 用 gh api 以 build_type=workflow 创建 Pages 站点
#   3. 等待就绪并触发 deploy-site.yml 重新部署
#
# 用法：
#   powershell -ExecutionPolicy Bypass -File scripts\enable-github-pages.ps1
# ============================================================================

$ErrorActionPreference = 'Stop'

$REPO = 'ruY9527/LexiPress'
$BRANCH = 'main'
$OWNER = ($REPO -split '/')[0]
$REPONAME = ($REPO -split '/')[1]
$PAGES_URL = "https://$OWNER.github.io/$REPONAME/"
$SETTINGS_URL = "https://github.com/$REPO/settings/pages"

function Show-Step([string]$msg) {
  Write-Host ""
  Write-Host "==> $msg" -ForegroundColor Cyan
}
function Show-Ok([string]$msg) {
  Write-Host "    OK  $msg" -ForegroundColor Green
}
function Show-Warn([string]$msg) {
  Write-Host "    !!  $msg" -ForegroundColor Yellow
}

Show-Step '检查 GitHub CLI'
if (-not (Get-Command gh -ErrorAction SilentlyContinue)) {
  Write-Error '未安装 GitHub CLI，请先安装 https://cli.github.com/ 后重新运行'
}
Write-Ok 'gh CLI 已安装'

Show-Step '检查 GitHub 登录状态'
$login = ''
try {
  $login = (gh api user --jq .login 2>$null).Trim()
} catch {
  $login = ''
}

if ([string]::IsNullOrEmpty($login)) {
  Show-Warn 'gh 尚未登录。将打开浏览器授权，请使用仓库所有者账号登录。'
  Write-Host ''
  gh auth login --web --git-protocol ssh --scopes 'repo,admin:org,delete_repo'
  try {
    $login = (gh api user --jq .login 2>$null).Trim()
  } catch {
    $login = ''
  }
}

if ([string]::IsNullOrEmpty($login)) {
  Write-Error 'gh 登录未完成，请重新运行本脚本。'
}
Write-Ok ("已登录为 " + $login)

if ($login -ne $OWNER) {
  Show-Warn ("当前账号 " + $login + " 与仓库所有者 " + $OWNER + " 不一致，可能无法创建 Pages。")
}

Show-Step '检查 Pages 站点状态'
$exists = $false
try {
  $null = gh api "repos/$REPO/pages" 2>$null
  if ($LASTEXITCODE -eq 0) {
    $exists = $true
  }
} catch {
  $exists = $false
}

if ($exists) {
  Write-Ok 'Pages 站点已存在，无需创建。'
} else {
  Show-Warn 'Pages 站点不存在，正在通过 API 创建（build_type=workflow）...'
  $bodyFile = Join-Path $env:TEMP 'lexipress-pages-body.json'
  $payload = @{ build_type = 'workflow' } | ConvertTo-Json -Compress
  [System.IO.File]::WriteAllText($bodyFile, $payload, [System.Text.Encoding]::UTF8)

  try {
    $null = gh api -X PUT "repos/$REPO/pages" --input $bodyFile 2>&1
  } catch {
    Show-Warn 'API 创建失败，将改为打开网页设置页。'
    Start-Process $SETTINGS_URL
    Write-Host ''
    Write-Warn '请在打开的页面中：Build and deployment -> Source 设为 GitHub Actions -> Save'
    Write-Warn '保存后回到 Actions 页 Re-run 一次即可。'
    exit 1
  }
  Write-Ok 'Pages 站点已创建。'
}

Show-Step '等待 Pages 站点就绪'
$ready = $false
for ($i = 1; $i -le 12; $i++) {
  Start-Sleep -Seconds 2
  try {
    $null = gh api "repos/$REPO/pages" 2>$null
    if ($LASTEXITCODE -eq 0) {
      $ready = $true
      break
    }
  } catch {
    $ready = $false
  }
  Write-Host ("    等待中 (" + $i + "/12)...")
}
if (-not $ready) {
  Write-Error 'Pages 站点未在预期时间内就绪，请稍后重试。'
}
Write-Ok ("Pages 站点已就绪: " + $PAGES_URL)

Show-Step '触发 deploy-site.yml 重新部署'
try {
  $null = gh api -X POST "repos/$REPO/actions/workflows/deploy-site.yml/dispatches" -f "ref=$BRANCH" 2>$null
  Write-Ok '已触发部署，前往查看: https://github.com/REPO/actions'
} catch {
  Show-Warn '自动触发失败，可手动 Push 一次或到 Actions 页点击 Run workflow。'
}

Write-Host ''
Write-Host ("完成。约 30 秒后访问: " + $PAGES_URL) -ForegroundColor Green
Write-Host ''
