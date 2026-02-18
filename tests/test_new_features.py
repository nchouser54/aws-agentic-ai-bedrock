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


# ===========================================================================
# Ticket Compliance — render_check_run_body section
# ===========================================================================

class TestRenderTicketCompliance:
    def _render(self, ticket_compliance=None):
        from worker.render_markdown import render_check_run_body
        review = {
            "summary": "Implements the Jira requirements.",
            "overall_risk": "low",
            "findings": [],
            "files_reviewed": ["app.py"],
            "files_skipped": [],
            "ticket_compliance": ticket_compliance,
        }
        return render_check_run_body(review)

    def test_section_absent_when_none(self):
        body = self._render(ticket_compliance=None)
        assert "Jira Ticket Compliance" not in body

    def test_section_absent_when_empty_list(self):
        body = self._render(ticket_compliance=[])
        assert "Jira Ticket Compliance" not in body

    def test_section_present_with_ticket(self):
        body = self._render(ticket_compliance=[{
            "ticket_key": "PROJ-99",
            "ticket_summary": "Add login endpoint",
            "fully_compliant": ["Login endpoint added"],
            "not_compliant": ["Logout not implemented"],
            "needs_human_verification": ["Browser redirect check"],
        }])
        assert "Jira Ticket Compliance" in body
        assert "PROJ-99" in body
        assert "Add login endpoint" in body

    def test_compliant_items_rendered(self):
        body = self._render(ticket_compliance=[{
            "ticket_key": "PROJ-1",
            "ticket_summary": "Refactor auth",
            "fully_compliant": ["Token refresh added", "Session invalidation fixed"],
            "not_compliant": [],
            "needs_human_verification": [],
        }])
        assert "✅ Compliant" in body
        assert "Token refresh added" in body
        assert "Session invalidation fixed" in body
        assert "❌ Not compliant" not in body

    def test_not_compliant_items_rendered(self):
        body = self._render(ticket_compliance=[{
            "ticket_key": "PROJ-2",
            "ticket_summary": "Add rate limiting",
            "fully_compliant": [],
            "not_compliant": ["Burst limit not enforced"],
            "needs_human_verification": [],
        }])
        assert "❌ Not compliant" in body
        assert "Burst limit not enforced" in body

    def test_needs_human_verification_rendered(self):
        body = self._render(ticket_compliance=[{
            "ticket_key": "PROJ-3",
            "ticket_summary": "Payment flow",
            "fully_compliant": [],
            "not_compliant": [],
            "needs_human_verification": ["Manual Stripe sandbox test required"],
        }])
        assert "🔍 Needs human verification" in body
        assert "Manual Stripe sandbox test required" in body

    def test_multiple_tickets_rendered(self):
        body = self._render(ticket_compliance=[
            {
                "ticket_key": "ALPHA-1",
                "ticket_summary": "First ticket",
                "fully_compliant": ["Done"],
                "not_compliant": [],
                "needs_human_verification": [],
            },
            {
                "ticket_key": "ALPHA-2",
                "ticket_summary": "Second ticket",
                "fully_compliant": [],
                "not_compliant": ["Not done"],
                "needs_human_verification": [],
            },
        ])
        assert "ALPHA-1" in body
        assert "ALPHA-2" in body
        assert "First ticket" in body
        assert "Second ticket" in body


# ===========================================================================
# check_run rerequested, labeled trigger, dedup, review_trigger_labels
# ===========================================================================

def _make_webhook_event(github_event: str, body_dict: dict, secret: str = "s3cr3t") -> dict:
    """Build a minimal Lambda proxy event for the webhook receiver."""
    import hashlib
    import hmac
    import json as _json

    body = _json.dumps(body_dict)
    sig = "sha256=" + hmac.new(secret.encode(), body.encode(), hashlib.sha256).hexdigest()
    return {
        "headers": {
            "X-GitHub-Event": github_event,
            "X-GitHub-Delivery": "abc-123",
            "X-Hub-Signature-256": sig,
        },
        "body": body,
        "isBase64Encoded": False,
    }


def _load_webhook(env_overrides: dict | None = None):
    env_base = {
        "WEBHOOK_SECRET_ARN": "arn:aws:secretsmanager:us-east-1:123:secret:test",
        "QUEUE_URL": "https://sqs.us-east-1.amazonaws.com/123/queue",
        "GITHUB_APP_IDS_SECRET_ARN": "arn:aws:secretsmanager:us-east-1:123:secret:ids",
        "GITHUB_APP_PRIVATE_KEY_SECRET_ARN": "arn:aws:secretsmanager:us-east-1:123:secret:key",
    }
    if env_overrides:
        env_base.update(env_overrides)
    mod = _reload_module("webhook_receiver.app", env_base)
    return mod


