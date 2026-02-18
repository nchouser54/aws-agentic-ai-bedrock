"""Tests for P1-A manual trigger, P1-B incremental, P2-A compression,
P2-B skip filters, and P3 structured verdict."""
from __future__ import annotations

import importlib
import os
import sys
import types
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _reload_module(module_name: str, env_overrides: dict | None = None):
    """Import (or re-import) a module with optional env overrides."""
    env_overrides = env_overrides or {}
    with patch.dict(os.environ, env_overrides, clear=False):
        if module_name in sys.modules:
            del sys.modules[module_name]
        return importlib.import_module(module_name)


# ===========================================================================
# P3 — _derive_conclusion
# ===========================================================================

class TestDeriveConclusion:
    def _get_fn(self, failure_on_severity="high"):
        mod = _reload_module("worker.app", {"FAILURE_ON_SEVERITY": failure_on_severity,
                                             "PR_REVIEW_STATE_TABLE": "",
                                             "IDEMPOTENCY_TABLE": "x"})
        return mod._derive_conclusion

    def test_no_findings_is_success(self):
        fn = self._get_fn()
        conclusion, verdict = fn([])
        assert conclusion == "success"
        assert "LGTM" in verdict

    def test_low_findings_are_suggestions(self):
        fn = self._get_fn()
        conclusion, verdict = fn([{"severity": "low"}])
        assert conclusion == "neutral"
        assert "Suggestions" in verdict

    def test_high_finding_triggers_failure_default(self):
        fn = self._get_fn("high")
        conclusion, verdict = fn([{"severity": "high"}])
        assert conclusion == "failure"
        assert "Changes Required" in verdict

    def test_medium_finding_does_not_fail_at_high_threshold(self):
        fn = self._get_fn("high")
        conclusion, verdict = fn([{"severity": "medium"}])
        assert conclusion == "neutral"

    def test_medium_finding_fails_at_medium_threshold(self):
        fn = self._get_fn("medium")
        conclusion, verdict = fn([{"severity": "medium"}])
        assert conclusion == "failure"

    def test_none_threshold_never_fails(self):
        fn = self._get_fn("none")
        conclusion, verdict = fn([{"severity": "high"}])
        assert conclusion == "neutral"

    def test_priority_zero_treated_as_high(self):
        fn = self._get_fn("high")
        conclusion, verdict = fn([{"priority": 0}])
        assert conclusion == "failure"


# ===========================================================================
# P2-B — _should_skip_review
# ===========================================================================

class TestShouldSkipReview:
    def _get_fn(self, **env):
        base_env = {
            "IGNORE_PR_AUTHORS": "",
            "IGNORE_PR_LABELS": "",
            "IGNORE_PR_SOURCE_BRANCHES": "",
            "IGNORE_PR_TARGET_BRANCHES": "",
            "PR_REVIEW_STATE_TABLE": "",
            "IDEMPOTENCY_TABLE": "x",
        }
        base_env.update(env)
        mod = _reload_module("worker.app", base_env)
        return mod._should_skip_review

    def _pr(self, author="alice", labels=None, head_ref="feature/foo", base_ref="main"):
        return {
            "user": {"login": author},
            "labels": [{"name": lb} for lb in (labels or [])],
            "head": {"ref": head_ref},
            "base": {"ref": base_ref},
        }

    def test_no_filters_no_skip(self):
        fn = self._get_fn()
        skip, reason = fn(self._pr(), "opened", "auto")
        assert not skip

    def test_skip_by_author(self):
        fn = self._get_fn(IGNORE_PR_AUTHORS="dependabot[bot],renovate")
        skip, reason = fn(self._pr(author="dependabot[bot]"), "opened", "auto")
        assert skip
        assert "author" in reason.lower()

    def test_skip_by_label(self):
        fn = self._get_fn(IGNORE_PR_LABELS="wip,do-not-review")
        skip, reason = fn(self._pr(labels=["wip"]), "opened", "auto")
        assert skip
        assert "label" in reason.lower()

    def test_skip_by_source_branch_regex(self):
        fn = self._get_fn(IGNORE_PR_SOURCE_BRANCHES="^chore/")
        skip, reason = fn(self._pr(head_ref="chore/update-deps"), "opened", "auto")
        assert skip

    def test_skip_by_target_branch_regex(self):
        fn = self._get_fn(IGNORE_PR_TARGET_BRANCHES="^release/")
        skip, reason = fn(self._pr(base_ref="release/1.0.0"), "opened", "auto")
        assert skip

    def test_manual_trigger_bypasses_author_filter(self):
        fn = self._get_fn(IGNORE_PR_AUTHORS="alice")
        skip, reason = fn(self._pr(author="alice"), "opened", "manual")
        assert not skip

    def test_manual_trigger_bypasses_label_filter(self):
        fn = self._get_fn(IGNORE_PR_LABELS="wip")
        skip, reason = fn(self._pr(labels=["wip"]), "opened", "manual")
        assert not skip


