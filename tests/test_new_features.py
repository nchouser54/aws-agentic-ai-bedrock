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


# ===========================================================================
# Skip draft PRs
# ===========================================================================

class TestSkipDraftPRs:
    def _get_fn(self, skip_draft_prs="true", extra_env=None):
        env = {
            "FAILURE_ON_SEVERITY": "high",
            "PR_REVIEW_STATE_TABLE": "",
            "IDEMPOTENCY_TABLE": "x",
            "SKIP_DRAFT_PRS": skip_draft_prs,
        }
        if extra_env:
            env.update(extra_env)
        mod = _reload_module("worker.app", env)
        return mod._should_skip_review

    def _pr(self, draft=False):
        return {"draft": draft, "labels": []}

    def test_draft_pr_skipped_by_default(self):
        fn = self._get_fn("true")
        skip, reason = fn(self._pr(draft=True), "opened", "auto")
        assert skip
        assert "draft" in reason.lower()

    def test_non_draft_pr_not_skipped(self):
        fn = self._get_fn("true")
        skip, _ = fn(self._pr(draft=False), "opened", "auto")
        assert not skip

    def test_draft_skip_disabled_allows_draft(self):
        fn = self._get_fn("false")
        skip, _ = fn(self._pr(draft=True), "opened", "auto")
        assert not skip

    def test_manual_trigger_bypasses_draft_skip(self):
        fn = self._get_fn("true")
        skip, _ = fn(self._pr(draft=True), "opened", "manual")
        assert not skip

    def test_rerun_trigger_bypasses_draft_skip(self):
        fn = self._get_fn("true")
        skip, _ = fn(self._pr(draft=True), "rerequested", "rerun")
        assert not skip


# ===========================================================================
# KB-augmented reviews
# ===========================================================================

class TestFetchKbContext:
    """Unit tests for _fetch_kb_context in worker.app."""

    def _get_fn(self):
        mod = _reload_module("worker.app", {
            "FAILURE_ON_SEVERITY": "high",
            "PR_REVIEW_STATE_TABLE": "",
            "IDEMPOTENCY_TABLE": "x",
        })
        return mod._fetch_kb_context

    def test_empty_query_returns_empty(self):
        fn = self._get_fn()
        result = fn("", "us-east-1", "kb-123")
        assert result == []

    def test_empty_kb_id_returns_empty(self):
        fn = self._get_fn()
        result = fn("some query", "us-east-1", "")
        assert result == []

    def test_kb_results_returned_and_trimmed(self):
        fn = self._get_fn()
        mock_kb = MagicMock()
        mock_kb.retrieve.return_value = [
            {"text": "Use dependency injection everywhere.", "uri": "s3://docs/standards.md", "score": 0.9},
            {"text": "All SQL queries must use parameterized statements.", "uri": "s3://docs/security.md", "score": 0.85},
        ]
        with patch("worker.app.BedrockKnowledgeBaseClient", return_value=mock_kb):
            result = fn("add user auth", "us-east-1", "kb-123", top_k=5, max_chars=1000)
        assert len(result) == 2
        assert result[0]["text"] == "Use dependency injection everywhere."
        assert result[0]["uri"] == "s3://docs/standards.md"

    def test_kb_results_clipped_to_max_chars(self):
        fn = self._get_fn()
        mock_kb = MagicMock()
        long_text = "x" * 200
        mock_kb.retrieve.return_value = [
            {"text": long_text, "uri": "s3://docs/a.md", "score": 0.9},
            {"text": long_text, "uri": "s3://docs/b.md", "score": 0.8},
        ]
        with patch("worker.app.BedrockKnowledgeBaseClient", return_value=mock_kb):
            result = fn("query", "us-east-1", "kb-123", top_k=5, max_chars=250)
        total_chars = sum(len(r["text"]) for r in result)
        assert total_chars <= 250

    def test_kb_exception_returns_empty(self):
        fn = self._get_fn()
        mock_kb = MagicMock()
        mock_kb.retrieve.side_effect = RuntimeError("throttled")
        with patch("worker.app.BedrockKnowledgeBaseClient", return_value=mock_kb):
            result = fn("query", "us-east-1", "kb-123")
        assert result == []


