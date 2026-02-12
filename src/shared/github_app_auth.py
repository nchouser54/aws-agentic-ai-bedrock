import json
import time
from typing import Optional, Tuple

import boto3
import jwt
import requests
from botocore.client import BaseClient

from shared.retry import call_with_retry


class GitHubAppAuth:
    def __init__(
        self,
        app_ids_secret_arn: str,
        private_key_secret_arn: str,
        api_base: str = "https://api.github.com",
        secrets_client: Optional[BaseClient] = None,
        http_session: Optional[requests.Session] = None,
    ) -> None:
        self._app_ids_secret_arn = app_ids_secret_arn
        self._private_key_secret_arn = private_key_secret_arn
        self._api_base = api_base.rstrip("/")
        self._secrets = secrets_client or boto3.client("secretsmanager")
        self._session = http_session or requests.Session()
        self._cached_app_id: Optional[str] = None
        self._cached_installation_id: Optional[str] = None
        self._cached_private_key: Optional[str] = None

    def _read_secret_string(self, secret_arn: str) -> str:
        response = self._secrets.get_secret_value(SecretId=secret_arn)
        secret_string = response.get("SecretString")
        if not secret_string:
            raise ValueError(f"Secret {secret_arn} has no SecretString")
        return secret_string

    def _load_app_ids(self) -> Tuple[str, str]:
        if self._cached_app_id and self._cached_installation_id:
            return self._cached_app_id, self._cached_installation_id

        payload = json.loads(self._read_secret_string(self._app_ids_secret_arn))
        app_id = str(payload["app_id"])
        installation_id = str(payload["installation_id"])
        self._cached_app_id = app_id
        self._cached_installation_id = installation_id
        return app_id, installation_id

    def _load_private_key(self) -> str:
        if self._cached_private_key:
            return self._cached_private_key

        self._cached_private_key = self._read_secret_string(self._private_key_secret_arn)
        return self._cached_private_key

    def create_app_jwt(self) -> str:
        app_id, _ = self._load_app_ids()
        now = int(time.time())
        payload = {
            "iat": now - 60,
            "exp": now + 540,
            "iss": app_id,
        }
        private_key = self._load_private_key()
        token = jwt.encode(payload, private_key, algorithm="RS256")
        return token if isinstance(token, str) else token.decode("utf-8")

    def get_installation_token(self, installation_id_override: Optional[str] = None) -> str:
        _, default_installation_id = self._load_app_ids()
        installation_id = installation_id_override or default_installation_id
        jwt_token = self.create_app_jwt()
        url = f"{self._api_base}/app/installations/{installation_id}/access_tokens"

        def _request() -> requests.Response:
            return self._session.post(
                url,
                headers={
                    "Authorization": f"Bearer {jwt_token}",
                    "Accept": "application/vnd.github+json",
                    "X-GitHub-Api-Version": "2022-11-28",
                },
                timeout=15,
            )

        def _retryable_exception(exc: Exception) -> bool:
            return isinstance(exc, requests.RequestException)

        response = call_with_retry(
            "github_installation_token",
            _request,
            is_retryable_exception=_retryable_exception,
            is_retryable_result=lambda r: r.status_code in {403, 429} or r.status_code >= 500,
        )
        response.raise_for_status()
        data = response.json()
        token = data.get("token")
        if not token:
            raise ValueError("GitHub installation token missing from response")
        return token