# ===========================================================================
# P1-A — webhook receiver manual trigger detection
# ===========================================================================

class TestIsManualTrigger:
    def _get_fn(self, phrase="/review", bot=""):
        mod = _reload_module("webhook_receiver.app", {
            "REVIEW_TRIGGER_PHRASE": phrase,
            "BOT_USERNAME": bot,
            "WEBHOOK_SECRET_ARN": "arn:fake",
        })
        return mod._is_manual_trigger

    def test_basic_phrase_match(self):
        fn = self._get_fn("/review")
        assert fn("/review")

    def test_phrase_with_trailing_text(self):
        fn = self._get_fn("/review")
        assert fn("/review please")

    def test_bot_mention_review(self):
        fn = self._get_fn("/review", bot="mybot")
        with patch.dict(os.environ, {"BOT_USERNAME": "mybot", "REVIEW_TRIGGER_PHRASE": "/review"}):
            assert fn("@mybot review")

    def test_bot_mention_phrase(self):
        fn = self._get_fn("/review", bot="mybot")
        with patch.dict(os.environ, {"BOT_USERNAME": "mybot", "REVIEW_TRIGGER_PHRASE": "/review"}):
            assert fn("@mybot /review")

    def test_unrelated_comment_not_matched(self):
        fn = self._get_fn("/review")
        assert not fn("LGTM")

    def test_empty_comment_not_matched(self):
        fn = self._get_fn("/review")
        assert not fn("")


# ===========================================================================
# P2-A — build_context compression
# ===========================================================================

class TestBuildContext:
    def _build(self, files, **env):
        base_env = {
            "MAX_REVIEW_FILES": "30",
            "MAX_DIFF_BYTES": "8000",
            "MAX_TOTAL_DIFF_BYTES": "0",
            "LARGE_PATCH_POLICY": "clip",
            "SKIP_PATTERNS": "",
        }
        base_env.update(env)
        mod = _reload_module("worker.build_context", base_env)
        pr = {"title": "test", "body": "", "head": {"ref": "feat"}, "base": {"ref": "main"},
              "additions": 10, "deletions": 5, "changed_files": len(files)}
        return mod.build_pr_context(pr, files)

    def test_files_sorted_by_changes_desc(self):
        files = [
            {"filename": "small.py", "patch": "x", "changes": 1, "additions": 1, "deletions": 0, "status": "modified"},
            {"filename": "large.py", "patch": "y" * 100, "changes": 100, "additions": 100, "deletions": 0, "status": "modified"},
        ]
        ctx, reviewed, skipped = self._build(files)
        # large.py should be first
        assert ctx["pull_request"]["changed_files"][0]["filename"] == "large.py"

    def test_clip_policy_truncates_oversized_patch(self):
        big_patch = "+" + "a" * 10000
        files = [{"filename": "big.py", "patch": big_patch, "changes": 1, "additions": 1, "deletions": 0, "status": "modified"}]
        ctx, reviewed, skipped = self._build(files, MAX_DIFF_BYTES="100", LARGE_PATCH_POLICY="clip")
        entry = ctx["pull_request"]["changed_files"][0]
        assert len(entry["patch"].encode("utf-8")) <= 100
        assert entry.get("patch_truncated") is True

    def test_skip_policy_excludes_oversized_file(self):
        big_patch = "+" + "a" * 10000
        files = [{"filename": "big.py", "patch": big_patch, "changes": 1, "additions": 1, "deletions": 0, "status": "modified"}]
        ctx, reviewed, skipped = self._build(files, MAX_DIFF_BYTES="100", LARGE_PATCH_POLICY="skip")
        assert len(ctx["pull_request"]["changed_files"]) == 0
        assert any("oversized" in s for s in skipped)

    def test_total_budget_respected(self):
        # 3 files each with 300 bytes of patch; total budget = 500 bytes  → third file skipped
        files = [
            {"filename": f"f{i}.py", "patch": "+" + "x" * 298, "changes": 1,
             "additions": 1, "deletions": 0, "status": "modified"}
            for i in range(3)
        ]
        ctx, reviewed, skipped = self._build(files, MAX_DIFF_BYTES="500", MAX_TOTAL_DIFF_BYTES="500")
        # At least one file should be in reviewed and at least one skipped due to budget
        assert len(reviewed) >= 1
        assert any("budget" in s for s in skipped)


