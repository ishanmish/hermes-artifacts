import json
from pathlib import Path

from scripts import youtube_summary_workflow as workflow


def test_dashboard_html_has_own_url_submission_surface():
    html = (workflow.ROOT / "video" / "youtube-summary-dashboard.html").read_text(
        encoding="utf-8"
    )

    assert 'id="summaryForm"' in html
    assert 'id="videoUrl"' in html
    assert "createSummary" in html
    assert "http://127.0.0.1:8765" in html
    assert "../Hermes/venv/bin/python scripts/youtube_summary_workflow.py serve" in html
    assert "Could not reach the local helper" in html


def test_dashboard_html_renders_memory_aids_inside_video_page():
    html = (workflow.ROOT / "video" / "youtube-summary-dashboard.html").read_text(
        encoding="utf-8"
    )

    assert "function memoryAids" in html
    assert "function conceptMapSvg" in html
    assert "Memory Aids" in html
    assert "Mnemonic" in html
    assert "Recall Prompts" in html
    assert "concept-map" in html


def test_summary_prompt_requires_memory_optimized_json_contract():
    prompt = workflow.SUMMARY_PROMPT

    assert "Memory-Optimized YouTube Video Summarizer Prompt" in prompt
    assert "HIGH-RETENTION KNOWLEDGE DOCUMENT" in prompt
    for field in (
        "memory_optimized",
        "one_sentence_core_thesis",
        "most_important_ideas",
        "mental_models",
        "counterintuitive_insights",
        "key_quotes",
        "facts_data_statistics",
        "mistakes_misunderstandings",
        "compression_layer",
        "flashcards",
        "final_synthesis",
    ):
        assert field in prompt


def test_dashboard_html_renders_memory_optimized_summary_format():
    html = (workflow.ROOT / "video" / "youtube-summary-dashboard.html").read_text(
        encoding="utf-8"
    )

    assert "function memoryOptimized" in html
    assert "${memoryOptimized(v)}" in html
    assert "One-Sentence Core Thesis" in html
    assert "Most Important Ideas" in html
    assert "Mental Models & Frameworks" in html
    assert "Counterintuitive or Surprising Insights" in html
    assert "Compression Layer" in html
    assert "Flashcards" in html
    assert "Final Synthesis" in html


def test_dashboard_html_exposes_delete_button_and_local_state_removal():
    html = (workflow.ROOT / "video" / "youtube-summary-dashboard.html").read_text(
        encoding="utf-8"
    )

    assert "function deleteSummary(id)" in html
    assert "confirm(`Delete" in html
    assert "GitHub token for deleting this dashboard entry" in html
    assert "function deleteSummaryFromGithubJson(id,token)" in html
    assert "GITHUB_DATA_PATH='video/youtube-summary-data.json'" in html
    assert "Delete YouTube summary ${id}" in html
    assert "method:'DELETE'" in html
    assert "data-delete-id" in html
    assert "videos=Array.isArray(data.items)?data.items:videos.filter" in html


def test_public_dashboard_can_delete_json_only_entries_without_local_helper():
    html = (workflow.ROOT / "video" / "youtube-summary-dashboard.html").read_text(
        encoding="utf-8"
    )

    delete_body = html.split("async function deleteSummary(id){", 1)[1].split(
        "\n}\nasync function loadFromLocalApi", 1
    )[0]
    assert "deleteSummaryFromGithubJson(id,token)" in delete_body
    assert "if(filePath&&apiOnline)" in delete_body
    assert "if(!token)" in delete_body


def test_public_dashboard_loads_static_data_before_local_helper_probe():
    html = (workflow.ROOT / "video" / "youtube-summary-dashboard.html").read_text(
        encoding="utf-8"
    )

    load_body = html.split("async function load(){", 1)[1].split("\n}", 1)[0]
    static_idx = load_body.index("await loadStaticData();")
    render_idx = load_body.index("renderData();")
    refresh_idx = load_body.index("refreshFromLocalApi();")

    assert static_idx < render_idx < refresh_idx
    assert "if(!(await loadFromLocalApi())) await loadStaticData();" not in html


def test_public_dashboard_keeps_archive_status_when_helper_is_offline():
    html = (workflow.ROOT / "video" / "youtube-summary-dashboard.html").read_text(
        encoding="utf-8"
    )

    assert "Local helper offline; public archive is still visible." in html
    assert "Deletions can be published with a GitHub token" in html


