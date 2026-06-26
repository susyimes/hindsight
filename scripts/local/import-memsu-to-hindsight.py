from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


SKIP_DIRS = {"backups", "imports", "sync-bundle"}
SECRET_PATTERNS = [
    (
        re.compile(
            r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----",
            re.DOTALL,
        ),
        "<redacted-private-key>",
    ),
    (
        re.compile(r"(?i)\b(api[_-]?key|secret|token|password)\s*[:=]\s*([\"']?)[^\s\"']{8,}"),
        r"\1=<redacted>",
    ),
    (
        re.compile(r"(?<![A-Za-z0-9_])sk-[A-Za-z0-9_-]{16,}"),
        "<redacted-sk-token>",
    ),
]


@dataclass
class ImportItem:
    document_id: str
    content: str
    context: str
    tags: list[str]
    timestamp: str | None = None


def json_load(value: Any) -> Any:
    if value in (None, ""):
        return None
    if not isinstance(value, str):
        return value
    try:
        return json.loads(value)
    except Exception:
        return value


def compact_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2)


def redact_text(value: str) -> str:
    for pattern, replacement in SECRET_PATTERNS:
        value = pattern.sub(replacement, value)
    return value


def safe_doc_id(value: str) -> str:
    value = value.replace("\\", "/")
    value = re.sub(r"[^A-Za-z0-9_.:/@+-]+", "-", value)
    return value.strip("-")[:240]


def coerce_metadata(value: Any) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    out: dict[str, str] = {}
    for key, item in value.items():
        out[str(key)] = item if isinstance(item, str) else json.dumps(item, ensure_ascii=False, sort_keys=True)
    return out


def row_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {key: row[key] for key in row.keys()}


def row_markdown(title: str, row: dict[str, Any], *, body_keys: list[str]) -> str:
    body: list[str] = [f"# {title}", ""]
    body_values: dict[str, Any] = {}
    meta_values: dict[str, Any] = {}
    for key, value in row.items():
        parsed = json_load(value)
        if key in body_keys and parsed not in (None, ""):
            body_values[key] = parsed
        elif parsed not in (None, "", [], {}):
            meta_values[key] = parsed
    if meta_values:
        body.extend(["## Metadata", "", "```json", redact_text(compact_json(meta_values)), "```", ""])
    for key, value in body_values.items():
        body.extend([f"## {key}", ""])
        if isinstance(value, (dict, list)):
            body.extend(["```json", redact_text(compact_json(value)), "```", ""])
        else:
            body.extend([redact_text(str(value)), ""])
    return "\n".join(body).strip() + "\n"


def make_item(table: str, source_id: str, title: str, row: dict[str, Any], *, body_keys: list[str], tags: list[str]) -> ImportItem:
    timestamp = row.get("created_at") or row.get("timestamp") or row.get("updated_at")
    context = (
        f"Imported from memSu table `{table}`. Preserve memSu provenance and status. "
        "Pending candidates are pending evidence, not accepted facts."
    )
    status = row.get("status")
    all_tags = ["memsu-import", f"memsu-{table.replace('_', '-')}", *tags]
    if status:
        all_tags.append(f"memsu-status-{str(status).lower()}")
    return ImportItem(
        document_id=safe_doc_id(f"memsu:{table}:{source_id}"),
        content=row_markdown(title, row, body_keys=body_keys),
        context=context,
        tags=sorted(set(all_tags)),
        timestamp=str(timestamp) if timestamp else None,
    )


