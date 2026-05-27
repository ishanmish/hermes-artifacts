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
