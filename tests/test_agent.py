"""
tests/test_agent.py — pytest test suite for Work Assistant Agent
================================================================
Tests core modules with mocked external APIs where needed.

Run:
    pytest tests/ -v
"""

import json
import time
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest


# ══════════════════════════════════════════════════════════════════════════════
# HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def _patch_conv_db(tmp_path):
    """Redirect conversation_store DB to a temp file for test isolation."""
    import tools.conversation_store as cs
    cs.DB_PATH = tmp_path / "test_conv.db"
    return cs


def _patch_trigger_db(tmp_path):
    """Redirect trigger_engine DB to a temp file for test isolation."""
    import tools.trigger_engine as te
    te.DB_PATH = tmp_path / "test_triggers.db"
    return te


def _patch_memory_file(tmp_path):
    """Redirect memory.py MEMORY_FILE to a temp file for test isolation."""
    import tools.memory as mem
    mem.MEMORY_FILE = tmp_path / "test_memory.json"
    return mem


def _patch_actions_db(tmp_path):
    """Redirect action_items DB to a temp file for test isolation."""
    import tools.action_items as ai
    ai.DB_PATH = tmp_path / "test_actions.db"
    return ai


# ══════════════════════════════════════════════════════════════════════════════
# conversation_store tests
# ══════════════════════════════════════════════════════════════════════════════

class TestConversationStore:

    def test_save_creates_session(self, tmp_path):
        cs = _patch_conv_db(tmp_path)
        cs.save_turn("s1", "home", "user", "Hello world", "Hello world")
        sessions = cs.list_sessions()
        assert len(sessions) == 1
        assert sessions[0]["id"] == "s1"
        assert sessions[0]["tool_id"] == "home"

    def test_save_increments_turn_count(self, tmp_path):
        cs = _patch_conv_db(tmp_path)
        cs.save_turn("s2", "home", "user", "Hi", "Hi")
        cs.save_turn("s2", "home", "assistant", "Hello!", "")
        cs.save_turn("s2", "home", "user", "How are you?", "")
        sessions = cs.list_sessions()
        assert sessions[0]["turn_count"] == 3

    def test_get_session_turns_order(self, tmp_path):
        cs = _patch_conv_db(tmp_path)
        cs.save_turn("s3", "outlook", "user", "Show emails", "Show emails")
        cs.save_turn("s3", "outlook", "assistant", "Here are your emails…", "")
        turns = cs.get_session_turns("s3")
        assert len(turns) == 2
        assert turns[0]["role"] == "user"
        assert turns[1]["role"] == "assistant"
        assert "emails" in turns[0]["content"]

    def test_list_sessions_filter_by_tool(self, tmp_path):
        cs = _patch_conv_db(tmp_path)
        cs.save_turn("s4", "home",    "user", "Daily briefing", "Daily briefing")
        cs.save_turn("s5", "outlook", "user", "Show emails",    "Show emails")
        outlook_sessions = cs.list_sessions(tool_id="outlook")
        assert len(outlook_sessions) == 1
        assert outlook_sessions[0]["id"] == "s5"

    def test_search_sessions_by_content(self, tmp_path):
        cs = _patch_conv_db(tmp_path)
        cs.save_turn("s6", "home", "user", "Tell me about Gemini 2.5 Flash", "Gemini model")
        cs.save_turn("s7", "home", "user", "What's on my calendar today?",    "Calendar")
        results = cs.search_sessions("Gemini")
        assert len(results) == 1
        assert results[0]["id"] == "s6"

    def test_delete_session_removes_turns(self, tmp_path):
        cs = _patch_conv_db(tmp_path)
        cs.save_turn("s8", "home", "user", "Test message", "Test message")
        cs.delete_session("s8")
        assert cs.list_sessions() == []
        assert cs.get_session_turns("s8") == []

    def test_get_title_from_first_message(self, tmp_path):
        cs = _patch_conv_db(tmp_path)
        cs.save_turn("s9", "home", "user", "What is the weather in London today?", "")
        title = cs.get_session_title_from_first_user_message("s9")
        assert "weather" in title.lower()

    def test_long_title_truncated(self, tmp_path):
        cs = _patch_conv_db(tmp_path)
        long_msg = "A" * 100
        cs.save_turn("s10", "home", "user", long_msg, "")
        title = cs.get_session_title_from_first_user_message("s10")
        assert len(title) <= 63  # 60 chars + ellipsis

    def test_missing_session_returns_empty(self, tmp_path):
        cs = _patch_conv_db(tmp_path)
        turns = cs.get_session_turns("nonexistent-id")
        assert turns == []


