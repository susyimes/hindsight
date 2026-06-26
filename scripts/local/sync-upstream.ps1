param(
  [switch]$Push
)

$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Resolve-Path (Join-Path $ScriptDir "..\..")

Push-Location $RepoRoot
try {
  $dirty = git status --porcelain
  if ($dirty) {
    throw "Working tree is dirty. Commit or stash local changes before syncing upstream."
  }

  git fetch upstream
  git fetch origin
  git checkout main
  git rebase upstream/main

  if ($Push) {
    git push origin main
  }
}
finally {
  Pop-Location
}
