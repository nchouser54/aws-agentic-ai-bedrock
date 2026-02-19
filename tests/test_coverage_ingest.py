"""Tests for the coverage ingestion Lambda (coverage_ingest/app.py)."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from coverage_ingest.app import (
    FileCoverage,
    _build_coverage_doc,
    _coverage_tier,
    _s3_coverage_key,
    ingest_coverage,
    lambda_handler,
    parse_cobertura,
    parse_lcov,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_COBERTURA_XML = """\
<?xml version="1.0" ?>
<coverage line-rate="0.75" branch-rate="0.5" version="5.5" timestamp="1700000000">
    <packages>
        <package name="src">
            <classes>
                <class name="auth" filename="src/auth.py" line-rate="0.8" branch-rate="0.6">
                    <methods>
                        <method name="verify_token" hits="5">
                            <lines><line number="10" hits="5"/></lines>
                        </method>
                        <method name="refresh_token" hits="0">
                            <lines><line number="30" hits="0"/></lines>
                        </method>
                    </methods>
                    <lines>
                        <line number="10" hits="5"/>
                        <line number="11" hits="5"/>
                        <line number="30" hits="0"/>
                        <line number="31" hits="0"/>
                    </lines>
                </class>
                <class name="models" filename="src/models/user.py" line-rate="0.5" branch-rate="0.0">
                    <lines>
                        <line number="5" hits="0"/>
                        <line number="6" hits="1"/>
                    </lines>
                </class>
            </classes>
        </package>
    </packages>