def test_create_summary_from_url_fetches_summarizes_and_saves(tmp_path, monkeypatch):
    data_file = tmp_path / "video" / "youtube-summary-data.json"
    manifest = tmp_path / "artifacts.json"
    manifest.write_text("[]", encoding="utf-8")
    monkeypatch.setattr(workflow, "DATA_FILE", data_file)
    monkeypatch.setattr(workflow, "MANIFEST", manifest)

    def fake_fetch(url, languages):
        assert url == "https://youtu.be/dQw4w9WgXcQ"
        assert languages == ["en", "hi"]
        return {
            "video_id": "dQw4w9WgXcQ",
            "video_url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            "language": "en",
            "transcript_source": "youtube-transcript-api",
            "transcript_text": "The speaker explains the main idea and a concrete next step.",
            "timestamped_transcript": [{"time": "0:01", "text": "Main idea"}],
            "summary_prompt": workflow.SUMMARY_PROMPT,
        }

    def fake_runner(prompt):
        assert "The speaker explains the main idea" in prompt
        return """```json
{
  "id": "2026-05-27-dQw4w9WgXcQ",
  "video_url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
  "title": "Useful Video",
  "channel": "Example Channel",
  "published_at": null,
  "summarized_at": "2026-05-27T10:00:00+05:30",
  "transcript_source": "youtube-transcript-api",
  "word_limit": 220,
  "tags": ["learning"],
  "brief": "A short summary.",
  "key_insights": ["The main idea matters."],
  "key_takeaways": ["Remember the main idea."],
  "actionable_points": ["Try the concrete next step."],
  "timestamped_highlights": [{"time": "0:01", "note": "Main idea"}],
  "brief_conclusion": "Use the idea deliberately.",
  "notes": ""
}
```"""

    monkeypatch.setattr(workflow, "fetch_transcript", fake_fetch)

    result = workflow.create_summary_from_url(
        "https://youtu.be/dQw4w9WgXcQ",
        languages=["en", "hi"],
        word_limit=220,
        runner=fake_runner,
        replace=False,
    )

    assert result["action"] == "added"
    assert result["total"] == 1
    assert result["summary"]["title"] == "Useful Video"
    assert json.loads(data_file.read_text(encoding="utf-8")) == [result["summary"]]


def test_upsert_summary_adds_memory_aids_for_dashboard_rendering(tmp_path, monkeypatch):
    data_file = tmp_path / "video" / "youtube-summary-data.json"
    manifest = tmp_path / "artifacts.json"
    manifest.write_text("[]", encoding="utf-8")
    monkeypatch.setattr(workflow, "DATA_FILE", data_file)
    monkeypatch.setattr(workflow, "MANIFEST", manifest)

    summary = {
        "id": "2026-05-27-dQw4w9WgXcQ",
        "video_url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        "title": "Useful Video",
        "channel": "Example Channel",
        "published_at": None,
        "summarized_at": "2026-05-27T10:00:00+05:30",
        "transcript_source": "youtube-transcript-api",
        "word_limit": 220,
        "tags": ["learning"],
        "brief": "A short summary.",
        "key_insights": [
            "The main idea matters.",
            "Concrete next steps make the lesson useful.",
        ],
        "key_takeaways": ["Remember the main idea."],
        "actionable_points": ["Try the concrete next step."],
        "timestamped_highlights": [{"time": "0:01", "note": "Main idea"}],
        "brief_conclusion": "Use the idea deliberately.",
        "notes": "",
    }

    action, total = workflow.upsert_summary(summary, replace=False)

    assert action == "added"
    assert total == 1
    saved = json.loads(data_file.read_text(encoding="utf-8"))[0]
    assert saved["memory_aids"] == [
        {
            "type": "concept_map",
            "title": "Concept Map",
            "center": "Useful Video",
            "items": [
                "The main idea matters.",
                "Concrete next steps make the lesson useful.",
                "Remember the main idea.",
                "Try the concrete next step.",
            ],
        },
        {
            "type": "mnemonic",
            "title": "Mnemonic",
            "items": ["M-C-R-T: Main; Concrete; Remember; Try"],
        },
        {
            "type": "recall_prompts",
            "title": "Recall Prompts",
            "items": [
                "What does the video say about the main idea matters?",
                "What does the video say about concrete next steps make the lesson useful?",
                "What does the video say about remember the main idea?",
                "What does the video say about try the concrete next step?",
            ],
        },
    ]