class TestBuildContextKbPassages:
    """build_pr_context should embed kb_passages into the returned context."""

    def _build(self, kb_passages=None):
        import importlib
        mod = importlib.import_module("worker.build_context")
        pr = {
            "title": "Add OAuth2 login",
            "body": "Closes PROJ-42",
            "base": {"ref": "main"},
            "head": {"ref": "feature/oauth"},
        }
        files = [{"filename": "auth.py", "status": "modified", "additions": 20, "deletions": 5, "changes": 25, "patch": "@@ -1,5 +1,6 @@\n+import jwt"}]
        return mod.build_pr_context(pr, files, kb_passages=kb_passages)

    def test_no_kb_passages_not_in_context(self):
        context, _, _ = self._build(kb_passages=None)
        assert "org_knowledge_base" not in context

    def test_empty_kb_passages_not_in_context(self):
        context, _, _ = self._build(kb_passages=[])
        assert "org_knowledge_base" not in context

    def test_kb_passages_embedded_in_context(self):
        passages = [{"text": "Use parameterized queries.", "uri": "s3://docs/sql.md", "score": 0.9}]
        context, _, _ = self._build(kb_passages=passages)
        assert "org_knowledge_base" in context
        assert context["org_knowledge_base"][0]["text"] == "Use parameterized queries."

    def test_kb_passages_alongside_jira(self):
        passages = [{"text": "Rate limit all endpoints.", "uri": "s3://docs/ratelimit.md", "score": 0.8}]
        import importlib
        mod = importlib.import_module("worker.build_context")
        pr = {"title": "T", "body": "", "base": {"ref": "main"}, "head": {"ref": "feat"}}
        files = [{"filename": "api.py", "status": "modified", "additions": 1, "deletions": 0, "changes": 1, "patch": "+pass"}]
        jira = [{"key": "PROJ-1", "summary": "Rate limiting", "status": "In Progress", "type": "Story", "description": ""}]
        context, _, _ = mod.build_pr_context(pr, files, jira_issues=jira, kb_passages=passages)
        assert "linked_jira_issues" in context
        assert "org_knowledge_base" in context


class TestBuildPromptKbPassages:
    """_build_prompt should embed kb_passages as org_knowledge_base."""

    def _get_fn(self):
        mod = _reload_module("worker.app", {
            "FAILURE_ON_SEVERITY": "high",
            "PR_REVIEW_STATE_TABLE": "",
            "IDEMPOTENCY_TABLE": "x",
        })
        return mod._build_prompt

    def test_no_kb_passages_no_key(self):
        import json
        fn = self._get_fn()
        pr = {"title": "T", "body": "", "base": {"ref": "main"}, "head": {"ref": "feat"}}
        result = json.loads(fn(pr, []))
        assert "org_knowledge_base" not in result

    def test_kb_passages_included(self):
        import json
        fn = self._get_fn()
        pr = {"title": "T", "body": "", "base": {"ref": "main"}, "head": {"ref": "feat"}}
        passages = [{"text": "Always use HTTPS.", "uri": "s3://docs/sec.md", "score": 0.95}]
        result = json.loads(fn(pr, [], kb_passages=passages))
        assert "org_knowledge_base" in result
        assert result["org_knowledge_base"][0]["text"] == "Always use HTTPS."
        # hard_rules should mention the KB
        assert any("org_knowledge_base" in rule or "coding standards" in rule for rule in result["hard_rules"])


# ===========================================================================
# Batch-8 features
# ===========================================================================

import base64
import hashlib
import hmac
import json as _json
import logging
import time

# ---------------------------------------------------------------------------
# Helpers for webhook tests
# ---------------------------------------------------------------------------

