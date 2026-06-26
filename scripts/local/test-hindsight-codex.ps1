param(
  [string]$EnvFile = "",
  [int]$Port = 8900,
  [switch]$KeepServer
)

$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Resolve-Path (Join-Path $ScriptDir "..\..")
$RunScript = Join-Path $ScriptDir "run-hindsight-codex.ps1"
if (-not $EnvFile) {
  $EnvFile = Join-Path $RepoRoot ".env"
}

function Invoke-JsonPost {
  param([string]$Uri, [hashtable]$Body, [int]$TimeoutSec = 180)
  $json = $Body | ConvertTo-Json -Depth 30 -Compress
  Invoke-RestMethod -Method Post -Uri $Uri -ContentType "application/json" -Body $json -TimeoutSec $TimeoutSec
}

function Invoke-JsonPut {
  param([string]$Uri, [hashtable]$Body, [int]$TimeoutSec = 60)
  $json = $Body | ConvertTo-Json -Depth 30 -Compress
  Invoke-RestMethod -Method Put -Uri $Uri -ContentType "application/json" -Body $json -TimeoutSec $TimeoutSec
}

$stamp = Get-Date -Format "yyyyMMddHHmmss"
$base = "http://127.0.0.1:$Port"
$bank = "codex-smoke-$stamp"
$dbName = "hindsight-codex-smoke-$stamp"
$databaseUrl = "pg0://$dbName"
$logDir = Join-Path $env:TEMP "hindsight-codex-smoke-$stamp"
New-Item -ItemType Directory -Path $logDir -Force | Out-Null
$outLog = Join-Path $logDir "server.out.log"
$errLog = Join-Path $logDir "server.err.log"

$proc = $null
$createdBank = $false
$results = [ordered]@{
  base_url = $base
  bank = $bank
  database_url = $databaseUrl
  log_dir = $logDir
}

function Stop-ListeningPort {
  param([int]$TargetPort)
  $listeners = Get-NetTCPConnection -LocalPort $TargetPort -State Listen -ErrorAction SilentlyContinue
  if (-not $listeners) {
    return
  }
  $ownerIds = $listeners | Select-Object -ExpandProperty OwningProcess -Unique
  foreach ($ownerId in $ownerIds) {
    Stop-Process -Id $ownerId -Force -ErrorAction SilentlyContinue
  }
}

function Stop-Pg0Instance {
  param([string]$InstanceName)
  $pg0Root = Join-Path $env:USERPROFILE ".pg0"
  $dataDir = Join-Path $pg0Root "instances\$InstanceName\data"
  $pgctl = Get-ChildItem -LiteralPath (Join-Path $pg0Root "installation") -Directory -ErrorAction SilentlyContinue |
    Sort-Object Name -Descending |
    ForEach-Object { Join-Path $_.FullName "bin\pg_ctl.exe" } |
    Where-Object { Test-Path -LiteralPath $_ } |
    Select-Object -First 1
  if ($pgctl -and (Test-Path -LiteralPath $dataDir)) {
    & $pgctl stop -D $dataDir -m fast | Out-Null
  }
}

