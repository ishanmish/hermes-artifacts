#!/usr/bin/env python3
"""YouTube summary dashboard helper.

This helper keeps the static GitHub Pages dashboard operational:

1. `fetch URL` extracts a YouTube transcript and writes a transcript payload.
2. The agent summarizes that transcript with the stored JSON contract.
3. `add SUMMARY.json` validates and appends the summary to video/youtube-summary-data.json.

The script intentionally does not call an LLM itself. Hermes/the agent performs the
summary step, which keeps the summarization prompt editable and auditable.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parents[1]
DATA_FILE = ROOT / "video" / "youtube-summary-data.json"
MANIFEST = ROOT / "artifacts.json"
DASHBOARD_PATH = "video/youtube-summary-dashboard.html"
DASHBOARD_URL = "https://ishanmish.github.io/hermes-artifacts/video/youtube-summary-dashboard.html"

SUMMARY_PROMPT = """Video Summary Assistant: Highlight Insights, Takeaways, and Actionable Points

Use the transcript and metadata to produce ONE valid JSON object matching this schema:
{
  "id": "stable slug, preferably YYYY-MM-DD-videoid",
  "video_url": "canonical YouTube URL",
  "title": "video title if known, otherwise concise title from transcript",
  "channel": "channel name if known",
  "published_at": "YYYY-MM-DD or null",
  "summarized_at": "ISO timestamp",
  "transcript_source": "youtube-transcript-api / yt-dlp cookies / manual",
  "word_limit": 350,
  "tags": ["short lowercase tags"],
  "brief": "2-4 sentence executive summary",
  "key_insights": ["important ideas, mechanisms, numbers, arguments"],
  "key_takeaways": ["what the viewer should remember"],
  "actionable_points": ["specific things to do, test, avoid, or investigate"],
  "timestamped_highlights": [{"time":"MM:SS or HH:MM:SS", "note":"important moment"}],
  "brief_conclusion": "bottom-line conclusion",
  "notes": "limitations, missing transcript sections, uncertainty, or empty string"
}