# ══════════════════════════════════════════════════════════════════════════════
# trigger_engine tests
# ══════════════════════════════════════════════════════════════════════════════

class TestTriggerEngine:

    def test_add_rule_returns_rule(self, tmp_path):
        te = _patch_trigger_db(tmp_path)
        rule = te.add_rule("PR opened", "github", "pull_request",
                           {"action": "opened"}, "slack_message", {"channel": "#dev"})
        assert rule["name"] == "PR opened"
        assert rule["action"] == "slack_message"
        assert "id" in rule

    def test_list_rules_returns_all(self, tmp_path):
        te = _patch_trigger_db(tmp_path)
        te.add_rule("Rule A", "github", "push",         {}, "notify",        {})
        te.add_rule("Rule B", "jira",   "issues",       {}, "slack_message",  {})
        rules = te.list_rules()
        assert len(rules) == 2
        names = [r["name"] for r in rules]
        assert "Rule A" in names
        assert "Rule B" in names

    def test_delete_rule(self, tmp_path):
        te = _patch_trigger_db(tmp_path)
        te.add_rule("Temp rule", "any", "any", {}, "notify", {})
        rule_id = te.list_rules()[0]["id"]
        te.delete_rule(rule_id)
        assert te.list_rules() == []

    def test_evaluate_event_match(self, tmp_path):
        te = _patch_trigger_db(tmp_path)
        te.add_rule("PR opened", "github", "pull_request",
                    {"action": "opened"}, "slack_message", {"channel": "#prs"})
        matched = te.evaluate_event("github", "pull_request",
                                    {"action": "opened", "number": 42, "title": "Fix bug"})
        assert len(matched) == 1
        assert matched[0]["rule_name"] == "PR opened"
        assert matched[0]["action"] == "slack_message"
        assert matched[0]["action_args"]["channel"] == "#prs"

    def test_evaluate_event_no_match_wrong_condition(self, tmp_path):
        te = _patch_trigger_db(tmp_path)
        te.add_rule("PR closed", "github", "pull_request",
                    {"action": "closed"}, "notify", {})
        matched = te.evaluate_event("github", "pull_request",
                                    {"action": "opened", "title": "Fix bug"})
        assert len(matched) == 0

    def test_evaluate_event_no_match_wrong_source(self, tmp_path):
        te = _patch_trigger_db(tmp_path)
        te.add_rule("GitHub only", "github", "push", {}, "notify", {})
        matched = te.evaluate_event("jira", "push", {"data": "test"})
        assert len(matched) == 0

    def test_evaluate_any_source_matches_all(self, tmp_path):
        te = _patch_trigger_db(tmp_path)
        te.add_rule("Catch all", "any", "any", {}, "notify", {})
        matched_gh   = te.evaluate_event("github", "push",   {"commits": 1})
        matched_jira = te.evaluate_event("jira",   "issues", {"summary": "Bug"})
        assert len(matched_gh)   == 1
        assert len(matched_jira) == 1

    def test_evaluate_increments_fire_count(self, tmp_path):
        te = _patch_trigger_db(tmp_path)
        te.add_rule("Counter test", "any", "any", {}, "notify", {})
        te.evaluate_event("github", "push", {})
        te.evaluate_event("github", "push", {})
        rule = te.list_rules()[0]
        assert rule["fire_count"] == 2

    def test_trigger_log_records_fires(self, tmp_path):
        te = _patch_trigger_db(tmp_path)
        te.add_rule("Log test", "any", "any", {}, "notify", {})
        te.evaluate_event("github", "push", {"data": "x"})
        log = te.get_trigger_log()
        assert len(log) == 1
        assert log[0]["event_type"] == "push"
        assert log[0]["result"] == "matched"

    def test_toggle_rule_disables(self, tmp_path):
        te = _patch_trigger_db(tmp_path)
        te.add_rule("Toggle me", "any", "any", {}, "notify", {})
        rule_id = te.list_rules()[0]["id"]
        te.toggle_rule(rule_id, enabled=False)
        # Disabled rule should not match
        matched = te.evaluate_event("github", "push", {})
        assert len(matched) == 0

    def test_empty_condition_matches_any_payload(self, tmp_path):
        te = _patch_trigger_db(tmp_path)
        te.add_rule("No condition", "github", "push", {}, "notify", {})
        matched = te.evaluate_event("github", "push", {"anything": "here"})
        assert len(matched) == 1


