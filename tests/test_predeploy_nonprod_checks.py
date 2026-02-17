from __future__ import annotations

import importlib.util
from pathlib import Path


_SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "predeploy_nonprod_checks.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("predeploy_nonprod_checks", _SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_parse_tfvars_strips_inline_comments(tmp_path: Path) -> None:
    mod = _load_module()
    tfvars = tmp_path / "sample.tfvars"
    tfvars.write_text(
        '\n'.join(
            [
                'aws_region = "us-gov-west-1" # inline comment',
                'name = "value-with-#-inside"',
                'enabled = true',
            ]
        )
    )

    parsed = mod._parse_tfvars(tfvars)
    assert parsed["aws_region"] == "us-gov-west-1"
    assert parsed["name"] == "value-with-#-inside"
    assert parsed["enabled"] == "true"


def test_extract_list_values_from_tfvars_multiline(tmp_path: Path) -> None:
    mod = _load_module()
    tfvars = tmp_path / "list.tfvars"
    tfvars.write_text(
        '\n'.join(
            [
                'webapp_tls_subnet_ids = [',
                '  "subnet-aaa",',
                '  "subnet-bbb"',
                ']',
            ]
        )
    )

    assert mod._extract_list_values_from_tfvars(tfvars, "webapp_tls_subnet_ids") == ["subnet-aaa", "subnet-bbb"]


def test_main_aws_checks_fails_when_secret_missing(tmp_path: Path, monkeypatch) -> None:
    mod = _load_module()
    tfvars = tmp_path / "nonprod.tfvars"
    tfvars.write_text(
        '\n'.join(
            [
                'environment = "nonprod"',
                'create_secrets_manager_secrets = true',
                'chatbot_retrieval_mode = "hybrid"',
                'existing_github_webhook_secret_arn = "arn:aws-us-gov:secretsmanager:us-gov-west-1:111122223333:secret:missing"',
            ]
        )
    )

    monkeypatch.setattr(mod, "_detect_infra_cli", lambda: "tofu")
    monkeypatch.setattr(mod, "_infra_cli_version_ok", lambda *_args, **_kwargs: (True, "found 1.8.0"))

    def _fake_exists(args, region=None):
        if args[:2] == ["secretsmanager", "describe-secret"]:
            return False, "ResourceNotFoundException"
        return True, "ok"

    monkeypatch.setattr(mod, "_aws_resource_exists", _fake_exists)
    monkeypatch.setattr(
        "sys.argv",
        [
            "predeploy_nonprod_checks.py",
            "--tfvars",
            str(tfvars),
            "--aws-checks",
        ],
    )

    assert mod.main() == 2


def test_main_aws_checks_uses_region_override(tmp_path: Path, monkeypatch) -> None:
    mod = _load_module()
    tfvars = tmp_path / "nonprod.tfvars"
    tfvars.write_text(
        '\n'.join(
            [
                'environment = "nonprod"',
                'aws_region = "us-gov-east-1"',
                'create_secrets_manager_secrets = true',
                'chatbot_retrieval_mode = "hybrid"',
                'existing_github_webhook_secret_arn = "arn:aws-us-gov:secretsmanager:us-gov-west-1:111122223333:secret:exists"',
            ]
        )
    )

    monkeypatch.setattr(mod, "_detect_infra_cli", lambda: "tofu")
    monkeypatch.setattr(mod, "_infra_cli_version_ok", lambda *_args, **_kwargs: (True, "found 1.8.0"))

    seen_regions: list[str | None] = []

    def _fake_exists(args, region=None):
        seen_regions.append(region)
        return True, "ok"

    monkeypatch.setattr(mod, "_aws_resource_exists", _fake_exists)
    monkeypatch.setattr(
        "sys.argv",
        [
            "predeploy_nonprod_checks.py",
            "--tfvars",
            str(tfvars),
            "--aws-checks",
            "--aws-region",
            "us-gov-west-1",
        ],
    )

    assert mod.main() == 0
    assert "us-gov-west-1" in seen_regions
