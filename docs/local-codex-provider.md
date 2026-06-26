# Local Codex Provider Setup

This fork is configured for local Hindsight development with the `openai-codex`
provider. The provider uses Codex/ChatGPT OAuth credentials from
`CODEX_HOME\auth.json`; it does not use an OpenAI Platform API key.

## Files

- `.env`: local machine config, ignored by git.
- `.env.codex.example`: safe example config for this fork.
- `scripts/local/run-hindsight-codex.ps1`: starts the Hindsight API with the
  local Codex provider config.
- `scripts/local/test-hindsight-codex.ps1`: starts a temporary server and runs
  health, retain, recall, and reflect smoke checks.
- `scripts/local/sync-upstream.ps1`: rebases the fork onto upstream `main`.

## Start Hindsight

```powershell
cd C:\Users\svmes\Documents\Playground\hindsight
.\scripts\local\run-hindsight-codex.ps1
```

The default local URL is:

```text
http://127.0.0.1:8888
```

## Smoke Test

```powershell
cd C:\Users\svmes\Documents\Playground\hindsight
.\scripts\local\test-hindsight-codex.ps1
```

This uses port `8900`, creates a temporary memory bank, runs:

- `/health`
- `/v1/default/banks/{bank}/health/llm`
- retain
- recall
- reflect

Then it deletes the temporary bank and stops the server.

## Import Local memSu

The local memSu importer reads `C:\Users\svmes\.memsu` in read-only mode and
loads it through Hindsight's retain API. It does not write directly to the
Hindsight database.

Start Hindsight first:

```powershell
cd C:\Users\svmes\Documents\Playground\hindsight
.\scripts\local\run-hindsight-codex.ps1
```

Preview the core import:

```powershell
.\scripts\local\import-memsu-to-hindsight.ps1 -SkipEvents -DryRun -BatchSize 20
```

Import core memSu state and local files into the `memsu-self` bank:

```powershell
.\scripts\local\import-memsu-to-hindsight.ps1 -SkipEvents -AsyncMode -BatchSize 20 -WaitTimeout 7200
```

Preview and import the event ledger as smaller chronological evidence batches:

```powershell
.\scripts\local\import-memsu-to-hindsight.ps1 -OnlyEvents -DryRun -EventBatchSize 25 -BatchSize 4
.\scripts\local\import-memsu-to-hindsight.ps1 -OnlyEvents -AsyncMode -EventBatchSize 25 -BatchSize 4 -WaitTimeout 14400
```

The importer skips `backups`, `imports`, and `sync-bundle` file trees to avoid
duplicate historical payloads. Generated retain text is passed through a small
local redaction layer for common key/secret patterns before it is sent to
Hindsight.

## Sync From Upstream

```powershell
cd C:\Users\svmes\Documents\Playground\hindsight
.\scripts\local\sync-upstream.ps1
```

To update the GitHub fork after rebasing:

```powershell
.\scripts\local\sync-upstream.ps1 -Push
```

`upstream` is configured as fetch-only; pushes go to `origin`
(`susyimes/hindsight`).