def load_sqlite_items(
    db_path: Path, *, include_events: bool, event_batch_size: int, only_events: bool = False
) -> list[ImportItem]:
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    items: list[ImportItem] = []

    table_specs = [
        ("memories", "item_id", "memSu accepted memory", ["content", "metadata", "source_event_ids"]),
        ("memory_candidates", "candidate_id", "memSu memory candidate", ["content", "reason", "metadata", "source_event_ids"]),
        ("delta_events", "delta_id", "memSu delta event", ["reason", "metadata"]),
        ("stable_intents", "intent_id", "memSu stable intent", ["statement", "context", "metadata", "source_refs"]),
        ("tradeoffs", "tradeoff_id", "memSu tradeoff", ["winner", "loser", "context", "metadata", "source_delta_refs"]),
        ("anti_rules", "anti_id", "memSu anti-rule", ["prohibition", "metadata", "source_refs"]),
        ("worklines", "workline_id", "memSu workline", ["title", "summary", "metadata", "evidence_ids_json"]),
        ("action_proposals", "proposal_id", "memSu action proposal", ["description", "reason", "metadata"]),
        ("advancement_opportunities", "opportunity_id", "memSu advancement opportunity", ["title", "description", "metadata"]),
        ("observation_snapshots", "snapshot_id", "memSu observation snapshot", ["current_picture_json", "known_json", "inferred_json", "unknown_json", "support_opportunity", "sources_json", "metadata"]),
        ("observation_findings", "finding_id", "memSu observation finding", ["claim", "metadata", "evidence_ids"]),
        ("policy_events", "policy_event_id", "memSu policy event", ["reason", "metadata"]),
        ("temporal_annotations", "annotation_id", "memSu temporal annotation", ["metadata", "evidence_refs"]),
    ]

    existing = {r["name"] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if not only_events:
        for table, id_key, label, body_keys in table_specs:
            if table not in existing:
                continue
            for row in con.execute(f'SELECT * FROM "{table}" ORDER BY rowid'):
                data = row_dict(row)
                source_id = str(data.get(id_key) or data.get("rowid") or len(items))
                title = f"{label}: {source_id}"
                items.append(make_item(table, source_id, title, data, body_keys=body_keys, tags=[]))

    if (include_events or only_events) and "events" in existing:
        batch: list[dict[str, Any]] = []
        batch_start = 0
        for idx, row in enumerate(con.execute('SELECT * FROM "events" ORDER BY timestamp, rowid'), start=1):
            if not batch:
                batch_start = idx
            batch.append(row_dict(row))
            if len(batch) >= event_batch_size:
                items.append(make_event_batch(batch, batch_start, idx))
                batch = []
        if batch:
            items.append(make_event_batch(batch, batch_start, batch_start + len(batch) - 1))

    return items


def make_event_batch(rows: list[dict[str, Any]], start: int, end: int) -> ImportItem:
    lines = [f"# memSu event ledger batch {start}-{end}", ""]
    lines.append("Imported from memSu `events`; preserve as chronological evidence, not as direct user preference unless the content explicitly says so.")
    lines.append("")
    for row in rows:
        event_id = row.get("event_id", "")
        lines.extend([f"## Event {event_id}", ""])
        meta = {k: json_load(v) for k, v in row.items() if k != "content" and v not in (None, "", [], {})}
        if meta:
            lines.extend(["```json", redact_text(compact_json(meta)), "```", ""])
        content = row.get("content") or ""
        if content:
            lines.extend([redact_text(str(content)), ""])
    return ImportItem(
        document_id=safe_doc_id(f"memsu:events:{start}-{end}"),
        content="\n".join(lines).strip() + "\n",
        context="Imported from memSu events ledger. Treat as evidence with provenance.",
        tags=["memsu-import", "memsu-events"],
    )


def load_file_items(home: Path, *, include_files: bool) -> list[ImportItem]:
    if not include_files:
        return []
    allowed_roots = ["observe", "advance", "inbox", "inspire.d"]
    root_files = ["AGENTS.md", "inspire.md", "policy.yaml", "tasks.md", "capabilities.json"]
    items: list[ImportItem] = []
    for rel in root_files:
        path = home / rel
        if path.exists() and path.is_file():
            items.append(file_item(home, path))
    for dirname in allowed_roots:
        root = home / dirname
        if not root.exists():
            continue
        for path in sorted(root.rglob("*")):
            if path.is_file():
                items.append(file_item(home, path))
    return items


def file_item(home: Path, path: Path) -> ImportItem:
    rel = path.relative_to(home).as_posix()
    text = path.read_text(encoding="utf-8", errors="replace")
    content = f"# memSu file: {rel}\n\n{redact_text(text.strip())}\n"
    tag_root = rel.split("/", 1)[0].replace(".", "-").lower()
    return ImportItem(
        document_id=safe_doc_id(f"memsu:file:{rel}"),
        content=content,
        context=f"Imported from local memSu file `{rel}`. Preserve provenance.",
        tags=["memsu-import", "memsu-file", f"memsu-file-{tag_root}"],
    )


def http_json(method: str, url: str, payload: dict[str, Any] | None = None, timeout: int = 120) -> dict[str, Any]:
    data = None
    headers = {"Accept": "application/json"}
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = Request(url, data=data, method=method, headers=headers)
    try:
        with urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            return json.loads(raw.decode("utf-8")) if raw else {}
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code} {url}: {detail}") from exc
    except URLError as exc:
        raise RuntimeError(f"Failed to connect to {url}: {exc}") from exc


