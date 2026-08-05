# 一键创建 GitHub 仓库并推送（二选一授权方式）
#
# 方式 A（推荐）：安装 GitHub CLI 并登录
#   winget install GitHub.cli
#   gh auth login
#   .\scripts\push-to-github.ps1
#
# 方式 B：提供 Personal Access Token
#   $env:GITHUB_TOKEN="ghp_xxx"
#   .\scripts\push-to-github.ps1

$ErrorActionPreference = "Stop"
$RepoName = "ai-content-pipeline"
$Description = "AI 内容生产管线：热点抓取 / RAG 生成 / 三层质检 / 人工审核 / 多渠道发布 / RAG 客服 / GEO 工程化"

if ($env:GITHUB_TOKEN) {
    $headers = @{ Authorization = "Bearer $env:GITHUB_TOKEN"; Accept = "application/vnd.github+json" }
    $body = @{
        name = $RepoName
        description = $Description
        private = $false
        auto_init = $false
    } | ConvertTo-Json

    $resp = Invoke-RestMethod -Method Post -Uri "https://api.github.com/user/repos" -Headers $headers -Body $body
    Write-Host "仓库已创建: $($resp.html_url)"

    git remote remove origin 2>$null
    git remote add origin "https://$env:GITHUB_TOKEN@github.com/Zhangyife1/$RepoName.git"
    git push -u origin main
    git remote set-url origin "https://github.com/Zhangyife1/$RepoName.git"
    Write-Host "推送完成: https://github.com/Zhangyife1/$RepoName"
} elseif (Get-Command gh -ErrorAction SilentlyContinue) {
    gh repo create $RepoName --public --source . --remote origin --push --description $Description
    Write-Host "推送完成: https://github.com/Zhangyife1/$RepoName"
} else {
    Write-Host "未检测到 gh 或 GITHUB_TOKEN。"
    Write-Host "请先执行: winget install GitHub.cli 然后 gh auth login"
    exit 1
}