class TestCheckRunRerequested:
    """check_run rerequested event triggers a review."""

    def _run(self, action="rerequested", check_run_name="AI PR Reviewer", pr_list=None, env=None):
        if pr_list is None:
            pr_list = [{"number": 42, "head": {"sha": "abc123"}}]
        payload = {
            "action": action,
            "check_run": {"name": check_run_name, "pull_requests": pr_list},
            "repository": {"full_name": "org/repo"},
            "installation": {"id": 99},
        }
        extra_env = env or {}
        mod = _load_webhook(extra_env)
        secret = b"s3cr3t"
        env_runtime = {
            "QUEUE_URL": "https://sqs.us-east-1.amazonaws.com/123/queue",
            "WEBHOOK_SECRET_ARN": "arn:aws:secretsmanager:us-east-1:123:secret:test",
            "GITHUB_APP_IDS_SECRET_ARN": "arn:aws:secretsmanager:us-east-1:123:secret:ids",
            "GITHUB_APP_PRIVATE_KEY_SECRET_ARN": "arn:aws:secretsmanager:us-east-1:123:secret:key",
        }
        env_runtime.update(extra_env)
        with (
            patch("webhook_receiver.app._load_webhook_secret", return_value=secret),
            patch("webhook_receiver.app._sqs") as mock_sqs,
            patch.dict(os.environ, env_runtime),
        ):
            event = _make_webhook_event("check_run", payload)
            result = mod.lambda_handler(event, None)
        return result, mock_sqs

    def test_rerequested_enqueues_review(self):
        result, mock_sqs = self._run()
        import json as _json
        assert result["statusCode"] == 202
        assert _json.loads(result["body"])["status"] == "accepted"
        mock_sqs.send_message.assert_called_once()

    def test_non_rerequested_action_ignored(self):
        result, mock_sqs = self._run(action="created")
        assert result["statusCode"] == 202
        import json as _json
        assert "ignored" in _json.loads(result["body"])
        mock_sqs.send_message.assert_not_called()

    def test_wrong_check_run_name_ignored(self):
        result, mock_sqs = self._run(check_run_name="Other Bot")
        assert result["statusCode"] == 202
        import json as _json
        assert "not_our_check_run" in _json.loads(result["body"])["ignored"]
        mock_sqs.send_message.assert_not_called()

    def test_no_pull_requests_ignored(self):
        result, mock_sqs = self._run(pr_list=[])
        assert result["statusCode"] == 202
        mock_sqs.send_message.assert_not_called()

    def test_check_run_event_not_delivered_for_other_events(self):
        """Non-check_run events still work normally (regression guard)."""
        mod = _load_webhook()
        secret = b"s3cr3t"
        with patch("webhook_receiver.app._load_webhook_secret", return_value=secret):
            event = _make_webhook_event("push", {"ref": "refs/heads/main"})
            result = mod.lambda_handler(event, None)
        import json as _json
        assert result["statusCode"] == 202
        assert "ignored" in _json.loads(result["body"])


class TestLabeledTrigger:
    """pull_request labeled action triggers a review only for configured labels."""

    def _pr_payload(self, label_name="needs-ai-review"):
        return {
            "action": "labeled",
            "label": {"name": label_name},
            "pull_request": {"number": 7, "head": {"sha": "deadbeef"}},
            "repository": {"full_name": "org/repo"},
            "installation": {"id": 1},
        }

    def test_labeled_with_matching_trigger_label_enqueues(self):
        mod = _load_webhook({"REVIEW_TRIGGER_LABELS": "needs-ai-review"})
        secret = b"s3cr3t"
        with (
            patch("webhook_receiver.app._load_webhook_secret", return_value=secret),
            patch("webhook_receiver.app._sqs") as mock_sqs,
            patch.dict(os.environ, {"QUEUE_URL": "https://sqs.us-east-1.amazonaws.com/123/queue", "REVIEW_TRIGGER_LABELS": "needs-ai-review"}),
        ):
            event = _make_webhook_event("pull_request", self._pr_payload("needs-ai-review"))
            result = mod.lambda_handler(event, None)
        import json as _json
        assert result["statusCode"] == 202
        assert _json.loads(result["body"])["status"] == "accepted"
        mock_sqs.send_message.assert_called_once()

    def test_labeled_with_non_trigger_label_ignored(self):
        mod = _load_webhook({"REVIEW_TRIGGER_LABELS": "needs-ai-review"})
        secret = b"s3cr3t"
        with (
            patch("webhook_receiver.app._load_webhook_secret", return_value=secret),
            patch("webhook_receiver.app._sqs") as mock_sqs,
            patch.dict(os.environ, {"QUEUE_URL": "https://sqs.us-east-1.amazonaws.com/123/queue", "REVIEW_TRIGGER_LABELS": "needs-ai-review"}),
        ):
            event = _make_webhook_event("pull_request", self._pr_payload("documentation"))
            result = mod.lambda_handler(event, None)
        import json as _json
        assert result["statusCode"] == 202
        assert "label_not_in_trigger_set" in _json.loads(result["body"])["ignored"]
        mock_sqs.send_message.assert_not_called()

    def test_labeled_with_empty_trigger_labels_allows_any(self):
        """When REVIEW_TRIGGER_LABELS is empty, any label-action triggers review."""
        mod = _load_webhook({"REVIEW_TRIGGER_LABELS": ""})
        secret = b"s3cr3t"
        with (
            patch("webhook_receiver.app._load_webhook_secret", return_value=secret),
            patch("webhook_receiver.app._sqs") as mock_sqs,
            patch.dict(os.environ, {"QUEUE_URL": "https://sqs.us-east-1.amazonaws.com/123/queue", "REVIEW_TRIGGER_LABELS": ""}),
        ):
            event = _make_webhook_event("pull_request", self._pr_payload("random-label"))
            result = mod.lambda_handler(event, None)
        import json as _json
        assert result["statusCode"] == 202
        assert _json.loads(result["body"])["status"] == "accepted"
        mock_sqs.send_message.assert_called_once()