</coverage>
"""

_LCOV_DATA = """\
SF:src/utils.py
FN:1,my_function
FNDA:3,my_function
FN:10,unused_func
FNDA:0,unused_func
DA:1,3
DA:2,3
DA:10,0
DA:11,0
end_of_record
SF:src/another.py
DA:1,1
end_of_record
"""


# ---------------------------------------------------------------------------
# parse_cobertura
# ---------------------------------------------------------------------------

class TestParseCobertura:
    def test_files_found(self) -> None:
        records = parse_cobertura(_COBERTURA_XML)
        paths = {r.path for r in records}
        assert "src/auth.py" in paths
        assert "src/models/user.py" in paths

    def test_line_rate_parsed(self) -> None:
        records = parse_cobertura(_COBERTURA_XML)
        auth = next(r for r in records if r.path == "src/auth.py")
        assert auth.line_rate == pytest.approx(0.8)

    def test_uncovered_lines_detected(self) -> None:
        records = parse_cobertura(_COBERTURA_XML)
        auth = next(r for r in records if r.path == "src/auth.py")
        assert 30 in auth.uncovered_lines
        assert 31 in auth.uncovered_lines

    def test_uncovered_methods_detected(self) -> None:
        records = parse_cobertura(_COBERTURA_XML)
        auth = next(r for r in records if r.path == "src/auth.py")
        assert "refresh_token" in auth.uncovered_functions

    def test_invalid_xml_raises(self) -> None:
        with pytest.raises(ValueError, match="Invalid Cobertura XML"):
            parse_cobertura("<not valid xml <<<")

    def test_empty_xml(self) -> None:
        records = parse_cobertura("<coverage/>")
        assert records == []


# ---------------------------------------------------------------------------
# parse_lcov
# ---------------------------------------------------------------------------

class TestParseLcov:
    def test_files_found(self) -> None:
        records = parse_lcov(_LCOV_DATA)
        paths = {r.path for r in records}
        assert "src/utils.py" in paths
        assert "src/another.py" in paths

    def test_line_rate_computed(self) -> None:
        records = parse_lcov(_LCOV_DATA)
        utils = next(r for r in records if r.path == "src/utils.py")
        assert utils.lines_valid == 4
        assert utils.lines_covered == 2
        assert utils.line_rate == pytest.approx(0.5)

    def test_uncovered_lines(self) -> None:
        records = parse_lcov(_LCOV_DATA)
        utils = next(r for r in records if r.path == "src/utils.py")
        assert 10 in utils.uncovered_lines
        assert 11 in utils.uncovered_lines

    def test_uncovered_functions(self) -> None:
        records = parse_lcov(_LCOV_DATA)
        utils = next(r for r in records if r.path == "src/utils.py")
        assert "unused_func" in utils.uncovered_functions

    def test_empty_string(self) -> None:
        assert parse_lcov("") == []


# ---------------------------------------------------------------------------
# _coverage_tier
# ---------------------------------------------------------------------------

class TestCoverageTier:
    def test_high(self) -> None:
        assert _coverage_tier(0.9) == "high"
        assert _coverage_tier(0.8) == "high"

    def test_medium(self) -> None:
        assert _coverage_tier(0.6) == "medium"
        assert _coverage_tier(0.5) == "medium"

    def test_low(self) -> None:
        assert _coverage_tier(0.49) == "low"
        assert _coverage_tier(0.0) == "low"


# ---------------------------------------------------------------------------
# _build_coverage_doc
# ---------------------------------------------------------------------------

class TestBuildCoverageDoc:
    def test_required_fields(self) -> None:
        fc = FileCoverage(
            path="src/auth.py",
            line_rate=0.75,
            branch_rate=0.5,
            lines_valid=20,
            lines_covered=15,
            branches_valid=4,
            branches_covered=2,
            uncovered_lines=[10, 11],
            uncovered_functions=["refresh_token"],
        )
        doc = _build_coverage_doc(fc, "owner/repo", "main", "https://github.com")
        assert doc["repo"] == "owner/repo"
        assert doc["path"] == "src/auth.py"
        assert doc["coverage_pct"] == pytest.approx(75.0)
        assert doc["coverage_tier"] == "medium"
        assert "refresh_token" in doc["text"]
        assert "Untested functions" in doc["text"]
        assert doc["source"] == "coverage"


# ---------------------------------------------------------------------------
# _s3_coverage_key
# ---------------------------------------------------------------------------

class TestS3CoverageKey:
    def test_key_structure(self) -> None:
        key = _s3_coverage_key("github", "owner/repo", "main", "src/auth.py")
        assert key.startswith("github/coverage/owner/repo/main/")
        assert key.endswith(".json")

    def test_leading_slash_stripped(self) -> None:
        key = _s3_coverage_key("github", "owner/repo", "main", "/src/auth.py")
        assert "//" not in key


# ---------------------------------------------------------------------------
# ingest_coverage
# ---------------------------------------------------------------------------

class TestIngestCoverage:
    def _make_clients(self) -> tuple[MagicMock, MagicMock]:
        s3 = MagicMock()
        agent = MagicMock()
        agent.start_ingestion_job.return_value = {
            "ingestionJob": {"ingestionJobId": "job-123"}
        }
        return s3, agent

    def test_cobertura_ingests_and_returns_count(self) -> None:
        s3, agent = self._make_clients()
        count, job_id = ingest_coverage(
            coverage_data=_COBERTURA_XML,
            fmt="cobertura",
            repo="owner/repo",
            ref="main",
            bucket="my-bucket",
            knowledge_base_id="kb-id",
            data_source_id="ds-id",
            prefix="github",
            web_base="https://github.com",
            s3_client=s3,
            bedrock_agent=agent,
        )
        assert count == 2
        assert job_id == "job-123"
        assert s3.put_object.call_count == 2
        agent.start_ingestion_job.assert_called_once()

    def test_lcov_ingests(self) -> None:
        s3, agent = self._make_clients()
        count, _ = ingest_coverage(
            coverage_data=_LCOV_DATA,
            fmt="lcov",
            repo="owner/repo",
            ref="main",
            bucket="my-bucket",
            knowledge_base_id="kb-id",
            data_source_id="ds-id",
            prefix="github",
            web_base="https://github.com",
            s3_client=s3,
            bedrock_agent=agent,
        )
        assert count == 2

    def test_empty_cobertura_returns_zero(self) -> None:
        s3, agent = self._make_clients()
        count, job_id = ingest_coverage(
            coverage_data="<coverage/>",
            fmt="cobertura",
            repo="owner/repo",
            ref="main",
            bucket="b",
            knowledge_base_id="kb",
            data_source_id="ds",
            prefix="p",
            web_base="https://github.com",
            s3_client=s3,
            bedrock_agent=agent,
        )
        assert count == 0
        assert job_id == ""
        agent.start_ingestion_job.assert_not_called()


# ---------------------------------------------------------------------------
# lambda_handler
# ---------------------------------------------------------------------------

class TestLambdaHandler:
    def _event(self, body: dict) -> dict:
        return {
            "requestContext": {"http": {"method": "POST"}},
            "body": json.dumps(body),
        }

    def test_missing_repo_returns_400(self) -> None:
        resp = lambda_handler(self._event({"ref": "main", "coverage_data": "x"}), None)
        assert resp["statusCode"] == 400

    def test_missing_coverage_data_returns_400(self) -> None:
        resp = lambda_handler(self._event({"repo": "o/r", "ref": "main"}), None)
        assert resp["statusCode"] == 400

    def test_invalid_format_returns_400(self) -> None:
        resp = lambda_handler(
            self._event({"repo": "o/r", "ref": "main", "format": "jacoco", "coverage_data": "x"}),
            None,
        )
        assert resp["statusCode"] == 400

    def test_get_returns_405(self) -> None:
        event = {"requestContext": {"http": {"method": "GET"}}, "body": "{}"}
        resp = lambda_handler(event, None)
        assert resp["statusCode"] == 405

    def test_invalid_json_returns_400(self) -> None:
        event = {"requestContext": {"http": {"method": "POST"}}, "body": "not json"}
        resp = lambda_handler(event, None)
        assert resp["statusCode"] == 400

    @patch("coverage_ingest.app.boto3")
    @patch.dict(
        "os.environ",
        {
            "KB_SYNC_BUCKET": "my-bucket",
            "BEDROCK_KNOWLEDGE_BASE_ID": "kb-id",
            "BEDROCK_KB_DATA_SOURCE_ID": "ds-id",
        },
    )
    def test_successful_ingest(self, mock_boto3: MagicMock) -> None:
        mock_s3 = MagicMock()
        mock_agent = MagicMock()
        mock_agent.start_ingestion_job.return_value = {
            "ingestionJob": {"ingestionJobId": "job-abc"}
        }
        mock_boto3.client.side_effect = lambda svc, **_: mock_s3 if svc == "s3" else mock_agent

        resp = lambda_handler(
            self._event({
                "repo": "owner/repo",
                "ref": "main",
                "format": "cobertura",
                "coverage_data": _COBERTURA_XML,
            }),
            None,
        )
        assert resp["statusCode"] == 200
        body = json.loads(resp["body"])
        assert body["status"] == "ingested"
        assert body["files_processed"] == 2