def _make_replay_event(
    github_event: str = "pull_request",
    age_seconds: float = 0,
    body: dict | None = None,
    secret: bytes = b"secret",
    signature: str | None = None,
    include_request_context: bool = True,
) -> dict:
    """Build an API-Gateway-like event for webhook_receiver.lambda_handler."""
    if body is None:
        body = {
            "action": "opened",
            "pull_request": {
                "number": 1,
                "draft": False,
                "title": "test",
                "body": "",
                "head": {"sha": "abc123", "ref": "feat/x"},
                "base": {"ref": "main"},
                "user": {"login": "tester"},
                "labels": [],
            },
            "repository": {"full_name": "org/repo"},
            "sender": {"login": "tester"},
        }
    raw_body = _json.dumps(body).encode()
    sig = signature or ("sha256=" + hmac.new(secret, raw_body, hashlib.sha256).hexdigest())
    epoch_ms = int((time.time() - age_seconds) * 1000)
    event: dict = {
        "headers": {
            "X-GitHub-Event": github_event,
            "X-GitHub-Delivery": "delivery-123",
            "X-Hub-Signature-256": sig,
        },
        "body": raw_body.decode(),
        "isBase64Encoded": False,
    }
    if include_request_context:
        event["requestContext"] = {"timeEpoch": epoch_ms}
    return event


# ---------------------------------------------------------------------------
# 1. Webhook replay-attack window (MAX_WEBHOOK_AGE_SECONDS)
# ---------------------------------------------------------------------------

class TestWebhookReplayWindow:
    """MAX_WEBHOOK_AGE_SECONDS replay-attack protection."""

    def _invoke(
        self,
        age_seconds: float,
        max_age: int = 300,
        include_request_context: bool = True,
    ) -> dict:
        secret = b"testsecret"
        event = _make_replay_event(
            age_seconds=age_seconds,
            secret=secret,
            include_request_context=include_request_context,
        )
        with (
            patch("webhook_receiver.app.MAX_WEBHOOK_AGE_SECONDS", max_age),
            patch("webhook_receiver.app._load_webhook_secret", return_value=secret),
            patch("webhook_receiver.app._sqs") as mock_sqs,
            patch.dict("os.environ", {"QUEUE_URL": "https://sqs.test/queue"}),
        ):
            mock_sqs.send_message.return_value = {}
            from webhook_receiver.app import lambda_handler
            return lambda_handler(event, None)

    def test_fresh_webhook_accepted(self):
        resp = self._invoke(age_seconds=10)
        assert resp["statusCode"] == 202

    def test_stale_webhook_rejected(self):
        resp = self._invoke(age_seconds=400)
        assert resp["statusCode"] == 400
        body = _json.loads(resp["body"])
        assert body["error"] == "webhook_too_old"

    def test_replay_check_disabled_when_zero(self):
        """MAX_WEBHOOK_AGE_SECONDS=0 must never reject even a very old delivery."""
        resp = self._invoke(age_seconds=9999, max_age=0)
        assert resp["statusCode"] == 202

    def test_missing_request_context_skips_check(self):
        """No requestContext → skip check, proceed normally."""
        resp = self._invoke(age_seconds=9999, include_request_context=False)
        assert resp["statusCode"] == 202


# ---------------------------------------------------------------------------
# 6. pull_request_review_comment early-return filter
# ---------------------------------------------------------------------------

class TestPullRequestReviewCommentFilter:
    """pull_request_review_comment events must be silently ignored (202)."""

    def test_review_comment_event_returns_202(self):
        secret = b"testsecret"
        event = _make_replay_event(github_event="pull_request_review_comment", secret=secret)
        with patch("webhook_receiver.app._load_webhook_secret", return_value=secret):
            from webhook_receiver.app import lambda_handler
            resp = lambda_handler(event, None)
        assert resp["statusCode"] == 202
        body = _json.loads(resp["body"])
        assert body.get("ignored") == "pull_request_review_comment_event"

    def test_review_comment_event_does_not_enqueue(self):
        secret = b"testsecret"
        event = _make_replay_event(github_event="pull_request_review_comment", secret=secret)
        with (
            patch("webhook_receiver.app._load_webhook_secret", return_value=secret),
            patch("webhook_receiver.app._sqs") as mock_sqs,
        ):
            from webhook_receiver.app import lambda_handler
            lambda_handler(event, None)
        mock_sqs.send_message.assert_not_called()


# ---------------------------------------------------------------------------
# 5. Token cost tracking — bedrock_client returns (result, in_tok, out_tok)
# ---------------------------------------------------------------------------

