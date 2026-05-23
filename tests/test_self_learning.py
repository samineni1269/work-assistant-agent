import json, pytest
from pathlib import Path
from unittest.mock import patch

def test_correction_detection():
    from tools.corrections import detect_correction
    assert detect_correction("that's wrong, I meant Python not Java") == ("Python not Java", "Java")
    assert detect_correction("no, the answer is 42") == ("42", None)
    assert detect_correction("show me my emails") is None

def test_save_and_load_corrections(tmp_path):
    import tools.corrections as mod
    from unittest.mock import patch
    with patch.object(mod, "CORRECTIONS_FILE", tmp_path / "corrections.json"):
        mod.save_correction(
            bad_response="Java is the language",
            correction="Python not Java",
            user_message="what language do we use"
        )
        ctx = mod.get_corrections_context()
        assert "Python not Java" in ctx
        assert "Past corrections" in ctx


def test_tool_weight_recording(tmp_path):
    import tools.self_learning as mod
    from unittest.mock import patch
    with patch.object(mod, "SL_FILE", tmp_path / "sl.json"):
        mod.record_tool_usage("github", ["get_github_notifications", "list_pull_requests"])
        mod.record_tool_usage("github", ["get_github_notifications"])
        order = mod.get_tool_order("show my github notifications")
        assert order[0] == "get_github_notifications"

def test_error_pattern_avoidance(tmp_path):
    import tools.self_learning as mod
    from unittest.mock import patch
    with patch.object(mod, "SL_FILE", tmp_path / "sl.json"):
        mod.record_tool_error("search_jira", "timeout")
        mod.record_tool_error("search_jira", "timeout")
        mod.record_tool_error("search_jira", "timeout")
        assert mod.should_skip_tool("search_jira") is True
        assert mod.should_skip_tool("get_emails") is False

def test_smart_briefing_timing(tmp_path):
    import tools.self_learning as mod
    from unittest.mock import patch
    with patch.object(mod, "SL_FILE", tmp_path / "sl.json"):
        for _ in range(5):
            mod.record_app_open(hour=8)
        for _ in range(10):
            mod.record_app_open(hour=9)
        assert mod.get_optimal_briefing_hour() == 9

def test_alert_priority(tmp_path):
    import tools.self_learning as mod
    from unittest.mock import patch
    with patch.object(mod, "SL_FILE", tmp_path / "sl.json"):
        # 8 acted out of 10 total → should be "high"
        for _ in range(8):
            mod.record_alert_action("github_pr", "acted")
        for _ in range(2):
            mod.record_alert_action("github_pr", "dismissed")
        assert mod.get_alert_priority("github_pr") == "high"
        # 1 acted out of 10 total → should be "muted"
        for _ in range(1):
            mod.record_alert_action("slack_dm", "acted")
        for _ in range(9):
            mod.record_alert_action("slack_dm", "dismissed")
        assert mod.get_alert_priority("slack_dm") == "muted"

def test_query_clustering(tmp_path):
    import tools.self_learning as mod
    from unittest.mock import patch
    with patch.object(mod, "SL_FILE", tmp_path / "sl.json"):
        for _ in range(3):
            mod.record_query("show my github pull requests")
        clusters = mod.get_query_clusters()
        assert len(clusters) >= 1
        assert clusters[0]["count"] >= 3

def test_auto_ingest_deduplication(tmp_path):
    import tools.auto_ingest as mod
    from unittest.mock import patch
    with patch.object(mod, "SEEN_FILE", tmp_path / "seen.json"):
        assert mod._already_seen("abc123") is False
        mod._mark_seen("abc123")
        assert mod._already_seen("abc123") is True
        # Marking again should not duplicate
        mod._mark_seen("abc123")
        seen = json.loads((tmp_path / "seen.json").read_text())
        assert seen.count("abc123") == 1

def test_tone_snippet_extraction():
    from tools.auto_ingest import _extract_tone_snippet
    email_body = "Hi John,\n\nJust following up on the PR review.\n\n> On Mon, John wrote:\n> please review this\n\nLet me know if you need anything.\n\nThanks,\nSai"
    snippet = _extract_tone_snippet(email_body)
    # Should strip reply lines (starting with ">") and "On..." lines
    assert ">" not in snippet
    assert len(snippet) > 10

def test_extract_meeting_keywords():
    from tools.meeting_prep import extract_keywords
    keywords = extract_keywords("Sprint Planning with Sarah and the backend team")
    assert "Sarah" in keywords
    # "Sprint" or "Planning" should appear (capitalised words)
    assert any(k in keywords for k in ["Sprint", "Planning", "Sprint Planning"])
    # "backend" should appear (>4 chars, not a stopword)
    assert "backend" in keywords

def test_build_meeting_brief_no_crash():
    from tools.meeting_prep import build_meeting_brief
    # Should not raise even with no credentials configured
    event = {
        "subject": "Sprint Review",
        "start": "2026-06-01T10:00:00Z",
        "end": "2026-06-01T11:00:00Z",
        "attendees": ["Alice Smith", "Bob Jones"],
        "body": ""
    }
    brief = build_meeting_brief(event)
    assert "Sprint Review" in brief
    assert brief.startswith("## 📅")