# ══════════════════════════════════════════════════════════════════════════════
# memory + entity extraction tests
# ══════════════════════════════════════════════════════════════════════════════

class TestMemory:

    def test_save_and_load_fact(self, tmp_path):
        mem = _patch_memory_file(tmp_path)
        mem.save_fact("people", "Alice Smith", {"email": "alice@example.com", "role": "PM"})
        loaded = mem.load_memory()
        assert "Alice Smith" in loaded["people"]
        assert loaded["people"]["Alice Smith"]["email"] == "alice@example.com"

    def test_load_missing_file_returns_empty(self, tmp_path):
        mem = _patch_memory_file(tmp_path)
        loaded = mem.load_memory()
        assert loaded["people"] == {}
        assert loaded["context"] == {}

    def test_delete_fact(self, tmp_path):
        mem = _patch_memory_file(tmp_path)
        mem.save_fact("facts", "foo", "bar")
        mem.delete_fact("facts", "foo")
        loaded = mem.load_memory()
        assert "foo" not in loaded["facts"]

    def test_extract_entities_emails(self, tmp_path):
        mem = _patch_memory_file(tmp_path)
        entities = mem.extract_entities("Please email bob@company.com about the project.")
        assert "bob@company.com" in entities["emails"]

    def test_extract_entities_names(self, tmp_path):
        mem = _patch_memory_file(tmp_path)
        entities = mem.extract_entities("I had a meeting with John Smith yesterday.")
        assert "John Smith" in entities["people"]

    def test_extract_entities_tickets(self, tmp_path):
        mem = _patch_memory_file(tmp_path)
        entities = mem.extract_entities("Working on PROJ-123 and ENG-456 this sprint.")
        assert "PROJ-123" in entities["projects"]
        assert "ENG-456" in entities["projects"]

    def test_extract_entities_projects(self, tmp_path):
        mem = _patch_memory_file(tmp_path)
        entities = mem.extract_entities("We're in Sprint 14 and starting Phase 2 next week.")
        projs_lower = [p.lower() for p in entities["projects"]]
        assert any("sprint 14" in p for p in projs_lower)

    def test_auto_save_entities_stores_email(self, tmp_path):
        mem = _patch_memory_file(tmp_path)
        mem.auto_save_entities(
            user_message="Can you email sarah@acme.com about the launch?",
            assistant_response="I'll draft an email to Sarah."
        )
        loaded = mem.load_memory()
        emails_found = [v.get("email", "") for v in loaded["people"].values()
                        if isinstance(v, dict)]
        assert "sarah@acme.com" in emails_found

    def test_auto_save_entities_idempotent(self, tmp_path):
        """Running auto_save_entities twice shouldn't duplicate entries."""
        mem = _patch_memory_file(tmp_path)
        msg = "Email tom@example.com about the project."
        mem.auto_save_entities(msg, "")
        mem.auto_save_entities(msg, "")
        loaded = mem.load_memory()
        # tom@example.com should appear only once
        emails = [v.get("email", "") for v in loaded["people"].values()
                  if isinstance(v, dict)]
        assert emails.count("tom@example.com") == 1

    def test_get_memory_context_empty(self, tmp_path):
        mem = _patch_memory_file(tmp_path)
        ctx = mem.get_memory_context()
        assert ctx == ""

    def test_get_memory_context_with_data(self, tmp_path):
        mem = _patch_memory_file(tmp_path)
        mem.save_fact("context", "current_sprint", "Sprint 14")
        mem.save_fact("preferences", "response_style", "concise")
        ctx = mem.get_memory_context()
        assert "Sprint 14" in ctx
        assert "concise" in ctx


