# slack-expert install script (Windows PowerShell)
$ErrorActionPreference = "Stop"

$SkillName = "x-slack"
$ClaudeDir = "$env:USERPROFILE\.claude"
$SkillDir = "$ClaudeDir\skills\$SkillName"

Write-Host "=== slack-expert installer ===" -ForegroundColor Cyan
Write-Host ""

# 1. Check prerequisites
if (-not (Get-Command claude -ErrorAction SilentlyContinue)) {
    Write-Error "Claude Code CLI not found. Install it first: https://github.com/anthropics/claude-code"
    exit 1
}
Write-Host "OK Claude Code CLI found" -ForegroundColor Green

# 2. Prompt for company name
$Company = Read-Host "Enter company name (used for data directory, e.g. acme)"
if (-not $Company) { $Company = "mycompany" }
Write-Host "Company: $Company"

$DataDir = "$ClaudeDir\companies\$Company\data"
$SlackDataDir = "$DataDir\slack"

# 3. Create data directories if missing
New-Item -ItemType Directory -Force -Path $SlackDataDir | Out-Null
Write-Host "OK Data directory: $SlackDataDir" -ForegroundColor Green

# 4. Copy shared template files (never overwrite existing)
Get-ChildItem "templates\data\*.template" | ForEach-Object {
    $target = Join-Path $DataDir ($_.Name -replace '\.template$', '')
    if (-not (Test-Path $target)) {
        Copy-Item $_.FullName $target
        Write-Host "  Created: $target"
    } else {
        Write-Host "  Skipped (exists): $target"
    }
}

# 5. Copy slack-specific template files
Get-ChildItem "templates\data\slack\*.template" | ForEach-Object {
    $target = Join-Path $SlackDataDir ($_.Name -replace '\.template$', '')
    if (-not (Test-Path $target)) {
        Copy-Item $_.FullName $target
        Write-Host "  Created: $target"
    } else {
        Write-Host "  Skipped (exists): $target"
    }
}

# 6. Install skill
New-Item -ItemType Directory -Force -Path $SkillDir | Out-Null
Copy-Item ".claude\skills\$SkillName\*" $SkillDir -Force
Write-Host "OK Skill installed: $SkillDir" -ForegroundColor Green

Write-Host ""
Write-Host "=== Installation complete ===" -ForegroundColor Cyan
Write-Host ""
Write-Host "Next steps:"
Write-Host "  1. Configure Slack MCP OAuth — see docs/setup.md"
Write-Host "  2. Edit $DataDir\people.yml with your team"
Write-Host "  3. Edit $SlackDataDir\message-tracker.yml with your channels"
Write-Host "  4. Run: /x-slack help"