# ===========================================================================
# P3 — render_check_run_body with verdict
# ===========================================================================

class TestRenderMarkdownVerdict:
    def _render(self, verdict=None):
        from worker.render_markdown import render_check_run_body
        review = {
            "summary": "All good.",
            "overall_risk": "low",
            "findings": [],
            "files_reviewed": ["app.py"],
            "files_skipped": [],
        }
        return render_check_run_body(review, verdict=verdict)

    def test_verdict_appears_at_top(self):
        body = self._render(verdict="✅ LGTM")
        assert body.startswith("**✅ LGTM**")

    def test_no_verdict_no_bold_header(self):
        body = self._render(verdict=None)
        assert not body.startswith("**")

    def test_summary_still_present(self):
        body = self._render(verdict="💬 Suggestions")
        assert "Summary" in body
        assert "All good." in body


# ===========================================================================
# P1-B — DynamoDB state helpers
# ===========================================================================

class TestIncrementalStateHelpers:
    def _get_helpers(self):
        mod = _reload_module("worker.app", {
            "PR_REVIEW_STATE_TABLE": "test-pr-state",
            "IDEMPOTENCY_TABLE": "x",
        })
        return mod._get_last_reviewed_sha, mod._set_last_reviewed_sha, mod._pr_state_key

    def test_get_returns_none_on_missing_key(self):
        get_sha, set_sha, pr_key = self._get_helpers()
        mock_dynamodb = MagicMock()
        mock_dynamodb.get_item.return_value = {}  # no Item
        with patch("worker.app._dynamodb", mock_dynamodb):
            result = get_sha("org/repo", 42)
        assert result is None

    def test_get_returns_sha_when_present(self):
        get_sha, set_sha, pr_key = self._get_helpers()
        mock_dynamodb = MagicMock()
        mock_dynamodb.get_item.return_value = {
            "Item": {"last_reviewed_sha": {"S": "abc123"}}
        }
        with patch("worker.app._dynamodb", mock_dynamodb):
            result = get_sha("org/repo", 42)
        assert result == "abc123"

    def test_set_calls_put_item(self):
        get_sha, set_sha, pr_key = self._get_helpers()
        mock_dynamodb = MagicMock()
        with patch("worker.app._dynamodb", mock_dynamodb):
            set_sha("org/repo", 42, "deadbeef")
        mock_dynamodb.put_item.assert_called_once()
        call_kwargs = mock_dynamodb.put_item.call_args[1]
        assert call_kwargs["Item"]["last_reviewed_sha"]["S"] == "deadbeef"
        assert call_kwargs["Item"]["pr_key"]["S"] == "org/repo:42"