def test_normalize_summary_backfills_memory_optimized_from_legacy_fields():
    summary = {
        "id": "2026-05-27-dQw4w9WgXcQ",
        "video_url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        "title": "Useful Video",
        "summarized_at": "2026-05-27T10:00:00+05:30",
        "brief": "A short summary. Extra context for the archive.",
        "key_insights": ["The main idea matters."],
        "key_takeaways": ["Remember the main idea."],
        "actionable_points": ["Try the concrete next step."],
        "brief_conclusion": "Use the idea deliberately.",
    }

    normalized = workflow.normalize_summary(summary)

    memory = normalized["memory_optimized"]
    assert memory["one_sentence_core_thesis"] == "A short summary."
    assert memory["most_important_ideas"] == [
        {
            "title": "Main",
            "idea": "The main idea matters.",
            "why_it_matters": "",
            "example": "",
            "memory_hook": "",
            "actionable_takeaway": "Try the concrete next step.",
        }
    ]
    assert memory["compression_layer"] == [
        "The main idea matters.",
        "Remember the main idea.",
        "Try the concrete next step.",
    ]
    assert memory["flashcards"] == [
        {
            "question": "What should you remember about remember the main idea?",
            "answer": "Remember the main idea.",
        }
    ]
    assert memory["final_synthesis"] == {
        "deepest_lesson": "Use the idea deliberately.",
        "how_to_change_thinking_or_action": "Try the concrete next step.",
        "three_takeaways": ["Remember the main idea."],
    }


def test_import_hermes_summary_metadata_maps_markdown_to_dashboard_schema(
    tmp_path, monkeypatch
):
    data_file = tmp_path / "video" / "youtube-summary-data.json"
    manifest = tmp_path / "artifacts.json"
    manifest.write_text("[]", encoding="utf-8")
    monkeypatch.setattr(workflow, "DATA_FILE", data_file)
    monkeypatch.setattr(workflow, "MANIFEST", manifest)

    metadata_path = tmp_path / "saved-summary.json"
    metadata_path.write_text(
        json.dumps(
            {
                "url": "https://www.youtube.com/watch?v=ANV3tE5ywv0",
                "video_id": "ANV3tE5ywv0",
                "title": "How Sundar Pichai is rethinking Google for the AI era | Decoder",
                "duration": "46:17",
                "created_at": 1779890202.348137,
                "summary": "\n".join(
                    [
                        "# How Sundar Pichai is rethinking Google for the AI era",
                        "",
                        "Source: https://www.youtube.com/watch?v=ANV3tE5ywv0",
                        "Video ID: `ANV3tE5ywv0`",
                        "Duration: 46:17",
                        "",
                        "## Concise Summary",
                        "",
                        "Google is reorganizing around AI, Gemini, and agentic tools.",
                        "",
                        "## Key Points",
                        "",
                        "- Gemini is becoming a common layer across Google products.",
                        "- Search is becoming more personalized and opinionated.",
                        "",
                        "## Notable Details",
                        "",
                        "- 3:48 - Pichai describes Google's major product centers.",
                        "- 42:46 - He says AGI may arrive sooner rather than later.",
                        "",
                        "## Action Items / Implications",
                        "",
                        "- Watch how Google merges AI products into shared primitives.",
                        "- Track publisher and creator opt-out rules.",
                        "",
                        "## Final Takeaway",
                        "",
                        "Google's AI reset depends on preserving trust in the web.",
                    ]
                ),
            }
        ),
        encoding="utf-8",
    )

    result = workflow.import_hermes_summary(metadata_path, replace=False)

    assert result["action"] == "added"
    assert result["total"] == 1
    summary = result["summary"]
    assert summary["id"] == "2026-05-27-ANV3tE5ywv0"
    assert summary["video_url"] == "https://www.youtube.com/watch?v=ANV3tE5ywv0"
    assert summary["brief"] == "Google is reorganizing around AI, Gemini, and agentic tools."
    assert summary["key_insights"] == [
        "Gemini is becoming a common layer across Google products.",
        "Search is becoming more personalized and opinionated.",
    ]
    assert summary["key_takeaways"] == summary["key_insights"]
    assert summary["actionable_points"] == [
        "Watch how Google merges AI products into shared primitives.",
        "Track publisher and creator opt-out rules.",
    ]
    assert summary["timestamped_highlights"] == [
        {"time": "3:48", "note": "Pichai describes Google's major product centers."},
        {"time": "42:46", "note": "He says AGI may arrive sooner rather than later."},
    ]
    assert summary["brief_conclusion"] == (
        "Google's AI reset depends on preserving trust in the web."
    )


