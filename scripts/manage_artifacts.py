#!/usr/bin/env python3
"""Manage Hermes artifact retention.

The hub is hosted on static GitHub Pages, so temp/non-temp state lives in
artifacts.json. This script is used by GitHub Actions to remove expired temp
entries and their artifact files from the repo.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "artifacts.json"


def parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    value = value.replace("Z", "+00:00")
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def is_temp(artifact: dict[str, Any]) -> bool:
    return bool(artifact.get("temp")) or bool(artifact.get("expires_at")) or (
        artifact.get("temp") is not False and artifact.get("category") == "temp"
    )


def load_manifest() -> list[dict[str, Any]]:
    return json.loads(MANIFEST.read_text(encoding="utf-8"))


def save_manifest(items: list[dict[str, Any]]) -> None:
    MANIFEST.write_text(json.dumps(items, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def safe_repo_path(relative_path: str | None) -> Path | None:
    if not relative_path:
        return None
    target = (ROOT / relative_path).resolve()
    if ROOT not in target.parents and target != ROOT:
        raise ValueError(f"Refusing to delete path outside repo: {relative_path}")
    return target


def removal_summary(item: dict[str, Any]) -> dict[str, str]:
    return {
        "id": str(item.get("id", "")),
        "title": str(item.get("title", "")),
        "path": str(item.get("path", "")),
    }


def delete_artifact(artifact_id: str, dry_run: bool = False) -> dict[str, str]:
    """Remove one artifact from the manifest and delete its file."""
    items = load_manifest()
    keep: list[dict[str, Any]] = []
    removed_item: dict[str, Any] | None = None

    for item in items:
        if item.get("id") == artifact_id:
            removed_item = item
        else:
            keep.append(item)

    if removed_item is None:
        raise KeyError(f"Artifact not found: {artifact_id}")

    path = safe_repo_path(removed_item.get("path"))
    if path and path.exists() and path.is_file() and not dry_run:
        path.unlink()
    if not dry_run:
        save_manifest(keep)
    return removal_summary(removed_item)


def prune(now: datetime | None = None, dry_run: bool = False) -> list[dict[str, str]]:
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    items = load_manifest()
    keep: list[dict[str, Any]] = []
    removed: list[dict[str, str]] = []

    for item in items:
        expires_at = parse_dt(item.get("expires_at"))
        if is_temp(item) and expires_at and expires_at <= now:
            path = safe_repo_path(item.get("path"))
            summary = removal_summary(item)
            summary["expires_at"] = item.get("expires_at", "")
            removed.append(summary)
            if path and path.exists() and path.is_file() and not dry_run:
                path.unlink()
            continue
        keep.append(item)

    if removed and not dry_run:
        save_manifest(keep)
    return removed


def main() -> int:
    parser = argparse.ArgumentParser(description="Manage Hermes artifact retention")
    parser.add_argument("--dry-run", action="store_true", help="Print what would be deleted without changing files")
    parser.add_argument("--now", help="Override current time as ISO-8601 for tests/manual cleanup")
    parser.add_argument("--delete-id", help="Delete one artifact by id, including its file")
    args = parser.parse_args()

    if args.delete_id:
        try:
            removed_one = delete_artifact(args.delete_id, dry_run=args.dry_run)
        except KeyError as exc:
            print(str(exc))
            return 1
        print(f"Deleted artifact: {removed_one['id']} | {removed_one['path']}")
        if args.dry_run:
            print("Dry run only; no files changed.")
        return 0

    now = parse_dt(args.now) if args.now else None
    removed = prune(now=now, dry_run=args.dry_run)
    if not removed:
        print("No expired temp artifacts.")
        return 0
    print(f"Expired temp artifacts: {len(removed)}")
    for item in removed:
        print(f"- {item['id']} | {item['path']} | expired {item['expires_at']}")
    if args.dry_run:
        print("Dry run only; no files changed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
