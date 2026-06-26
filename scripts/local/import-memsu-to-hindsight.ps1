param(
  [string]$MemsuHome = "C:\Users\svmes\.memsu",
  [string]$BaseUrl = "http://127.0.0.1:8888",
  [string]$BankId = "memsu-self",
  [int]$BatchSize = 6,
  [int]$EventBatchSize = 25,
  [int]$Timeout = 300,
  [int]$WaitTimeout = 3600,
  [switch]$AsyncMode,
  [switch]$SkipEvents,
  [switch]$SkipFiles,
  [switch]$OnlyEvents,
  [switch]$DryRun
)

$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Resolve-Path (Join-Path $ScriptDir "..\..")
$ApiProject = Join-Path $RepoRoot "hindsight-api-slim"
$Importer = Join-Path $ScriptDir "import-memsu-to-hindsight.py"

$argsList = @(
  "run",
  "--no-env-file",
  "--project",
  $ApiProject,
  "python",
  $Importer,
  "--memsu-home",
  $MemsuHome,
  "--base-url",
  $BaseUrl,
  "--bank-id",
  $BankId,
  "--batch-size",
  "$BatchSize",
  "--event-batch-size",
  "$EventBatchSize",
  "--timeout",
  "$Timeout",
  "--wait-timeout",
  "$WaitTimeout"
)

if ($AsyncMode) { $argsList += "--async-mode" }
if ($SkipEvents) { $argsList += "--skip-events" }
if ($SkipFiles) { $argsList += "--skip-files" }
if ($OnlyEvents) { $argsList += "--only-events" }
if ($DryRun) { $argsList += "--dry-run" }

& uv @argsList
exit $LASTEXITCODE
