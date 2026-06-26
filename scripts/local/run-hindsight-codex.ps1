param(
  [string]$EnvFile = "",
  [int]$Port = 0,
  [string]$DatabaseUrl = "",
  [switch]$NoSync
)

$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Resolve-Path (Join-Path $ScriptDir "..\..")
$ApiProject = Join-Path $RepoRoot "hindsight-api-slim"
if (-not $EnvFile) {
  $EnvFile = Join-Path $RepoRoot ".env"
}

function Import-DotEnv {
  param([string]$Path)
  if (-not (Test-Path -LiteralPath $Path)) {
    throw "Env file not found: $Path"
  }
  foreach ($line in Get-Content -LiteralPath $Path) {
    $trimmed = $line.Trim()
    if (-not $trimmed -or $trimmed.StartsWith("#")) {
      continue
    }
    $parts = $trimmed -split "=", 2
    if ($parts.Count -ne 2) {
      continue
    }
    $name = $parts[0].Trim()
    $value = $parts[1].Trim()
    if (($value.StartsWith('"') -and $value.EndsWith('"')) -or ($value.StartsWith("'") -and $value.EndsWith("'"))) {
      $value = $value.Substring(1, $value.Length - 2)
    }
    [Environment]::SetEnvironmentVariable($name, $value, "Process")
  }
}

function Test-CodexAuth {
  if (-not $env:CODEX_HOME) {
    $env:CODEX_HOME = Join-Path $env:USERPROFILE ".codex"
  }
  $authPath = Join-Path $env:CODEX_HOME "auth.json"
  if (-not (Test-Path -LiteralPath $authPath)) {
    throw "Codex auth.json not found at $authPath. Run 'codex auth login' first."
  }
  $auth = Get-Content -LiteralPath $authPath -Raw | ConvertFrom-Json
  if ($auth.auth_mode -ne "chatgpt") {
    throw "Expected Codex auth_mode=chatgpt, got '$($auth.auth_mode)'. Run 'codex auth login' again."
  }
  if (-not $auth.tokens.access_token -or -not $auth.tokens.refresh_token -or -not $auth.tokens.account_id) {
    throw "Codex auth.json is missing access_token, refresh_token, or account_id. Run 'codex auth login' again."
  }
}

Import-DotEnv -Path $EnvFile
if ($Port -gt 0) {
  $env:HINDSIGHT_API_PORT = "$Port"
}
if ($DatabaseUrl) {
  $env:HINDSIGHT_API_DATABASE_URL = $DatabaseUrl
}
if (-not $env:HINDSIGHT_API_HOST) {
  $env:HINDSIGHT_API_HOST = "127.0.0.1"
}
if (-not $env:HINDSIGHT_API_PORT) {
  $env:HINDSIGHT_API_PORT = "8888"
}

Test-CodexAuth

$uvArgs = @("run", "--no-env-file", "--project", $ApiProject, "--extra", "local-onnx", "--extra", "embedded-db")
if ($NoSync) {
  $uvArgs += "--no-sync"
}
$uvArgs += @(
  "hindsight-api",
  "--host", $env:HINDSIGHT_API_HOST,
  "--port", $env:HINDSIGHT_API_PORT,
  "--log-level", $(if ($env:HINDSIGHT_API_LOG_LEVEL) { $env:HINDSIGHT_API_LOG_LEVEL } else { "info" })
)

Write-Host "Starting Hindsight with provider=$env:HINDSIGHT_API_LLM_PROVIDER model=$env:HINDSIGHT_API_LLM_MODEL"
Write-Host "API: http://$env:HINDSIGHT_API_HOST`:$env:HINDSIGHT_API_PORT"
Write-Host "Database: $env:HINDSIGHT_API_DATABASE_URL"

$RunCwd = Join-Path $env:TEMP "hindsight-run-cwd"
New-Item -ItemType Directory -Path $RunCwd -Force | Out-Null

# Hindsight loads .env from the current working directory and parents with
# override=True. Run from an empty temp directory so the explicit env above is
# authoritative, while uv still uses the project specified by --project.
Push-Location $RunCwd
try {
  & uv @uvArgs
  exit $LASTEXITCODE
}
finally {
  Pop-Location
}