def test_delete_github_markdown_file_deletes_existing_file(monkeypatch):
    calls = []

    def fake_request(method, url, *, token, payload=None):
        calls.append((method, url, token, payload))
        if method == "GET":
            assert token == "secret-token"
            return {"sha": "file-sha"}
        if method == "DELETE":
            assert payload["sha"] == "file-sha"
            assert payload["branch"] == "main"
            assert "Delete posts/example.md" in payload["message"]
            return {"commit": {"sha": "commit-sha"}}
        raise AssertionError(f"unexpected method: {method}")

    monkeypatch.setattr(workflow, "_github_request", fake_request)

    result = workflow.delete_github_markdown_file(
        "posts/example.md",
        repo="owner/repo",
        token="secret-token",
        branch="main",
    )

    assert result == {
        "ok": True,
        "deleted": True,
        "already_missing": False,
        "path": "posts/example.md",
        "repo": "owner/repo",
        "branch": "main",
        "commit_sha": "commit-sha",
    }
    assert [call[0] for call in calls] == ["GET", "DELETE"]


def test_delete_github_markdown_file_treats_missing_file_as_success(monkeypatch):
    def fake_request(method, url, *, token, payload=None):
        raise workflow.GitHubAPIError("not found", status=404)

    monkeypatch.setattr(workflow, "_github_request", fake_request)

    result = workflow.delete_github_markdown_file(
        "posts/missing.md",
        repo="owner/repo",
        token="secret-token",
        branch="main",
    )

    assert result["ok"] is True
    assert result["deleted"] is False
    assert result["already_missing"] is True


def test_delete_github_markdown_file_treats_delete_race_404_as_missing(monkeypatch):
    calls = []

    def fake_request(method, url, *, token, payload=None):
        calls.append(method)
        if method == "GET":
            return {"sha": "stale-sha"}
        raise workflow.GitHubAPIError("not found", status=404)

    monkeypatch.setattr(workflow, "_github_request", fake_request)

    result = workflow.delete_github_markdown_file(
        "posts/raced.md",
        repo="owner/repo",
        token="secret-token",
        branch="main",
    )

    assert result["ok"] is True
    assert result["deleted"] is False
    assert result["already_missing"] is True
    assert calls == ["GET", "DELETE"]


def test_delete_github_markdown_file_rejects_unsafe_or_non_markdown_paths():
    for path in ("../secret.md", "posts//bad.md", "posts/not-markdown.txt", ""):
        try:
            workflow.delete_github_markdown_file(
                path,
                repo="owner/repo",
                token="secret-token",
                branch="main",
            )
        except ValueError:
            pass
        else:
            raise AssertionError(f"expected ValueError for {path!r}")


def test_http_delete_requires_explicit_body_token():
    handler = object.__new__(workflow.SummaryRequestHandler)

    try:
        handler._delete_summary_response(None, {"file_path": "posts/example.md"})
    except ValueError as exc:
        assert "GitHub token" in str(exc)
    else:
        raise AssertionError("expected ValueError when token is omitted")


def test_http_delete_uses_explicit_body_token(monkeypatch):
    handler = object.__new__(workflow.SummaryRequestHandler)
    captured = []
    handler._json = lambda status, payload: captured.append((status, payload))

    def fake_delete(path, **kwargs):
        assert path == "posts/example.md"
        assert kwargs["token"] == "body-token"
        return {"ok": True, "deleted": False, "already_missing": True, "path": path}

    monkeypatch.setattr(workflow, "delete_github_markdown_file", fake_delete)

    handler._delete_summary_response(
        None,
        {"file_path": "posts/example.md", "token": "body-token", "repo": "owner/repo"},
    )

    assert captured == [
        (
            200,
            {
                "ok": True,
                "deleted": False,
                "already_missing": True,
                "removed_local": False,
                "github": {"ok": True, "deleted": False, "already_missing": True, "path": "posts/example.md"},
            },
        )
    ]