# ══════════════════════════════════════════════════════════════════════════════
# action_items tests
# ══════════════════════════════════════════════════════════════════════════════

class TestActionItems:

    def test_save_and_retrieve(self, tmp_path):
        ai = _patch_actions_db(tmp_path)
        items = [
            {"task": "Review PR #42", "owner": "me", "due_date": "2026-06-01",
             "source": "test", "priority": "high"},
            {"task": "Write docs", "owner": "me", "due_date": "",
             "source": "test", "priority": "medium"},
        ]
        count = ai.save_action_items(items)
        assert count == 2
        result = ai.get_my_action_items(status="open")
        tasks = [r["task"] for r in result]
        assert any("Review PR" in t for t in tasks)
        assert any("Write docs" in t for t in tasks)

    def test_high_priority_comes_first(self, tmp_path):
        ai = _patch_actions_db(tmp_path)
        ai.save_action_items([
            {"task": "Low priority task",  "priority": "low",  "owner": "", "due_date": "", "source": "t"},
            {"task": "High priority task", "priority": "high", "owner": "", "due_date": "", "source": "t"},
        ])
        result = ai.get_my_action_items(status="open")
        assert result[0]["priority"] == "high"

    def test_complete_action_item(self, tmp_path):
        ai = _patch_actions_db(tmp_path)
        ai.save_action_items([{"task": "Finish report", "priority": "low",
                                "owner": "", "due_date": "", "source": "test"}])
        open_items = ai.get_my_action_items(status="open")
        item_id = open_items[0]["id"]
        result = ai.complete_action_item(item_id=item_id)
        assert result["status"] == "completed"
        # Should no longer appear in open list
        open_after = ai.get_my_action_items(status="open")
        assert not any(i["id"] == item_id for i in open_after)
        # Should appear in completed list
        completed = ai.get_my_action_items(status="completed")
        assert any(i["id"] == item_id for i in completed)

    def test_filter_by_priority(self, tmp_path):
        ai = _patch_actions_db(tmp_path)
        ai.save_action_items([
            {"task": "High task",   "priority": "high",   "owner": "", "due_date": "", "source": "t"},
            {"task": "Medium task", "priority": "medium", "owner": "", "due_date": "", "source": "t"},
        ])
        high_only = ai.get_my_action_items(priority="high")
        assert all(i["priority"] == "high" for i in high_only)
        assert len(high_only) == 1

    def test_empty_task_not_saved(self, tmp_path):
        ai = _patch_actions_db(tmp_path)
        count = ai.save_action_items([{"task": "", "priority": "high",
                                        "owner": "", "due_date": "", "source": "t"}])
        assert count == 0
        assert ai.get_my_action_items() == []


# ══════════════════════════════════════════════════════════════════════════════
# retry logic tests  (self-contained, no heavy agent.py import)
# ══════════════════════════════════════════════════════════════════════════════

