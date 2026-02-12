from __future__ import annotations

import re
from typing import Optional

_HUNK_HEADER_RE = re.compile(r"@@\s+-\d+(?:,\d+)?\s+\+(\d+)(?:,\d+)?\s+@@")


def map_new_line_to_diff_position(patch: str, target_new_line: int) -> Optional[int]:
    """
    Map a PR file patch new-line number to GitHub 'position' for review comments.

    Position is counted from the first hunk line and includes context/add/remove lines,
    excluding hunk header lines.
    """
    if not patch:
        return None

    position = 0
    current_new_line: Optional[int] = None

    for raw_line in patch.splitlines():
        if raw_line.startswith("@@"):
            match = _HUNK_HEADER_RE.match(raw_line)
            if match:
                current_new_line = int(match.group(1))
            continue

        if current_new_line is None:
            continue

        if raw_line.startswith("\\"):
            continue

        position += 1

        if raw_line.startswith("+"):
            if current_new_line == target_new_line:
                return position
            current_new_line += 1
            continue

        if raw_line.startswith("-"):
            continue

        if current_new_line == target_new_line:
            return position
        current_new_line += 1

    return None
