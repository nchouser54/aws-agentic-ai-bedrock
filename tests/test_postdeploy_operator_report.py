from __future__ import annotations

import importlib.util
from pathlib import Path


_SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "postdeploy_operator_report.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("postdeploy_operator_report", _SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_headers_token_and_bearer() -> None:
    mod = _load_module()

    assert mod._headers("none", "") == {"Content-Type": "application/json"}
    assert mod._headers("token", "abc")["X-Api-Token"] == "abc"
    assert mod._headers("bearer", "xyz")["Authorization"] == "Bearer xyz"


def test_derive_models_url() -> None:
    mod = _load_module()
    assert mod._derive_models_url("https://api.example.com/chatbot/query") == "https://api.example.com/chatbot/models"


def test_main_returns_nonzero_when_infra_outputs_unavailable(monkeypatch) -> None:
    mod = _load_module()

    monkeypatch.setattr(mod, "_detect_infra_cli", lambda: "tofu")

    def _boom(*_args, **_kwargs):
        raise RuntimeError("no state")

    monkeypatch.setattr(mod, "_run_infra_output", _boom)
    monkeypatch.setattr("sys.argv", ["postdeploy_operator_report.py"])

    assert mod.main() == 2


def test_main_ready_with_reachable_endpoints(monkeypatch) -> None:
    mod = _load_module()

    monkeypatch.setattr(mod, "_detect_infra_cli", lambda: "tofu")
    monkeypatch.setattr(
        mod,
        "_run_infra_output",
        lambda *_args, **_kwargs: {
            "webhook_url": {"value": "https://example.test/webhook/github"},
            "chatbot_url": {"value": "https://example.test/chatbot/query"},
            "webapp_url": {"value": "https://example.test/"},
        },
    )

    def _fake_request(method: str, url: str, timeout: int, headers: dict[str, str], payload=None):
        _ = (method, url, timeout, headers, payload)
        return {"reachable": True, "status_code": 200, "ok": True, "body_snippet": "ok"}

    monkeypatch.setattr(mod, "_request", _fake_request)
    monkeypatch.setattr("sys.argv", ["postdeploy_operator_report.py", "--auth-mode", "token", "--auth-value", "test-token"])

    assert mod.main() == 0