class TestRetryLogic:
    """
    Tests for the _with_retry pattern used in agent.py dispatch_tool.
    We inline a minimal copy so we don't import the full agent module
    (which would pull in all provider SDKs).
    """

    @staticmethod
    def _with_retry(fn, tool_name, max_attempts=3):
        NO_RETRY_SIGNALS = ("401", "403", "400", "invalid", "not found", "unauthorized")
        delay = 0.01  # accelerated for tests
        last_err = None
        for attempt in range(max_attempts):
            try:
                return fn()
            except Exception as e:
                err_str = str(e).lower()
                last_err = e
                if any(sig in err_str for sig in NO_RETRY_SIGNALS):
                    break
                if attempt < max_attempts - 1:
                    time.sleep(delay)
                    delay *= 2
        tool_label = tool_name.replace("_", " ")
        return json.dumps({"error": f"⚠️ {tool_label} unavailable.", "detail": str(last_err)})

    def test_succeeds_on_first_try(self):
        result = self._with_retry(lambda: '{"ok": true}', "test_tool")
        assert result == '{"ok": true}'

    def test_retries_on_transient_error(self):
        call_count = 0

        def flaky():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ConnectionError("network timeout")
            return '{"ok": true}'

        result = self._with_retry(flaky, "my_tool", max_attempts=3)
        assert result == '{"ok": true}'
        assert call_count == 3

    def test_gives_up_after_max_attempts(self):
        call_count = 0

        def always_fails():
            nonlocal call_count
            call_count += 1
            raise ConnectionError("network timeout")

        result = self._with_retry(always_fails, "outlook", max_attempts=3)
        data = json.loads(result)
        assert "unavailable" in data["error"]
        assert call_count == 3

    def test_no_retry_on_auth_error(self):
        call_count = 0

        def auth_fail():
            nonlocal call_count
            call_count += 1
            raise PermissionError("401 Unauthorized — token expired")

        self._with_retry(auth_fail, "github", max_attempts=3)
        assert call_count == 1  # no retry on 401

    def test_no_retry_on_bad_request(self):
        call_count = 0

        def bad_req():
            nonlocal call_count
            call_count += 1
            raise ValueError("400 Bad Request — invalid parameters")

        self._with_retry(bad_req, "jira", max_attempts=3)
        assert call_count == 1  # no retry on 400

    def test_graceful_message_format(self):
        result = self._with_retry(
            lambda: (_ for _ in ()).throw(RuntimeError("timeout")),
            "get_emails",
            max_attempts=1,
        )
        data = json.loads(result)
        assert "error" in data
        assert "detail" in data
        assert "get emails" in data["error"]  # underscores replaced with spaces


# ══════════════════════════════════════════════════════════════════════════════
# planner mode tests
# ══════════════════════════════════════════════════════════════════════════════

class TestPlannerMode:
    """
    Tests for _is_complex_request heuristic.
    Imported inline to avoid heavy agent.py side-effects.
    """

    PLANNER_KEYWORDS = {
        "plan", "strategy", "set up", "setup", "organise", "organize", "prepare",
        "roadmap", "workflow", "automate", "design", "architect",
        "sprint", "onboard", "migrate", "restructure", "build out",
    }

    def _is_complex(self, message):
        low = message.lower()
        has_keyword = any(kw in low for kw in self.PLANNER_KEYWORDS)
        is_long = len(message.split()) >= 8
        return has_keyword and is_long

    def test_short_message_not_complex(self):
        assert not self._is_complex("Show my emails")

    def test_long_message_no_keyword_not_complex(self):
        assert not self._is_complex("What are the unread emails I have in my inbox today")

    def test_complex_with_keyword_and_length(self):
        assert self._is_complex("Can you help me plan the Q3 sprint and set up the board in Jira")

    def test_automate_keyword(self):
        assert self._is_complex("I want to automate my daily briefing email so it sends every morning at 8am")

    def test_prepare_keyword(self):
        assert self._is_complex("Help me prepare for my performance review with my manager next week")

    def test_onboard_keyword(self):
        assert self._is_complex("Can you help me onboard our new developer to the team repos and tools")