def wait_health(base_url: str, timeout_s: int = 120) -> None:
    deadline = time.time() + timeout_s
    last = ""
    while time.time() < deadline:
        try:
            data = http_json("GET", f"{base_url}/health", timeout=5)
            if data.get("status") == "healthy":
                return
            last = str(data)
        except Exception as exc:
            last = str(exc)
        time.sleep(2)
    raise RuntimeError(f"Hindsight health did not become healthy: {last}")


def create_bank(base_url: str, bank_id: str) -> None:
    payload = {
        "name": "memSu self import",
        "reflect_mission": (
            "Use imported memSu evidence as provenance-rich local memory for the user's projects, preferences, "
            "will constraints, workflow history, and decision behavior. Do not claim pending candidates are accepted facts."
        ),
        "retain_mission": (
            "Extract durable, source-grounded facts from memSu import records. Preserve source ids, statuses, scopes, "
            "timestamps, decisions, preferences, anti-rules, tradeoffs, and project workflow facts. "
            "Treat pending candidates and proposals as pending evidence, not settled truth."
        ),
        "observations_mission": (
            "Consolidate memSu imports into stable observations about user preferences, project state, workflow behavior, "
            "risk boundaries, and memory migration provenance."
        ),
    }
    http_json("PUT", f"{base_url}/v1/default/banks/{bank_id}", payload, timeout=60)


def to_retain_payload(items: list[ImportItem], async_mode: bool) -> dict[str, Any]:
    return {
        "items": [
            {
                "content": item.content,
                "context": item.context,
                "document_id": item.document_id,
                "tags": item.tags,
                **({"timestamp": item.timestamp} if item.timestamp else {}),
            }
            for item in items
        ],
        "async": async_mode,
    }


def retain_batches(base_url: str, bank_id: str, items: list[ImportItem], *, batch_size: int, async_mode: bool, timeout: int) -> list[str]:
    op_ids: list[str] = []
    total = len(items)
    for idx in range(0, total, batch_size):
        batch = items[idx : idx + batch_size]
        payload = to_retain_payload(batch, async_mode)
        print(f"retain batch {idx // batch_size + 1}/{(total + batch_size - 1) // batch_size}: {len(batch)} docs", flush=True)
        resp = http_json("POST", f"{base_url}/v1/default/banks/{bank_id}/memories", payload, timeout=timeout)
        if async_mode:
            ids = resp.get("operation_ids") or ([resp.get("operation_id")] if resp.get("operation_id") else [])
            op_ids.extend([str(x) for x in ids if x])
    return op_ids


