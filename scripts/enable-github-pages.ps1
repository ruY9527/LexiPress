# ============================================================================
# LexiPress · 一键启用 GitHub Pages 并触发部署
#
# 背景（第一性原理）：
#   Pages 站点是「仓库级资源」，当前 has_pages=False，GET /pages 返回 404。
#   它只能用带 administration:write 权限的 token 通过 REST API 创建，
#   或在网页 Settings → Pages 手动启用。
#   SSH 免密仅用于 git 传输，与 REST API 权限无关——这就是 workflow 里
#   GITHUB_TOKEN 反复失败的本质原因。
#
# 本脚本做的事：
#   1. 检查/引导 gh CLI 登录（浏览器方式，无需手抄 token）
#   2. 用 gh api 调用 PUT /repos/{owner}/{repo}/pages 创建 Pages 站点
#   3. 验证 Pages 已就绪
#   4. 触发 deploy-site.yml 重新部署
#
# 用法：
#   powershell -ExecutionPolicy Bypass -File scripts\enable-github-pages.ps1
# ============================================================================

$ErrorActionPreference = 'Stop'

$REPO  = 'ruY9527/LexiPress'
$BRANCH = 'main'

function Write-Step($msg) { Write-Host "`n==> $msg" -ForegroundColor Cyan }
function Write-Ok($msg)   { Write-Host "    OK  $msg" -ForegroundColor Green }
function Write-Warn2($msg){ Write-Host "    !!  $msg" -ForegroundColor Yellow }

Write-Step "检查 GitHub CLI"
if (-not (Get-Command gh -ErrorAction SilentlyContinue)) {
    Write-Error "未安装 GitHub CLI，请先安装：https://cli.github.com/ 然后重新运行本脚本"
}
Write-Ok ("gh " + (gh --version | Select-Object -First 1))

Write-Step "检查 GitHub 登录状态"
$whoami = $null
try {
    $whoami = gh api user --jq .login 2>$null
} catch { }

if (-not $whoami) {
    Write-Warn2 "gh 尚未登录。接下来会在浏览器打开 GitHub 授权页。"
    Write-Warn2 "登录账号必须是 $($REPO.Split('/')[0])（仓库所有者），否则无权启用 Pages。"
    Write-Host ""
    gh auth login --web --git-protocol ssh --scopes 'repo'
    $whoami = gh api user --jq .login 2>$null
}

if (-not $whoami) {
    Write-Error "gh 登录未完成，请重新运行本脚本。"
}
Write-Ok "已登录为 $whoami"

$owner = $REPO.Split('/')[0]
if ($whoami -ne $owner) {
    Write-Warn2 "当前登录账号 $whoami 与仓库所有者 $owner 不一致，可能无法启用 Pages。"
}

Write-Step "检查 Pages 站点状态"
$pagesJson = $null
try {
    $pagesJson = gh api "repos/$REPO/pages" 2>$null
} catch { }

if ($LASTEXITCODE -eq 0 -and $pagesJson) {
    Write-Ok "Pages 站点已存在，无需创建。"
} else {
    Write-Warn2 "Pages 站点不存在（404），正在创建..."
    # 官方 API：PUT /repos/{owner}/{repo}/pages
    # source.branch=main, source.path=/  => 以 GitHub Actions 为构建源的前置条件
    $body = @{
        source = @{
            branch = $BRANCH
            path   = '/'
        }
    } | ConvertTo-Json -Compress -Depth 5

    $tmp = Join-Path $env:TEMP "lexipress-pages-body.json"
    [System.IO.File]::WriteAllText($tmp, $body, [System.Text.Encoding]::UTF8)

    try {
        $null = gh api -X PUT "repos/$REPO/pages" --input $tmp
    } catch {
        Write-Error "创建 Pages 失败：$($_.Exception.Message)"
    }

    # 大部分仓库创建后 source 默认是 "branch"，需要切换为 GitHub Actions：
    # gh api 无法直接设置 source=github-actions（该字段由网页/配置动作写入），
    # configure-pages action 会在站点存在后自动完成这一步。
    Write-Ok "Pages 站点已创建。"
}

Write-Step "等待 Pages 站点就绪"
$ready = $false
for ($i = 1; $i -le 12; $i++) {
    Start-Sleep -Seconds 2
    try {
        $p = gh api "repos/$REPO/pages" 2>$null
        if ($LASTEXITCODE -eq 0 -and $p) { $ready = $true; break }
    } catch { }
    Write-Host "    等待中 ($i/12)..."
}
if (-not $ready) {
    Write-Error "Pages 站点未在预期时间内就绪，请检查网络或稍后重试。"
}
Write-Ok "Pages 站点已就绪：https://$owner.github.io/$(($REPO -split '/')[1])/"

Write-Step "触发 deploy-site.yml 重新部署"
try {
    $null = gh api -X POST "repos/$REPO/actions/workflows/deploy-site.yml/dispatches" -f "ref=$BRANCH"
    Write-Ok "已触发部署，前往查看：https://github.com/$REPO/actions"
} catch {
    Write-Warn2 "自动触发失败，可手动 Push 一次或到 Actions 页点击 Run workflow。"
}

Write-Host ""
Write-Host "完成。约 30 秒后访问：https://$owner.github.io/$(($REPO -split '/')[1])/" -ForegroundColor Green
Write-Host ""
