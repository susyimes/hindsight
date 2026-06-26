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