def wait_operations(base_url: str, bank_id: str, op_ids: list[str], timeout_s: int) -> dict[str, Any]:
    if not op_ids:
        return {"completed": 0, "failed": 0, "cancelled": 0}
    pending = set(op_ids)
    result = {"completed": 0, "failed": 0, "cancelled": 0}
    deadline = time.time() + timeout_s
    while pending and time.time() < deadline:
        for op_id in list(pending):
            status = http_json("GET", f"{base_url}/v1/default/banks/{bank_id}/operations/{op_id}", timeout=30)
            state = status.get("status")
            if state in {"completed", "not_found"}:
                result["completed"] += 1
                pending.remove(op_id)
            elif state in {"failed", "cancelled"}:
                result[state] += 1
                pending.remove(op_id)
                print(f"operation {op_id} ended with {state}: {status.get('error_message')}", file=sys.stderr, flush=True)
        if pending:
            print(f"waiting operations: {len(pending)} remaining", flush=True)
            time.sleep(5)
    result["remaining"] = len(pending)
    if pending:
        raise RuntimeError(f"Timed out waiting for {len(pending)} operations")
    return result


def recall_check(base_url: str, bank_id: str) -> dict[str, Any]:
    payload = {
        "query": "What does imported memSu say about the user's memory migration direction and Hindsight/openai-codex setup?",
        "budget": "low",
        "max_tokens": 2048,
        "trace": True,
        "tags": ["memsu-import"],
        "tags_match": "any_strict",
        "include": {"entities": None},
    }
    return http_json("POST", f"{base_url}/v1/default/banks/{bank_id}/memories/recall", payload, timeout=120)


def main() -> int:
    parser = argparse.ArgumentParser(description="Import local memSu data into Hindsight via retain API.")
    parser.add_argument("--memsu-home", default=str(Path.home() / ".memsu"))
    parser.add_argument("--base-url", default="http://127.0.0.1:8888")
    parser.add_argument("--bank-id", default="memsu-self")
    parser.add_argument("--batch-size", type=int, default=6)
    parser.add_argument("--event-batch-size", type=int, default=25)
    parser.add_argument("--timeout", type=int, default=300)
    parser.add_argument("--wait-timeout", type=int, default=3600)
    parser.add_argument("--async-mode", action="store_true")
    parser.add_argument("--skip-events", action="store_true")
    parser.add_argument("--skip-files", action="store_true")
    parser.add_argument("--only-events", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    home = Path(args.memsu_home).resolve()
    db_path = home / "memsu.db"
    if not db_path.exists():
        raise SystemExit(f"memSu database not found: {db_path}")

    if args.only_events and args.skip_events:
        raise SystemExit("--only-events cannot be combined with --skip-events")

    effective_include_files = not args.skip_files and not args.only_events
    sqlite_items = load_sqlite_items(
        db_path,
        include_events=not args.skip_events,
        event_batch_size=args.event_batch_size,
        only_events=args.only_events,
    )
    file_items = load_file_items(home, include_files=effective_include_files)
    items = sqlite_items + file_items

    summary = {
        "memsu_home": str(home),
        "bank_id": args.bank_id,
        "base_url": args.base_url,
        "items": len(items),
        "sqlite_items": len(sqlite_items),
        "file_items": len(file_items),
        "total_chars": sum(len(item.content) for item in items),
        "include_events": not args.skip_events,
        "include_files": effective_include_files,
        "only_events": args.only_events,
        "async_mode": args.async_mode,
    }
    print(json.dumps({"plan": summary}, ensure_ascii=False, indent=2), flush=True)
    if args.dry_run:
        return 0

    wait_health(args.base_url)
    create_bank(args.base_url, args.bank_id)
    op_ids = retain_batches(
        args.base_url,
        args.bank_id,
        items,
        batch_size=max(1, args.batch_size),
        async_mode=args.async_mode,
        timeout=args.timeout,
    )
    op_result = wait_operations(args.base_url, args.bank_id, op_ids, args.wait_timeout) if args.async_mode else {}
    recall = recall_check(args.base_url, args.bank_id)
    out = {
        "ok": True,
        "plan": summary,
        "operations": op_result,
        "recall_count": len(recall.get("results") or []),
        "recall_first": (recall.get("results") or [{}])[0].get("text") if recall.get("results") else None,
    }
    print(json.dumps(out, ensure_ascii=False, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