try {
  $args = @(
    "-NoProfile",
    "-ExecutionPolicy",
    "Bypass",
    "-File",
    $RunScript,
    "-EnvFile",
    $EnvFile,
    "-Port",
    "$Port",
    "-DatabaseUrl",
    $databaseUrl
  )
  $proc = Start-Process -FilePath "powershell.exe" -ArgumentList $args -WorkingDirectory $RepoRoot -PassThru -WindowStyle Hidden -RedirectStandardOutput $outLog -RedirectStandardError $errLog
  $results.server_pid = $proc.Id

  $healthy = $false
  $lastError = $null
  $start = Get-Date
  for ($i = 0; $i -lt 90; $i++) {
    if ($proc.HasExited) {
      throw "server_exited_early code=$($proc.ExitCode)"
    }
    try {
      $health = Invoke-RestMethod -Method Get -Uri "$base/health" -TimeoutSec 5
      if ($health.status -eq "healthy") {
        $healthy = $true
        break
      }
      $lastError = "status=$($health.status)"
    }
    catch {
      $lastError = $_.Exception.Message
    }
    Start-Sleep -Seconds 2
    $proc.Refresh()
  }
  if (-not $healthy) {
    throw "server_not_healthy last=$lastError"
  }
  $results.server_start_seconds = [math]::Round(((Get-Date) - $start).TotalSeconds, 3)

  $bankResp = Invoke-JsonPut "$base/v1/default/banks/$bank" @{
    name = "Codex smoke test bank"
    reflect_mission = "Answer briefly from retained smoke-test memories."
    retain_mission = "Extract concrete smoke-test facts and preferences."
  } 60
  $createdBank = $true
  $results.bank_id = $bankResp.bank_id

  $t = Get-Date
  $llm = Invoke-JsonPost "$base/v1/default/banks/$bank/health/llm" @{} 240
  $results.llm_health_seconds = [math]::Round(((Get-Date) - $t).TotalSeconds, 3)
  $results.llm_health = @($llm.operations | ForEach-Object {
    @{ operation = $_.operation; ok = $_.ok; status = $_.status; latency_ms = $_.latency_ms }
  })

  $t = Get-Date
  $retain = Invoke-JsonPost "$base/v1/default/banks/$bank/memories" @{
    items = @(@{
      content = "Smoke test fact: Hindsight server should use the openai-codex provider and share Codex OAuth credentials with OpenClaw."
      context = "codex provider smoke test"
      document_id = "doc-$bank"
      tags = @("smoke", "openai-codex")
    })
    async = $false
  } 300
  $results.retain_seconds = [math]::Round(((Get-Date) - $t).TotalSeconds, 3)
  $results.retain = @{ success = $retain.success; items_count = $retain.items_count; total_tokens = $retain.usage.total_tokens }

  $t = Get-Date
  $recall = Invoke-JsonPost "$base/v1/default/banks/$bank/memories/recall" @{
    query = "Which provider should Hindsight server use?"
    budget = "low"
    max_tokens = 1024
    trace = $true
    include = @{ entities = $null }
    tags = @("openai-codex")
    tags_match = "any_strict"
  } 120
  $results.recall_seconds = [math]::Round(((Get-Date) - $t).TotalSeconds, 3)
  $results.recall_count = @($recall.results).Count
  $results.recall_first = if (@($recall.results).Count -gt 0) { @($recall.results)[0].text } else { $null }

  $t = Get-Date
  $reflect = Invoke-JsonPost "$base/v1/default/banks/$bank/reflect" @{
    query = "For this smoke test, should Hindsight server use openai-codex or Ark? Answer one sentence."
    budget = "low"
    max_tokens = 512
    include = @{ facts = @{}; tool_calls = @{ output = $false } }
    tags = @("openai-codex")
    tags_match = "any_strict"
  } 300
  $results.reflect_seconds = [math]::Round(((Get-Date) - $t).TotalSeconds, 3)
  $results.reflect_text = $reflect.text
  $results.result = "success"
}
catch {
  $results.result = "failed"
  $results.error = $_.Exception.Message
  $results.server_err_tail = if (Test-Path -LiteralPath $errLog) { (Get-Content -LiteralPath $errLog -Tail 80) -join "`n" } else { "" }
  $results.server_out_tail = if (Test-Path -LiteralPath $outLog) { (Get-Content -LiteralPath $outLog -Tail 80) -join "`n" } else { "" }
}
finally {
  if ($createdBank) {
    try {
      Invoke-RestMethod -Method Delete -Uri "$base/v1/default/banks/$bank" -TimeoutSec 60 | Out-Null
      $results.bank_delete = "ok"
    }
    catch {
      $results.bank_delete = "failed:$($_.Exception.Message)"
    }
  }
  if ($proc -and -not $proc.HasExited -and -not $KeepServer) {
    Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue
    $results.server_stop = "ok"
  }
  if (-not $KeepServer) {
    Stop-ListeningPort -TargetPort $Port
    Stop-Pg0Instance -InstanceName $dbName
  }
  Start-Sleep -Seconds 2
  $listener = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
  $results.port_after_cleanup = if ($listener) { "listening pid=$($listener.OwningProcess -join ',')" } else { "free" }
}

Write-Output ($results | ConvertTo-Json -Depth 30)
if ($results.result -ne "success") {
  exit 1
}