Rules:
- Be transcript-backed. Do not invent facts.
- Capture all important insights and takeaways, not just a generic overview.
- Emphasize actionable points.
- Preserve important numbers, names, caveats, and causality.
- If the transcript is poor/missing context, say so in notes.
- Keep bullets concise and useful for later search.
"""

REQUIRED_FIELDS = {
    "id",
    "video_url",
    "title",
    "summarized_at",
    "brief",
    "key_insights",
    "key_takeaways",
    "actionable_points",
    "brief_conclusion",
}
LIST_FIELDS = {"tags", "key_insights", "key_takeaways", "actionable_points", "timestamped_highlights"}


@dataclass
class TranscriptSegment:
    start: float
    duration: float
    text: str


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        return default
    return json.loads(text)


def save_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def extract_video_id(value: str) -> str:
    value = value.strip()
    if re.fullmatch(r"[A-Za-z0-9_-]{11}", value):
        return value
    parsed = urlparse(value)
    host = parsed.netloc.lower().replace("www.", "")
    if host == "youtu.be":
        candidate = parsed.path.strip("/").split("/")[0]
        if re.fullmatch(r"[A-Za-z0-9_-]{11}", candidate):
            return candidate
    if "youtube.com" in host:
        query_id = parse_qs(parsed.query).get("v", [None])[0]
        if query_id and re.fullmatch(r"[A-Za-z0-9_-]{11}", query_id):
            return query_id
        parts = [p for p in parsed.path.split("/") if p]
        for marker in ("shorts", "embed", "live"):
            if marker in parts:
                idx = parts.index(marker)
                if idx + 1 < len(parts) and re.fullmatch(r"[A-Za-z0-9_-]{11}", parts[idx + 1]):
                    return parts[idx + 1]
    raise ValueError(f"Could not extract YouTube video id from: {value}")


def canonical_url(video_id: str) -> str:
    return f"https://www.youtube.com/watch?v={video_id}"


def fmt_time(seconds: float) -> str:
    seconds = max(0, int(seconds))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


def fetch_transcript(url_or_id: str, languages: list[str]) -> dict[str, Any]:
    try:
        from youtube_transcript_api import YouTubeTranscriptApi
    except ImportError as exc:  # pragma: no cover - environment dependent
        raise SystemExit(
            "Missing dependency: youtube-transcript-api. Install with `pip install youtube-transcript-api`."
        ) from exc

    video_id = extract_video_id(url_or_id)
    api = YouTubeTranscriptApi()
    transcript = None
    used_language = None
    errors: list[str] = []
    for lang in languages:
        try:
            transcript = api.fetch(video_id, languages=[lang])
            used_language = lang
            break
        except Exception as exc:  # noqa: BLE001 - library exposes several exception classes
            errors.append(f"{lang}: {exc}")
    if transcript is None:
        try:
            transcript = api.fetch(video_id)
            used_language = "auto"
        except Exception as exc:  # noqa: BLE001
            errors.append(f"auto: {exc}")
            raise RuntimeError("Transcript fetch failed. " + " | ".join(errors)) from exc

    segments = [
        TranscriptSegment(
            start=float(getattr(item, "start", item.get("start", 0.0) if isinstance(item, dict) else 0.0)),
            duration=float(getattr(item, "duration", item.get("duration", 0.0) if isinstance(item, dict) else 0.0)),
            text=str(getattr(item, "text", item.get("text", "") if isinstance(item, dict) else "")).replace("\n", " ").strip(),
        )
        for item in transcript
    ]
    text = " ".join(seg.text for seg in segments if seg.text)
    timestamped = [{"time": fmt_time(seg.start), "text": seg.text} for seg in segments if seg.text]
    return {
        "video_id": video_id,
        "video_url": canonical_url(video_id),
        "language": used_language,
        "transcript_source": "youtube-transcript-api",
        "fetched_at": now_iso(),
        "char_count": len(text),
        "segment_count": len(timestamped),
        "summary_prompt": SUMMARY_PROMPT,
        "transcript_text": text,
        "timestamped_transcript": timestamped,
    }


def validate_summary(summary: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    missing = sorted(field for field in REQUIRED_FIELDS if field not in summary)
    if missing:
        errors.append("missing required fields: " + ", ".join(missing))
    for field in LIST_FIELDS:
        if field in summary and not isinstance(summary[field], list):
            errors.append(f"{field} must be a list")
    if not str(summary.get("id", "")).strip():
        errors.append("id cannot be empty")
    if not str(summary.get("video_url", "")).startswith(("https://youtu.be/", "https://www.youtube.com/", "https://youtube.com/")):
        errors.append("video_url should be a YouTube URL")
    return errors


def normalize_summary(summary: dict[str, Any]) -> dict[str, Any]:
    out = dict(summary)
    out.setdefault("summarized_at", now_iso())
    out.setdefault("channel", "")
    out.setdefault("published_at", None)
    out.setdefault("transcript_source", "")
    out.setdefault("word_limit", None)
    out.setdefault("tags", [])
    out.setdefault("timestamped_highlights", [])
    out.setdefault("notes", "")
    for field in LIST_FIELDS:
        out[field] = out.get(field) or []
    return out


def upsert_summary(summary: dict[str, Any], *, replace: bool) -> tuple[str, int]:
    summary = normalize_summary(summary)
    errors = validate_summary(summary)
    if errors:
        raise ValueError("Invalid summary: " + "; ".join(errors))

    DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
    items = load_json(DATA_FILE, [])
    if not isinstance(items, list):
        raise ValueError(f"{DATA_FILE} must contain a JSON list")

    existing_idx = next((i for i, item in enumerate(items) if item.get("id") == summary["id"]), None)
    if existing_idx is not None:
        if not replace:
            raise ValueError(f"Summary id already exists: {summary['id']} (use --replace)")
        items[existing_idx] = summary
        action = "replaced"
    else:
        items.append(summary)
        action = "added"

    items.sort(key=lambda item: str(item.get("summarized_at") or item.get("published_at") or ""), reverse=True)
    save_json(DATA_FILE, items)
    touch_manifest()
    return action, len(items)


def touch_manifest() -> None:
    manifest = load_json(MANIFEST, [])
    if not isinstance(manifest, list):
        return
    changed = False
    for item in manifest:
        if item.get("path") == DASHBOARD_PATH or item.get("id") == "2026-05-27-youtube-summary-dashboard":
            item["updated_at"] = now_iso()
            changed = True
    if changed:
        save_json(MANIFEST, manifest)


def command_fetch(args: argparse.Namespace) -> int:
    payload = fetch_transcript(args.url, args.language.split(","))
    output = Path(args.output) if args.output else ROOT / "video" / "transcripts" / f"{payload['video_id']}.json"
    save_json(output, payload)
    print(f"Transcript written: {output}")
    print(f"Video: {payload['video_url']}")
    print(f"Segments: {payload['segment_count']} | chars: {payload['char_count']} | language: {payload['language']}")
    print("Next: summarize `transcript_text` with the embedded `summary_prompt`, then run:")
    print(f"  python3 scripts/youtube_summary_workflow.py add summary.json")
    return 0


def command_prompt(_: argparse.Namespace) -> int:
    print(SUMMARY_PROMPT)
    return 0


def command_add(args: argparse.Namespace) -> int:
    if args.json == "-":
        summary = json.load(sys.stdin)
    else:
        summary = load_json(Path(args.json), {})
    action, total = upsert_summary(summary, replace=args.replace)
    print(f"Summary {action}. Dashboard entries: {total}")
    print(DASHBOARD_URL)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="YouTube summary dashboard workflow")
    sub = parser.add_subparsers(dest="command", required=True)

    fetch = sub.add_parser("fetch", help="Fetch transcript payload for a YouTube URL")
    fetch.add_argument("url", help="YouTube URL or video id")
    fetch.add_argument("--language", default="en,hi", help="Comma-separated language fallback list, default: en,hi")
    fetch.add_argument("--output", help="Output JSON path; default video/transcripts/<id>.json")
    fetch.set_defaults(func=command_fetch)

    prompt = sub.add_parser("prompt", help="Print the stored summarization prompt / JSON contract")
    prompt.set_defaults(func=command_prompt)

    add = sub.add_parser("add", help="Validate and append/replace one summary JSON object")
    add.add_argument("json", help="Summary JSON file, or '-' for stdin")
    add.add_argument("--replace", action="store_true", help="Replace an existing entry with the same id")
    add.set_defaults(func=command_add)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args) or 0)
    except Exception as exc:  # noqa: BLE001 - command line error boundary
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