class TestSqsDeduplication:
    """_enqueue_review sends MessageDeduplicationId on FIFO queues."""

    def _enqueue(self, queue_url: str):
        mod = _load_webhook({"QUEUE_URL": queue_url})
        secret = b"s3cr3t"
        with (
            patch("webhook_receiver.app._load_webhook_secret", return_value=secret),
            patch("webhook_receiver.app._sqs") as mock_sqs,
            patch.dict(os.environ, {"QUEUE_URL": queue_url}),
        ):
            payload = {
                "action": "opened",
                "pull_request": {"number": 1, "head": {"sha": "sha1"}},
                "repository": {"full_name": "org/repo"},
                "installation": {"id": 5},
            }
            event = _make_webhook_event("pull_request", payload)
            mod.lambda_handler(event, None)
        return mock_sqs.send_message.call_args_list

    def test_fifo_queue_gets_dedup_id(self):
        calls = self._enqueue("https://sqs.us-east-1.amazonaws.com/123/queue.fifo")
        assert len(calls) == 1
        kwargs = calls[0].kwargs or calls[0][1]
        assert "MessageDeduplicationId" in kwargs
        assert "MessageGroupId" in kwargs

    def test_standard_queue_no_dedup_id(self):
        calls = self._enqueue("https://sqs.us-east-1.amazonaws.com/123/standard-queue")
        assert len(calls) == 1
        kwargs = calls[0].kwargs or calls[0][1]
        assert "MessageDeduplicationId" not in kwargs
        assert "MessageGroupId" not in kwargs


class TestReviewTriggerLabelsWorkerFilter:
    """Worker _should_skip_review respects REVIEW_TRIGGER_LABELS."""

    def _get_fn(self, review_trigger_labels=""):
        mod = _reload_module("worker.app", {
            "FAILURE_ON_SEVERITY": "high",
            "PR_REVIEW_STATE_TABLE": "",
            "IDEMPOTENCY_TABLE": "x",
            "REVIEW_TRIGGER_LABELS": review_trigger_labels,
        })
        return mod._should_skip_review

    def _pr(self, labels=None):
        return {"labels": [{"name": lb} for lb in (labels or [])]}

    def test_no_trigger_labels_configured_never_skips(self):
        fn = self._get_fn("")
        skip, _ = fn(self._pr(["anything"]), "opened", "auto")
        assert not skip

    def test_pr_has_required_label_not_skipped(self):
        fn = self._get_fn("needs-ai-review")
        skip, _ = fn(self._pr(["needs-ai-review", "bug"]), "labeled", "auto")
        assert not skip

    def test_pr_missing_required_label_skipped(self):
        fn = self._get_fn("needs-ai-review")
        skip, reason = fn(self._pr(["bug"]), "opened", "auto")
        assert skip
        assert "needs-ai-review" in reason

    def test_manual_trigger_bypasses_label_check(self):
        fn = self._get_fn("needs-ai-review")
        skip, _ = fn(self._pr([]), "opened", "manual")
        assert not skip

    def test_rerun_trigger_bypasses_label_check(self):
        fn = self._get_fn("needs-ai-review")
        skip, _ = fn(self._pr([]), "rerequested", "rerun")
        assert not skip
