"""Shared constants used across Lambda entrypoints."""

from __future__ import annotations

DEFAULT_REGION = "us-gov-west-1"

# Maximum length of user queries accepted by the chatbot
MAX_QUERY_LENGTH = 4000

# Maximum length of user-supplied CQL/JQL strings
MAX_QUERY_FILTER_LENGTH = 500
