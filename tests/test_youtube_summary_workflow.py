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
