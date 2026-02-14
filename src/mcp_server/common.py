from __future__ import annotations

import os
from functools import lru_cache

from shared.atlassian_client import AtlassianClient
from shared.github_app_auth import GitHubAppAuth
from shared.github_client import GitHubClient


def required_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def parse_repo(repo_full_name: str) -> tuple[str, str]:
    value = (repo_full_name or "").strip()
    if "/" not in value:
        raise ValueError("repo_full_name must be in the form 'owner/repo'")
    owner, repo = value.split("/", 1)
    owner = owner.strip()
    repo = repo.strip()
    if not owner or not repo:
        raise ValueError("repo_full_name must be in the form 'owner/repo'")
    return owner, repo


@lru_cache(maxsize=1)
def github_client() -> GitHubClient:
    app_ids_secret_arn = required_env("GITHUB_APP_IDS_SECRET_ARN")
    private_key_secret_arn = required_env("GITHUB_APP_PRIVATE_KEY_SECRET_ARN")
    api_base = os.getenv("GITHUB_API_BASE", "https://api.github.com")

    auth = GitHubAppAuth(
        app_ids_secret_arn=app_ids_secret_arn,
        private_key_secret_arn=private_key_secret_arn,
        api_base=api_base,
    )
    return GitHubClient(token_provider=auth.get_installation_token, api_base=api_base)


@lru_cache(maxsize=1)
def atlassian_client() -> AtlassianClient:
    credentials_secret_arn = required_env("ATLASSIAN_CREDENTIALS_SECRET_ARN")
    return AtlassianClient(credentials_secret_arn=credentials_secret_arn)