class TestTokenTracking:
    """_invoke_model_with_system returns a (text, input_tokens, output_tokens) tuple."""

    def _make_runtime(self, in_tok: int = 150, out_tok: int = 50, include_usage: bool = True):
        runtime = MagicMock()
        payload: dict = {"content": [{"text": "{}"}]}
        if include_usage:
            payload["usage"] = {"input_tokens": in_tok, "output_tokens": out_tok}

        class _Body:
            def read(self):
                return _json.dumps(payload).encode()

        runtime.invoke_model.return_value = {"body": _Body()}
        return runtime

    def test_returns_tuple_with_token_counts(self):
        from shared.bedrock_client import BedrockReviewClient
        runtime = self._make_runtime(in_tok=100, out_tok=40)
        client = BedrockReviewClient(
            region="us-gov-west-1",
            model_id="anthropic.model",
            agent_runtime=MagicMock(),
            bedrock_runtime=runtime,
        )
        text, in_tok, out_tok = client._invoke_model_with_system(
            system="sys",
            messages=[{"role": "user", "content": "hi"}],
            model_id="anthropic.model",
        )
        assert isinstance(text, str)
        assert in_tok == 100
        assert out_tok == 40

    def test_missing_usage_yields_zeros(self):
        from shared.bedrock_client import BedrockReviewClient
        runtime = self._make_runtime(include_usage=False)
        client = BedrockReviewClient(
            region="us-gov-west-1",
            model_id="anthropic.model",
            agent_runtime=MagicMock(),
            bedrock_runtime=runtime,
        )
        _, in_tok, out_tok = client._invoke_model_with_system(
            system="sys",
            messages=[{"role": "user", "content": "hi"}],
            model_id="anthropic.model",
        )
        assert in_tok == 0
        assert out_tok == 0


# ---------------------------------------------------------------------------
# 7. Per-repo .ai-reviewer.yml config (_load_repo_config)
# ---------------------------------------------------------------------------

class TestLoadRepoConfig:
    """_load_repo_config fetches .ai-reviewer.yml and returns filtered dict."""

    def _gh(self, content: str | None, status_code: int = 200):
        gh = MagicMock()
        resp = MagicMock()
        resp.status_code = status_code
        if content is not None:
            encoded = base64.b64encode(content.encode()).decode()
            resp.json.return_value = {"content": encoded}
        else:
            resp.json.return_value = {}
        gh._request.return_value = resp
        return gh

    def test_valid_config_loaded(self):
        from worker.app import _load_repo_config
        yaml_content = (
            "failure_on_severity: medium\n"
            "skip_draft_prs: false\n"
            "post_review_comment: true\n"
        )
        gh = self._gh(yaml_content)
        cfg = _load_repo_config(gh, "org", "repo", "main")
        assert cfg["failure_on_severity"] == "medium"
        assert cfg["skip_draft_prs"] == "false"
        assert cfg["post_review_comment"] == "true"

    def test_missing_file_returns_empty_dict(self):
        from worker.app import _load_repo_config
        gh = self._gh(None, status_code=404)
        cfg = _load_repo_config(gh, "org", "repo", "main")
        assert cfg == {}

    def test_unknown_keys_ignored(self):
        from worker.app import _load_repo_config
        yaml_content = "secret_key: value\nfailure_on_severity: high\n"
        gh = self._gh(yaml_content)
        cfg = _load_repo_config(gh, "org", "repo", "main")
        assert "secret_key" not in cfg
        assert cfg["failure_on_severity"] == "high"

    def test_exception_returns_empty_dict(self):
        from worker.app import _load_repo_config
        gh = MagicMock()
        gh._request.side_effect = RuntimeError("network error")
        cfg = _load_repo_config(gh, "org", "repo", "main")
        assert cfg == {}

    def test_comment_lines_skipped(self):
        from worker.app import _load_repo_config
        yaml_content = "# this is a comment\nfailure_on_severity: low\n"
        gh = self._gh(yaml_content)
        cfg = _load_repo_config(gh, "org", "repo", "main")
        assert cfg.get("failure_on_severity") == "low"
        assert len(cfg) == 1

    def test_quoted_values_stripped(self):
        from worker.app import _load_repo_config
        yaml_content = 'failure_on_severity: "critical"\n'
        gh = self._gh(yaml_content)
        cfg = _load_repo_config(gh, "org", "repo", "main")
        assert cfg["failure_on_severity"] == "critical"

    def test_post_review_comment_true_parses(self):
        from worker.app import _load_repo_config
        gh = self._gh("post_review_comment: true\n")
        cfg = _load_repo_config(gh, "org", "repo", "feat/x")
        assert cfg.get("post_review_comment") == "true"

    def test_post_review_comment_false_parses(self):
        from worker.app import _load_repo_config
        gh = self._gh("post_review_comment: false\n")
        cfg = _load_repo_config(gh, "org", "repo", "feat/x")
        assert cfg.get("post_review_comment") == "false"