def test_delete_summary_removes_local_record_and_github_markdown(tmp_path, monkeypatch):
    data_file = tmp_path / "video" / "youtube-summary-data.json"
    manifest = tmp_path / "artifacts.json"
    manifest.write_text("[]", encoding="utf-8")
    monkeypatch.setattr(workflow, "DATA_FILE", data_file)
    monkeypatch.setattr(workflow, "MANIFEST", manifest)
    data_file.parent.mkdir(parents=True)
    data_file.write_text(
        json.dumps(
            [
                {
                    "id": "post-1",
                    "video_url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
                    "title": "Delete Me",
                    "summarized_at": "2026-05-27T10:00:00+05:30",
                    "brief": "A short summary.",
                    "key_insights": [],
                    "key_takeaways": [],
                    "actionable_points": [],
                    "brief_conclusion": "Done.",
                    "markdown_path": "posts/post-1.md",
                }
            ]
        ),
        encoding="utf-8",
    )
    github_calls = []

    def fake_delete(path, **kwargs):
        github_calls.append((path, kwargs))
        return {"ok": True, "deleted": True, "already_missing": False, "path": path}

    monkeypatch.setattr(workflow, "delete_github_markdown_file", fake_delete)

    result = workflow.delete_summary(
        "post-1",
        repo="owner/repo",
        token="secret-token",
        branch="main",
    )

    assert result["ok"] is True
    assert result["deleted"] is True
    assert result["removed_local"] is True
    assert result["summary"]["id"] == "post-1"
    assert json.loads(data_file.read_text(encoding="utf-8")) == []
    assert github_calls == [
        (
            "posts/post-1.md",
            {"repo": "owner/repo", "token": "secret-token", "branch": "main", "message": None},
        )
    ]


def test_import_hermes_summary_uses_key_points_and_takeaway_when_no_summary_section():
    summary = workflow.dashboard_summary_from_hermes_metadata(
        {
            "url": "https://www.youtube.com/watch?v=OtkNABB8Ras",
            "video_id": "OtkNABB8Ras",
            "title": "Why Fixing the UK Is So Hard",
            "created_at": 1779891711.645799,
            "summary": "\n".join(
                [
                    "# Why Fixing the UK Is So Hard",
                    "",
                    "## Key Points",
                    "",
                    "- Bloomberg frames the UK's political churn as a collision between public impatience, weak growth, and harsh fiscal reality.",
                    "- Britain has had five prime ministers in roughly seven years, while the cost-of-living crisis and low-growth economy have remained stubbornly unresolved.",
                    "",
                    "## Important Details",
                    "",
                    "- The transcript says UK debt is above 90% of economic output.",
                    "",
                    "## Takeaway",
                    "",
                    "Changing prime ministers will not reset Britain's economic problems.",
                ]
            ),
        }
    )

    assert summary["brief"] == (
        "Bloomberg frames the UK's political churn as a collision between public impatience, "
        "weak growth, and harsh fiscal reality.\n\n"
        "Britain has had five prime ministers in roughly seven years, while the cost-of-living "
        "crisis and low-growth economy have remained stubbornly unresolved."
    )
    assert summary["brief_conclusion"] == (
        "Changing prime ministers will not reset Britain's economic problems."
    )


def test_import_hermes_command_imports_summary_directory(tmp_path, monkeypatch, capsys):
    data_file = tmp_path / "video" / "youtube-summary-data.json"
    manifest = tmp_path / "artifacts.json"
    manifest.write_text("[]", encoding="utf-8")
    monkeypatch.setattr(workflow, "DATA_FILE", data_file)
    monkeypatch.setattr(workflow, "MANIFEST", manifest)

    saved_dir = tmp_path / "youtube_summaries"
    saved_dir.mkdir()
    (saved_dir / "20260527-192642-ANV3tE5ywv0.json").write_text(
        json.dumps(
            {
                "url": "https://www.youtube.com/watch?v=ANV3tE5ywv0",
                "video_id": "ANV3tE5ywv0",
                "title": "AI Era",
                "created_at": 1779890202.348137,
                "summary": "## Summary\n\nA useful summary.\n\n## Key Points\n\n- One point.\n\n## Final Takeaway\n\nRemember this.",
            }
        ),
        encoding="utf-8",
    )

    assert workflow.main(["import-hermes", str(saved_dir)]) == 0

    out = capsys.readouterr().out
    assert "Imported 1 Hermes summary" in out
    items = json.loads(data_file.read_text(encoding="utf-8"))
    assert [item["id"] for item in items] == ["2026-05-27-ANV3tE5ywv0"]
