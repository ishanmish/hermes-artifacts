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
import os
import re
import shlex
import shutil
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, quote, urlparse
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
DATA_FILE = ROOT / "video" / "youtube-summary-data.json"
MANIFEST = ROOT / "artifacts.json"
DASHBOARD_PATH = "video/youtube-summary-dashboard.html"
DASHBOARD_URL = "https://ishanmish.github.io/hermes-artifacts/video/youtube-summary-dashboard.html"
DEFAULT_SERVICE_HOST = "127.0.0.1"
DEFAULT_SERVICE_PORT = 8765
DEFAULT_WORD_LIMIT = 350

SUMMARY_PROMPT = """# Memory-Optimized YouTube Video Summarizer Prompt

You are not a normal summarizer.

Your goal is to convert the YouTube video into a HIGH-RETENTION KNOWLEDGE DOCUMENT optimized for:

- Long-term memory
- Fast revision
- Conceptual clarity
- Recall under pressure
- Understanding instead of passive reading

The output should feel like elite study notes, compressed wisdom, mental models, revision sheets, and insight maps.

Do not create generic summaries. Extract only information that changes how the viewer thinks, contains actionable insights, explains important mechanisms, contains counterintuitive ideas, contains principles/frameworks/heuristics/systems/strategies/rules, or is likely to be forgotten unless structured properly.

Ignore filler, repetition, storytelling fluff, sponsor segments, transitions, and motivational padding.

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
  "notes": "limitations, missing transcript sections, uncertainty, or empty string",
  "memory_optimized": {
    "one_sentence_core_thesis": "one powerful sentence capturing the central idea, main argument, and deepest insight",
    "most_important_ideas": [
      {
        "title": "short memorable title",
        "idea": "clear concise explanation",
        "why_it_matters": "real-world importance",
        "example": "practical example from business, life, psychology, investing, history, etc.",
        "memory_hook": "memorable analogy, visual image, or phrase",
        "actionable_takeaway": "what someone should do differently"
      }
    ],
    "mental_models": [
      {
        "name": "framework, system, heuristic, checklist, or model",
        "explanation": "what it means",
        "when_to_use": "best use case",
        "when_not_to_use": "where it misleads or overreaches"
      }
    ],
    "counterintuitive_insights": [
      {
        "common_belief": "what people normally believe",
        "video_argument": "what the video argues instead",
        "why_it_matters": "why the reversal matters"
      }
    ],
    "key_quotes": [
      {
        "quote": "extremely memorable, high-signal, perspective-shifting line",
        "meaning": "simple-language meaning"
      }
    ],
    "facts_data_statistics": ["important numbers, studies, statistics, events, findings, metrics, or experiments"],
    "mistakes_misunderstandings": [
      {
        "mistake": "common mistake",
        "why_people_make_it": "why people make it",
        "correction": "better understanding or action"
      }
    ],
    "compression_layer": ["10-20 high-density one-line bullets for sub-2-minute revision"],
    "flashcards": [
      {
        "question": "understanding-focused retrieval question",
        "answer": "concise answer"
      }
    ],
    "final_synthesis": {
      "deepest_lesson": "deepest lesson from the video",
      "how_to_change_thinking_or_action": "how someone should think or act differently",
      "three_takeaways": ["the 3 most important takeaways overall"]
    }
  }
}

Rules:
- Be transcript-backed. Do not invent facts.
- Fill both the legacy dashboard fields and the memory_optimized object.
- For most_important_ideas, include 5-15 ideas when the transcript supports them.
- For flashcards, generate at least 15 Q/A pairs when the transcript supports them.
- Prefer insight density over length.
- Use structure aggressively and make the document easy to revisit months later.
- Optimize for memory and understanding, not completeness.
- Merge overlapping ideas intelligently.
- Highlight causal relationships and first principles.
- Whenever possible, connect ideas into a coherent mental map.
- Preserve important numbers, names, caveats, and causality.
- If the transcript is poor/missing context, say so in notes.
- Keep bullets concise and useful for later search and revision.
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


class GitHubAPIError(RuntimeError):
    def __init__(self, message: str, *, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


def _github_repo(repo: str | None = None) -> str:
    value = repo or os.getenv("GITHUB_REPOSITORY") or os.getenv("GITHUB_REPO") or "ishanmish/hermes-artifacts"
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", value):
        raise ValueError("GitHub repo must use owner/repo format")
    return value


def _github_token(token: str | None = None) -> str:
    value = token or os.getenv("GITHUB_TOKEN") or os.getenv("GH_TOKEN")
    if not value:
        raise ValueError("GitHub token missing. Set GITHUB_TOKEN or GH_TOKEN.")
    return value


def _github_branch(branch: str | None = None) -> str:
    return branch or os.getenv("GITHUB_BRANCH") or os.getenv("GITHUB_PAGES_BRANCH") or "main"


def _safe_markdown_path(path: str) -> str:
    value = path.strip().lstrip("/")
    if not value:
        raise ValueError("Markdown path is required")
    parts = value.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise ValueError("Markdown path must be a safe repository-relative path")
    if not value.lower().endswith((".md", ".markdown")):
        raise ValueError("Only markdown files can be deleted")
    return value


def _github_request(method: str, url: str, *, token: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request = Request(
        url,
        data=data,
        method=method,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "User-Agent": "hermes-artifacts-youtube-summary-helper",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    try:
        with urlopen(request, timeout=30) as response:  # noqa: S310 - URL is GitHub API or operator-supplied API base
            body = response.read().decode("utf-8")
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        message = body
        try:
            parsed = json.loads(body)
            if isinstance(parsed, dict):
                message = str(parsed.get("message") or body)
        except json.JSONDecodeError:
            pass
        raise GitHubAPIError(message, status=exc.code) from exc
    except URLError as exc:
        raise GitHubAPIError(str(exc.reason)) from exc
    if not body.strip():
        return {}
    parsed = json.loads(body)
    if not isinstance(parsed, dict):
        raise GitHubAPIError("GitHub API returned a non-object response")
    return parsed


def delete_github_markdown_file(
    file_path: str,
    *,
    repo: str | None = None,
    token: str | None = None,
    branch: str | None = None,
    message: str | None = None,
) -> dict[str, Any]:
    safe_path = _safe_markdown_path(file_path)
    resolved_repo = _github_repo(repo)
    resolved_token = _github_token(token)
    resolved_branch = _github_branch(branch)
    api_base = os.getenv("GITHUB_API_URL", "https://api.github.com").rstrip("/")
    contents_url = f"{api_base}/repos/{resolved_repo}/contents/{quote(safe_path, safe='/')}"
    try:
        current = _github_request("GET", f"{contents_url}?ref={quote(resolved_branch, safe='')}", token=resolved_token)
    except GitHubAPIError as exc:
        if exc.status == 404:
            return {
                "ok": True,
                "deleted": False,
                "already_missing": True,
                "path": safe_path,
                "repo": resolved_repo,
                "branch": resolved_branch,
                "commit_sha": None,
            }
        raise
    sha = current.get("sha")
    if not isinstance(sha, str) or not sha:
        raise GitHubAPIError("GitHub content response did not include a file sha")
    try:
        result = _github_request(
            "DELETE",
            contents_url,
            token=resolved_token,
            payload={
                "message": message or f"Delete {safe_path}",
                "sha": sha,
                "branch": resolved_branch,
            },
        )
    except GitHubAPIError as exc:
        if exc.status == 404:
            return {
                "ok": True,
                "deleted": False,
                "already_missing": True,
                "path": safe_path,
                "repo": resolved_repo,
                "branch": resolved_branch,
                "commit_sha": None,
            }
        raise
    commit_value = result.get("commit")
    commit = commit_value if isinstance(commit_value, dict) else {}
    return {
        "ok": True,
        "deleted": True,
        "already_missing": False,
        "path": safe_path,
        "repo": resolved_repo,
        "branch": resolved_branch,
        "commit_sha": commit.get("sha"),
    }


def _summary_markdown_path(summary: dict[str, Any]) -> str | None:
    for key in ("markdown_path", "github_path", "file_path", "path"):
        value = summary.get(key)
        if isinstance(value, str) and value.strip().lower().endswith((".md", ".markdown")):
            return value
    return None


def delete_summary(
    post_id: str,
    *,
    file_path: str | None = None,
    repo: str | None = None,
    token: str | None = None,
    branch: str | None = None,
    message: str | None = None,
) -> dict[str, Any]:
    items = load_json(DATA_FILE, [])
    if not isinstance(items, list):
        raise ValueError(f"{DATA_FILE} must contain a JSON list")
    idx = next((i for i, item in enumerate(items) if isinstance(item, dict) and item.get("id") == post_id), None)
    if idx is None:
        github_result = None
        if file_path:
            github_result = delete_github_markdown_file(file_path, repo=repo, token=token, branch=branch, message=message)
        return {"ok": True, "deleted": False, "already_missing": True, "removed_local": False, "summary": None, "github": github_result}
    summary = dict(items[idx])
    markdown_path = file_path or _summary_markdown_path(summary)
    github_result = None
    if markdown_path:
        github_result = delete_github_markdown_file(markdown_path, repo=repo, token=token, branch=branch, message=message)
    del items[idx]
    save_json(DATA_FILE, items)
    touch_manifest()
    return {
        "ok": True,
        "deleted": bool(github_result.get("deleted")) if github_result else True,
        "already_missing": bool(github_result.get("already_missing")) if github_result else False,
        "removed_local": True,
        "summary": summary,
        "github": github_result,
        "items": items,
    }


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


def _memory_item_text(item: str) -> str:
    return re.sub(r"\s+", " ", str(item).strip())


def _memory_aid_items(summary: dict[str, Any]) -> list[str]:
    seen: set[str] = set()
    items: list[str] = []
    for field, limit in (("key_insights", 2), ("key_takeaways", 1), ("actionable_points", 1)):
        values = summary.get(field) or []
        if not isinstance(values, list):
            continue
        for value in values[:limit]:
            text = _memory_item_text(value)
            key = text.casefold()
            if text and key not in seen:
                seen.add(key)
                items.append(text)
    return items


def _leading_word(value: str) -> str:
    words = re.findall(r"[A-Za-z][A-Za-z0-9']*", value)
    stopwords = {"a", "an", "and", "the", "this", "that", "what", "why", "how", "review"}
    for word in words:
        if word.lower() not in stopwords:
            return word[:1].upper() + word[1:].lower()
    return "Point"


def _prompt_subject(value: str) -> str:
    text = _memory_item_text(value).rstrip(".?!")
    if not text:
        return "this point"
    return text[:1].lower() + text[1:]


def _first_sentence(value: str) -> str:
    text = _memory_item_text(value)
    if not text:
        return ""
    match = re.match(r"(.+?[.!?])(?:\s|$)", text)
    return match.group(1).strip() if match else text


def _summary_list(summary: dict[str, Any], field: str) -> list[str]:
    values = summary.get(field) or []
    if not isinstance(values, list):
        return []
    return [_memory_item_text(value) for value in values if _memory_item_text(value)]


def _unique_memory_lines(*groups: list[str], limit: int | None = None) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for group in groups:
        for value in group:
            text = _memory_item_text(value)
            key = text.casefold()
            if text and key not in seen:
                seen.add(key)
                out.append(text)
                if limit is not None and len(out) >= limit:
                    return out
    return out


def _normalize_string_list(value: Any, *, fallback: list[str] | None = None, limit: int | None = None) -> list[str]:
    values = value if isinstance(value, list) else fallback or []
    normalized = [_memory_item_text(item) for item in values if _memory_item_text(item)]
    return normalized[:limit] if limit is not None else normalized


def _normalize_dict_list(value: Any, fields: tuple[str, ...], *, fallback: list[dict[str, str]] | None = None) -> list[dict[str, str]]:
    values = value if isinstance(value, list) else fallback or []
    out: list[dict[str, str]] = []
    for item in values:
        if isinstance(item, dict):
            normalized = {field: _memory_item_text(item.get(field, "")) for field in fields}
        else:
            normalized = {field: "" for field in fields}
            normalized[fields[0]] = _memory_item_text(item)
        if any(normalized.values()):
            out.append(normalized)
    return out


def _legacy_memory_optimized(summary: dict[str, Any]) -> dict[str, Any]:
    insights = _summary_list(summary, "key_insights")
    takeaways = _summary_list(summary, "key_takeaways")
    actions = _summary_list(summary, "actionable_points")
    brief = str(summary.get("brief") or "")
    conclusion = str(summary.get("brief_conclusion") or "")
    ideas: list[dict[str, str]] = []
    for idx, insight in enumerate(insights[:15]):
        ideas.append(
            {
                "title": _leading_word(insight),
                "idea": insight,
                "why_it_matters": "",
                "example": "",
                "memory_hook": "",
                "actionable_takeaway": actions[idx] if idx < len(actions) else "",
            }
        )
    return {
        "one_sentence_core_thesis": _first_sentence(brief) or _first_sentence(conclusion),
        "most_important_ideas": ideas,
        "mental_models": [],
        "counterintuitive_insights": [],
        "key_quotes": [],
        "facts_data_statistics": [],
        "mistakes_misunderstandings": [],
        "compression_layer": _unique_memory_lines(insights, takeaways, actions, limit=20),
        "flashcards": [
            {
                "question": f"What should you remember about {_prompt_subject(item)}?",
                "answer": item,
            }
            for item in takeaways[:15]
        ],
        "final_synthesis": {
            "deepest_lesson": _memory_item_text(conclusion) or _first_sentence(brief),
            "how_to_change_thinking_or_action": actions[0] if actions else "",
            "three_takeaways": (takeaways or insights)[:3],
        },
    }


def _normalize_final_synthesis(value: Any, fallback: dict[str, Any]) -> dict[str, Any]:
    raw = value if isinstance(value, dict) else {}
    return {
        "deepest_lesson": _memory_item_text(raw.get("deepest_lesson") or fallback.get("deepest_lesson") or ""),
        "how_to_change_thinking_or_action": _memory_item_text(
            raw.get("how_to_change_thinking_or_action") or fallback.get("how_to_change_thinking_or_action") or ""
        ),
        "three_takeaways": _normalize_string_list(raw.get("three_takeaways"), fallback=fallback.get("three_takeaways") or [], limit=3),
    }


def _normalize_memory_optimized(summary: dict[str, Any]) -> dict[str, Any]:
    fallback = _legacy_memory_optimized(summary)
    raw = summary.get("memory_optimized")
    if not isinstance(raw, dict):
        raw = {}
    return {
        "one_sentence_core_thesis": _memory_item_text(
            raw.get("one_sentence_core_thesis") or fallback["one_sentence_core_thesis"]
        ),
        "most_important_ideas": _normalize_dict_list(
            raw.get("most_important_ideas"),
            ("title", "idea", "why_it_matters", "example", "memory_hook", "actionable_takeaway"),
            fallback=fallback["most_important_ideas"],
        ),
        "mental_models": _normalize_dict_list(
            raw.get("mental_models"),
            ("name", "explanation", "when_to_use", "when_not_to_use"),
            fallback=fallback["mental_models"],
        ),
        "counterintuitive_insights": _normalize_dict_list(
            raw.get("counterintuitive_insights"),
            ("common_belief", "video_argument", "why_it_matters"),
            fallback=fallback["counterintuitive_insights"],
        ),
        "key_quotes": _normalize_dict_list(
            raw.get("key_quotes"),
            ("quote", "meaning"),
            fallback=fallback["key_quotes"],
        ),
        "facts_data_statistics": _normalize_string_list(
            raw.get("facts_data_statistics"),
            fallback=fallback["facts_data_statistics"],
        ),
        "mistakes_misunderstandings": _normalize_dict_list(
            raw.get("mistakes_misunderstandings"),
            ("mistake", "why_people_make_it", "correction"),
            fallback=fallback["mistakes_misunderstandings"],
        ),
        "compression_layer": _normalize_string_list(
            raw.get("compression_layer"),
            fallback=fallback["compression_layer"],
            limit=20,
        ),
        "flashcards": _normalize_dict_list(
            raw.get("flashcards"),
            ("question", "answer"),
            fallback=fallback["flashcards"],
        ),
        "final_synthesis": _normalize_final_synthesis(raw.get("final_synthesis"), fallback["final_synthesis"]),
    }


def _generated_memory_aids(summary: dict[str, Any]) -> list[dict[str, Any]]:
    items = _memory_aid_items(summary)
    if not items:
        return []
    title = str(summary.get("title") or "Concept Map")
    words = [_leading_word(item) for item in items]
    mnemonic = f"{'-'.join(word[0].upper() for word in words)}: {'; '.join(words)}"
    return [
        {
            "type": "concept_map",
            "title": "Concept Map",
            "center": title,
            "items": items,
        },
        {
            "type": "mnemonic",
            "title": "Mnemonic",
            "items": [mnemonic],
        },
        {
            "type": "recall_prompts",
            "title": "Recall Prompts",
            "items": [f"What does the video say about {_prompt_subject(item)}?" for item in items],
        },
    ]


def _normalize_memory_aids(summary: dict[str, Any]) -> list[dict[str, Any]]:
    raw = summary.get("memory_aids")
    if not raw:
        return _generated_memory_aids(summary)
    if not isinstance(raw, list):
        return []
    aids: list[dict[str, Any]] = []
    for aid in raw:
        if not isinstance(aid, dict):
            continue
        normalized = dict(aid)
        normalized["type"] = str(normalized.get("type") or "note")
        normalized["title"] = str(normalized.get("title") or normalized["type"].replace("_", " ").title())
        items = normalized.get("items") or []
        normalized["items"] = [_memory_item_text(item) for item in items if _memory_item_text(item)] if isinstance(items, list) else []
        if normalized["type"] == "concept_map":
            normalized.setdefault("center", str(summary.get("title") or "Concept Map"))
        asset_path = normalized.get("asset_path")
        if isinstance(asset_path, str):
            normalized["asset_path"] = asset_path.strip().lstrip("/")
        aids.append(normalized)
    return aids


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
    out["memory_optimized"] = _normalize_memory_optimized(out)
    out["memory_aids"] = _normalize_memory_aids(out)
    return out


def extract_json_object(text: str) -> dict[str, Any]:
    """Parse a JSON object from raw model output, including fenced JSON."""
    raw = text.strip()
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw, re.DOTALL | re.IGNORECASE)
    if fenced:
        raw = fenced.group(1)
    else:
        start = raw.find("{")
        end = raw.rfind("}")
        if start != -1 and end != -1 and end > start:
            raw = raw[start : end + 1]
    parsed = json.loads(raw)
    if not isinstance(parsed, dict):
        raise ValueError("Summary response must be a JSON object")
    return parsed


def _candidate_hermes_roots() -> list[Path]:
    candidates: list[Path] = []
    env_root = os.getenv("HERMES_AGENT_ROOT")
    if env_root:
        candidates.append(Path(env_root).expanduser())
    candidates.extend(
        [
            ROOT.parent / "Hermes",
            ROOT.parent / "hermes-agent",
            Path.cwd(),
        ]
    )
    return candidates


def _run_summary_prompt(prompt: str) -> str:
    command = os.getenv("HERMES_YOUTUBE_SUMMARY_COMMAND") or os.getenv("YOUTUBE_SUMMARY_COMMAND")
    if command:
        proc = subprocess.run(
            shlex.split(command),
            input=prompt,
            text=True,
            capture_output=True,
            check=False,
        )
        if proc.returncode != 0:
            raise RuntimeError(proc.stderr.strip() or f"Summary command failed: {command}")
        return proc.stdout

    for root in _candidate_hermes_roots():
        if (root / "run_agent.py").exists():
            sys.path.insert(0, str(root))
            break

    try:
        from run_agent import AIAgent
    except Exception as exc:  # noqa: BLE001 - dashboard helper boundary
        raise RuntimeError(
            "Could not import Hermes. Run this helper from beside the Hermes checkout, "
            "set HERMES_AGENT_ROOT, or set HERMES_YOUTUBE_SUMMARY_COMMAND."
        ) from exc

    agent = AIAgent(
        platform="youtube-summary-dashboard",
        max_iterations=1,
        quiet_mode=True,
        skip_memory=True,
        skip_context_files=True,
        enabled_toolsets=[],
    )
    return agent.chat(prompt).strip()


def build_summary_prompt(payload: dict[str, Any], word_limit: int) -> str:
    transcript = str(payload.get("transcript_text") or "")[:120000]
    highlights = payload.get("timestamped_transcript") or []
    highlight_sample = highlights[:160] if isinstance(highlights, list) else []
    metadata = {
        "video_id": payload.get("video_id"),
        "video_url": payload.get("video_url"),
        "language": payload.get("language"),
        "transcript_source": payload.get("transcript_source"),
        "word_limit": word_limit,
        "timestamped_transcript_sample": highlight_sample,
    }
    return (
        f"{SUMMARY_PROMPT}\n\n"
        f"Use a maximum of {word_limit} words unless the user later requests a different length.\n"
        "Return only the JSON object, with no prose before or after it.\n\n"
        "Metadata:\n"
        f"{json.dumps(metadata, ensure_ascii=False, indent=2)}\n\n"
        "Transcript:\n"
        f"{transcript}"
    )


def summarize_transcript_payload(
    payload: dict[str, Any],
    *,
    word_limit: int = DEFAULT_WORD_LIMIT,
    runner: Callable[[str], str] | None = None,
) -> dict[str, Any]:
    if not str(payload.get("transcript_text") or "").strip():
        raise ValueError("Transcript is empty")

    prompt = build_summary_prompt(payload, word_limit)
    response = (runner or _run_summary_prompt)(prompt)
    summary = extract_json_object(response)

    video_id = str(payload.get("video_id") or extract_video_id(str(payload.get("video_url") or "")))
    summary.setdefault("id", f"{now_iso()[:10]}-{video_id}")
    summary.setdefault("video_url", payload.get("video_url") or canonical_url(video_id))
    summary.setdefault("title", f"YouTube video {video_id}")
    summary.setdefault("summarized_at", now_iso())
    summary.setdefault("transcript_source", payload.get("transcript_source") or "")
    summary.setdefault("word_limit", word_limit)
    if not summary.get("timestamped_highlights") and payload.get("timestamped_transcript"):
        summary["timestamped_highlights"] = [
            {"time": item.get("time", ""), "note": item.get("text", "")}
            for item in payload.get("timestamped_transcript", [])[:8]
            if isinstance(item, dict)
        ]

    normalized = normalize_summary(summary)
    errors = validate_summary(normalized)
    if errors:
        raise ValueError("Invalid summary: " + "; ".join(errors))
    return normalized


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


def create_summary_from_url(
    url: str,
    *,
    languages: list[str],
    word_limit: int = DEFAULT_WORD_LIMIT,
    runner: Callable[[str], str] | None = None,
    replace: bool = False,
) -> dict[str, Any]:
    payload = fetch_transcript(url, languages)
    summary = summarize_transcript_payload(payload, word_limit=word_limit, runner=runner)
    action, total = upsert_summary(summary, replace=replace)
    return {
        "ok": True,
        "action": action,
        "total": total,
        "summary": summary,
        "items": load_json(DATA_FILE, []),
        "dashboard_url": DASHBOARD_URL,
    }


def _heading_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()


def _markdown_sections(markdown: str) -> dict[str, str]:
    sections: dict[str, list[str]] = {"": []}
    current = ""
    for line in markdown.splitlines():
        heading = re.match(r"^#{2,6}\s+(.+?)\s*$", line)
        if heading:
            current = _heading_key(heading.group(1))
            sections.setdefault(current, [])
            continue
        sections.setdefault(current, []).append(line)
    return {key: "\n".join(lines).strip() for key, lines in sections.items()}


def _first_section(sections: dict[str, str], *names: str) -> str:
    for name in names:
        value = sections.get(_heading_key(name), "").strip()
        if value:
            return value
    return ""


def _clean_markdown_text(value: str) -> str:
    lines = []
    for line in value.splitlines():
        stripped = line.strip()
        if not stripped:
            if lines and lines[-1] != "":
                lines.append("")
            continue
        if re.match(r"^#{1,6}\s+", stripped):
            continue
        if re.match(r"^(source|video id|duration):", stripped, re.IGNORECASE):
            continue
        stripped = re.sub(r"`([^`]+)`", r"\1", stripped)
        stripped = re.sub(r"\*\*([^*]+)\*\*", r"\1", stripped)
        lines.append(stripped)
    return "\n".join(lines).strip()


def _paragraph(section: str) -> str:
    text = _clean_markdown_text(section)
    paragraphs = [part.strip() for part in re.split(r"\n\s*\n", text) if part.strip()]
    return "\n\n".join(paragraphs)


def _bullet_items(section: str) -> list[str]:
    items: list[str] = []
    current: list[str] = []
    for line in section.splitlines():
        match = re.match(r"^\s*[-*]\s+(.+?)\s*$", line)
        if match:
            if current:
                items.append(_clean_markdown_text(" ".join(current)))
            current = [match.group(1).strip()]
            continue
        if current and line.startswith((" ", "\t")) and line.strip():
            current.append(line.strip())
    if current:
        items.append(_clean_markdown_text(" ".join(current)))
    return [item for item in items if item]


def _timestamped_highlights(section: str) -> list[dict[str, str]]:
    highlights: list[dict[str, str]] = []
    for item in _bullet_items(section):
        match = re.match(
            r"^(?P<time>\d{1,2}:\d{2}(?::\d{2})?)\s*(?:[-\u2013\u2014:]|\s+-\s+)\s*(?P<note>.+)$",
            item,
        )
        if match:
            highlights.append({"time": match.group("time"), "note": match.group("note").strip()})
    return highlights


def _created_at_iso(metadata: dict[str, Any]) -> str:
    created_at = metadata.get("created_at")
    if isinstance(created_at, (int, float)) and created_at > 0:
        return datetime.fromtimestamp(created_at, timezone.utc).astimezone().isoformat(timespec="seconds")
    return now_iso()


def _id_date(metadata: dict[str, Any], iso: str) -> str:
    if isinstance(metadata.get("path"), str):
        match = re.search(r"(\d{8})-\d{6}-([A-Za-z0-9_-]{11})", metadata["path"])
        if match:
            raw = match.group(1)
            return f"{raw[:4]}-{raw[4:6]}-{raw[6:8]}"
    return iso[:10]


def _hermes_home() -> Path:
    return Path(os.getenv("HERMES_HOME", str(Path.home() / ".hermes"))).expanduser()


def _copy_summary_asset(asset_path: str) -> str:
    safe_path = asset_path.strip().lstrip("/")
    if not safe_path or any(part in {"", ".", ".."} for part in safe_path.split("/")):
        return safe_path
    if safe_path.startswith("video/"):
        relative_to_video = safe_path.removeprefix("video/")
    else:
        relative_to_video = safe_path
    sources = [
        _hermes_home() / relative_to_video,
        Path.home() / ".hermes" / relative_to_video,
    ]
    login_user = os.getenv("SUDO_USER") or os.getenv("LOGNAME") or os.getenv("USER")
    if login_user:
        sources.append(Path("/Users") / login_user / ".hermes" / relative_to_video)
    destination = ROOT / "video" / relative_to_video
    for source in sources:
        if source.exists() and source.is_file() and not destination.exists():
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
            break
    return relative_to_video


def _metadata_memory_aids(metadata: dict[str, Any], markdown_path: str | None) -> list[dict[str, Any]] | None:
    raw = metadata.get("memory_aids")
    if not isinstance(raw, list):
        return None
    aids: list[dict[str, Any]] = []
    for aid in raw:
        if not isinstance(aid, dict):
            continue
        normalized = dict(aid)
        asset_path = normalized.get("asset_path")
        if isinstance(asset_path, str) and asset_path.strip():
            normalized["asset_path"] = _copy_summary_asset(asset_path)
        aids.append(normalized)
    if markdown_path:
        stem = Path(markdown_path).with_suffix("").name
        inferred_svg = f"youtube_summaries/{stem}-memory-map.svg"
        if (_hermes_home() / inferred_svg).exists():
            copied = _copy_summary_asset(inferred_svg)
            for aid in aids:
                if aid.get("type") == "concept_map" and not aid.get("asset_path"):
                    aid["asset_path"] = copied
                    break
    return aids


def dashboard_summary_from_hermes_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    markdown = str(metadata.get("summary") or "")
    if not markdown.strip():
        path = metadata.get("path")
        if isinstance(path, str):
            candidate = Path(path).expanduser()
            if not candidate.is_absolute():
                candidate = Path(os.getenv("HERMES_HOME", str(Path.home() / ".hermes"))) / candidate
            if candidate.exists():
                markdown = candidate.read_text(encoding="utf-8")
    if not markdown.strip():
        raise ValueError("Hermes summary metadata does not include summary markdown")

    video_id = str(metadata.get("video_id") or extract_video_id(str(metadata.get("url") or "")))
    summarized_at = _created_at_iso(metadata)
    sections = _markdown_sections(markdown)
    key_insights = _bullet_items(_first_section(sections, "Key Insights", "Key Points"))
    key_takeaways = _bullet_items(_first_section(sections, "Key Takeaways"))
    if not key_takeaways:
        key_takeaways = key_insights[:]
    actionable_points = _bullet_items(
        _first_section(sections, "Actionable Points", "Action Items", "Action Items / Implications")
    )
    brief = _paragraph(_first_section(sections, "Brief", "Concise Summary", "Summary"))
    if not brief:
        brief = _paragraph(sections.get("", ""))
    if not brief and key_insights:
        brief = "\n\n".join(key_insights[:2])
    conclusion = _paragraph(_first_section(sections, "Brief Conclusion", "Final Takeaway", "Conclusion", "Takeaway"))
    if not conclusion and brief:
        conclusion = brief.split("\n\n")[-1]

    markdown_path = metadata.get("path") if isinstance(metadata.get("path"), str) else None
    memory_aids = _metadata_memory_aids(metadata, markdown_path)
    summary = {
        "id": f"{_id_date(metadata, summarized_at)}-{video_id}",
        "video_url": str(metadata.get("url") or canonical_url(video_id)),
        "title": str(metadata.get("title") or f"YouTube video {video_id}"),
        "channel": str(metadata.get("channel") or ""),
        "published_at": metadata.get("published_at"),
        "summarized_at": summarized_at,
        "transcript_source": str(metadata.get("transcript_source") or "Hermes local summary"),
        "word_limit": metadata.get("word_limit"),
        "tags": list(metadata.get("tags") or ["youtube", "summary"]),
        "brief": brief,
        "key_insights": key_insights,
        "key_takeaways": key_takeaways,
        "actionable_points": actionable_points,
        "timestamped_highlights": _timestamped_highlights(
            _first_section(sections, "Timestamped Highlights", "Notable Details")
        ),
        "brief_conclusion": conclusion,
        "notes": str(metadata.get("notes") or ""),
    }
    if memory_aids is not None:
        summary["memory_aids"] = memory_aids
    normalized = normalize_summary(summary)
    errors = validate_summary(normalized)
    if errors:
        raise ValueError("Invalid imported summary: " + "; ".join(errors))
    return normalized


def import_hermes_summary(path: Path | str, *, replace: bool) -> dict[str, Any]:
    metadata = load_json(Path(path), {})
    if not isinstance(metadata, dict):
        raise ValueError("Hermes summary metadata must be a JSON object")
    summary = dashboard_summary_from_hermes_metadata(metadata)
    action, total = upsert_summary(summary, replace=replace)
    return {
        "ok": True,
        "action": action,
        "total": total,
        "summary": summary,
        "items": load_json(DATA_FILE, []),
        "dashboard_url": DASHBOARD_URL,
    }


def import_hermes_summaries(path: Path | str, *, replace: bool) -> list[dict[str, Any]]:
    source = Path(path).expanduser()
    files = sorted(source.glob("*.json")) if source.is_dir() else [source]
    return [import_hermes_summary(file, replace=replace) for file in files]


class SummaryHTTPServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(
        self,
        server_address: tuple[str, int],
        request_handler: type[BaseHTTPRequestHandler],
        *,
        languages: list[str],
        word_limit: int,
        replace: bool,
    ) -> None:
        super().__init__(server_address, request_handler)
        self.languages = languages
        self.word_limit = word_limit
        self.replace = replace


class SummaryRequestHandler(BaseHTTPRequestHandler):
    server: SummaryHTTPServer

    def log_message(self, fmt: str, *args: Any) -> None:
        print(f"[youtube-summary] {self.address_string()} - {fmt % args}", file=sys.stderr)

    def _cors(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Private-Network", "true")

    def _json(self, status: int, payload: dict[str, Any]) -> None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self._cors()
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length") or "0")
        if length <= 0:
            return {}
        body = self.rfile.read(length).decode("utf-8")
        parsed = json.loads(body)
        if not isinstance(parsed, dict):
            raise ValueError("Request body must be a JSON object")
        return parsed

    def do_OPTIONS(self) -> None:  # noqa: N802 - http.server hook
        self.send_response(204)
        self._cors()
        self.end_headers()

    def _delete_summary_response(self, post_id: str | None, body: dict[str, Any] | None = None) -> None:
        body = body or {}
        target_id = str(post_id or body.get("id") or body.get("post_id") or "").strip()
        file_path = str(body.get("file_path") or body.get("path") or "").strip() or None
        token = str(body.get("token") or "").strip() or None
        if not target_id and not file_path:
            raise ValueError("Provide an id/post_id or file_path to delete.")
        if file_path and not token:
            raise ValueError("Provide a GitHub token in the request body when deleting a markdown file.")
        if target_id:
            result = delete_summary(
                target_id,
                file_path=file_path,
                repo=body.get("repo"),
                token=token,
                branch=body.get("branch"),
                message=body.get("message"),
            )
        else:
            github_result = delete_github_markdown_file(
                file_path or "",
                repo=body.get("repo"),
                token=token,
                branch=body.get("branch"),
                message=body.get("message"),
            )
            result = {
                "ok": True,
                "deleted": github_result.get("deleted"),
                "already_missing": github_result.get("already_missing"),
                "removed_local": False,
                "github": github_result,
            }
        self._json(200, result)

    def do_GET(self) -> None:  # noqa: N802 - http.server hook
        path = urlparse(self.path).path.rstrip("/") or "/"
        if path == "/health":
            self._json(
                200,
                {
                    "ok": True,
                    "dashboard_url": DASHBOARD_URL,
                    "total": len(load_json(DATA_FILE, [])),
                },
            )
            return
        if path == "/summaries":
            self._json(200, {"ok": True, "items": load_json(DATA_FILE, []), "dashboard_url": DASHBOARD_URL})
            return
        if path == "/prompt":
            self._json(200, {"ok": True, "prompt": SUMMARY_PROMPT})
            return
        self._json(404, {"ok": False, "error": "Not found"})

    def do_POST(self) -> None:  # noqa: N802 - http.server hook
        path = urlparse(self.path).path.rstrip("/") or "/"
        if path in {"/summaries/delete", "/delete"}:
            try:
                self._delete_summary_response(None, self._read_json())
            except ValueError as exc:
                self._json(400, {"ok": False, "error": str(exc)})
            except GitHubAPIError as exc:
                status = 404 if exc.status == 404 else 502
                self._json(status, {"ok": False, "error": str(exc), "status": exc.status})
            except Exception as exc:  # noqa: BLE001 - local API error boundary
                self._json(502, {"ok": False, "error": str(exc)})
            return
        if path != "/summaries":
            self._json(404, {"ok": False, "error": "Not found"})
            return
        try:
            body = self._read_json()
            url = str(body.get("url") or body.get("text") or "").strip()
            if not url:
                raise ValueError("Paste a YouTube URL.")
            languages = body.get("languages") or self.server.languages
            if isinstance(languages, str):
                languages = [item.strip() for item in languages.split(",") if item.strip()]
            word_limit = int(body.get("word_limit") or self.server.word_limit)
            result = create_summary_from_url(
                url,
                languages=languages,
                word_limit=word_limit,
                replace=bool(body.get("replace", self.server.replace)),
            )
            self._json(200, result)
        except ValueError as exc:
            self._json(400, {"ok": False, "error": str(exc)})
        except Exception as exc:  # noqa: BLE001 - local API error boundary
            self._json(502, {"ok": False, "error": str(exc)})

    def do_DELETE(self) -> None:  # noqa: N802 - http.server hook
        path = urlparse(self.path).path.rstrip("/") or "/"
        if path == "/summaries":
            post_id = None
        elif path.startswith("/summaries/"):
            post_id = path.rsplit("/", 1)[-1]
        else:
            self._json(404, {"ok": False, "error": "Not found"})
            return
        try:
            self._delete_summary_response(post_id, self._read_json())
        except ValueError as exc:
            self._json(400, {"ok": False, "error": str(exc)})
        except GitHubAPIError as exc:
            status = 404 if exc.status == 404 else 502
            self._json(status, {"ok": False, "error": str(exc), "status": exc.status})
        except Exception as exc:  # noqa: BLE001 - local API error boundary
            self._json(502, {"ok": False, "error": str(exc)})


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


def command_import_hermes(args: argparse.Namespace) -> int:
    source = Path(args.path).expanduser()
    results = import_hermes_summaries(source, replace=args.replace)
    count = len(results)
    label = "summary" if count == 1 else "summaries"
    print(f"Imported {count} Hermes {label}. Dashboard entries: {len(load_json(DATA_FILE, []))}")
    print(DASHBOARD_URL)
    return 0


def command_delete(args: argparse.Namespace) -> int:
    if not args.id and not args.file_path:
        raise ValueError("delete requires --id/--post-id or --file-path")
    if args.id:
        result = delete_summary(
            args.id,
            file_path=args.file_path,
            repo=args.repo,
            token=args.token,
            branch=args.branch,
            message=args.message,
        )
    else:
        github_result = delete_github_markdown_file(
            args.file_path,
            repo=args.repo,
            token=args.token,
            branch=args.branch,
            message=args.message,
        )
        result = {
            "ok": True,
            "deleted": github_result.get("deleted"),
            "already_missing": github_result.get("already_missing"),
            "removed_local": False,
            "github": github_result,
        }
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


def command_serve(args: argparse.Namespace) -> int:
    languages = [item.strip() for item in args.language.split(",") if item.strip()]
    server = SummaryHTTPServer(
        (args.host, args.port),
        SummaryRequestHandler,
        languages=languages,
        word_limit=args.word_limit,
        replace=args.replace,
    )
    print(f"YouTube summary dashboard helper listening on http://{args.host}:{args.port}")
    print(f"Dashboard: {DASHBOARD_URL}")
    print("Press Ctrl-C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        server.server_close()
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

    import_hermes = sub.add_parser("import-hermes", help="Import saved Hermes dashboard summaries")
    import_hermes.add_argument(
        "path",
        nargs="?",
        default=str(Path(os.getenv("HERMES_HOME", str(Path.home() / ".hermes"))) / "youtube_summaries"),
        help="Metadata JSON file or directory; default: $HERMES_HOME/youtube_summaries",
    )
    import_hermes.add_argument("--replace", action="store_true", help="Replace existing entries with the same id")
    import_hermes.set_defaults(func=command_import_hermes)

    delete = sub.add_parser("delete", help="Delete a summary record and its GitHub markdown file")
    delete.add_argument("--id", "--post-id", dest="id", help="Dashboard summary/post id to remove from local data")
    delete.add_argument("--file-path", help="Repository-relative markdown path to delete")
    delete.add_argument("--repo", help="GitHub owner/repo; default GITHUB_REPOSITORY/GITHUB_REPO or ishanmish/hermes-artifacts")
    delete.add_argument("--branch", help="Git branch; default GITHUB_BRANCH/GITHUB_PAGES_BRANCH or main")
    delete.add_argument("--token", help="GitHub token; default GITHUB_TOKEN/GH_TOKEN")
    delete.add_argument("--message", help="Commit message for the GitHub deletion")
    delete.set_defaults(func=command_delete)

    serve = sub.add_parser("serve", help="Run the local dashboard submission API")
    serve.add_argument("--host", default=DEFAULT_SERVICE_HOST, help="Host to bind, default: 127.0.0.1")
    serve.add_argument("--port", type=int, default=DEFAULT_SERVICE_PORT, help="Port to bind, default: 8765")
    serve.add_argument("--language", default="en,hi", help="Comma-separated language fallback list, default: en,hi")
    serve.add_argument("--word-limit", type=int, default=DEFAULT_WORD_LIMIT, help="Summary word limit, default: 350")
    serve.add_argument("--replace", action="store_true", help="Replace an existing entry with the same id")
    serve.set_defaults(func=command_serve)
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