# ---------------------------------------------------------------------------
# 8. Review history — _set_last_reviewed_sha / _get_review_history
# ---------------------------------------------------------------------------

class TestReviewHistoryEnrichment:
    """Enriched DynamoDB schema stores and retrieves full review metadata."""

    def test_set_stores_enriched_fields(self):
        from worker.app import _set_last_reviewed_sha
        ddb = MagicMock()
        with (
            patch("worker.app._dynamodb", ddb),
            patch("worker.app.PR_REVIEW_STATE_TABLE", "state-table"),
        ):
            _set_last_reviewed_sha(
                "org/repo", 42, "deadbeef",
                overall_risk="high",
                finding_count=3,
                verdict="FAIL",
                input_tokens=500,
                output_tokens=200,
            )
        ddb.put_item.assert_called_once()
        item = ddb.put_item.call_args.kwargs["Item"]
        assert item["overall_risk"]["S"] == "high"
        assert item["finding_count"]["N"] == "3"
        assert item["verdict"]["S"] == "FAIL"
        assert item["input_tokens"]["N"] == "500"
        assert item["output_tokens"]["N"] == "200"
        assert item["last_reviewed_sha"]["S"] == "deadbeef"

    def test_set_noop_when_no_table(self):
        from worker.app import _set_last_reviewed_sha
        ddb = MagicMock()
        with (
            patch("worker.app._dynamodb", ddb),
            patch("worker.app.PR_REVIEW_STATE_TABLE", ""),
        ):
            _set_last_reviewed_sha("org/repo", 1, "abc")
        ddb.put_item.assert_not_called()

    def test_get_returns_history_dict(self):
        from worker.app import _get_review_history
        ddb = MagicMock()
        ddb.get_item.return_value = {
            "Item": {
                "pr_key": {"S": "org/repo#1"},
                "last_reviewed_sha": {"S": "abc123"},
                "updated_at": {"N": "1700000000"},
                "overall_risk": {"S": "medium"},
                "finding_count": {"N": "2"},
                "verdict": {"S": "PASS"},
                "input_tokens": {"N": "300"},
                "output_tokens": {"N": "100"},
            }
        }
        with (
            patch("worker.app._dynamodb", ddb),
            patch("worker.app.PR_REVIEW_STATE_TABLE", "state-table"),
        ):
            history = _get_review_history("org/repo", 1)
        assert history is not None
        assert history["overall_risk"] == "medium"
        assert history["finding_count"] == 2
        assert history["verdict"] == "PASS"
        assert history["input_tokens"] == 300
        assert history["output_tokens"] == 100

    def test_get_returns_none_when_no_table(self):
        from worker.app import _get_review_history
        with patch("worker.app.PR_REVIEW_STATE_TABLE", ""):
            result = _get_review_history("org/repo", 1)
        assert result is None

    def test_get_returns_none_when_item_absent(self):
        from worker.app import _get_review_history
        ddb = MagicMock()
        ddb.get_item.return_value = {"Item": {}}
        with (
            patch("worker.app._dynamodb", ddb),
            patch("worker.app.PR_REVIEW_STATE_TABLE", "state-table"),
        ):
            result = _get_review_history("org/repo", 99)
        assert result is None

    def test_get_returns_none_on_exception(self, caplog):
        from worker.app import _get_review_history
        ddb = MagicMock()
        ddb.get_item.side_effect = RuntimeError("ddb down")
        with (
            patch("worker.app._dynamodb", ddb),
            patch("worker.app.PR_REVIEW_STATE_TABLE", "state-table"),
            caplog.at_level(logging.WARNING),
        ):
            result = _get_review_history("org/repo", 1)
        assert result is None
