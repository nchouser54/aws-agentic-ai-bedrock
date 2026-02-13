from __future__ import annotations

import re

_HUNK_HEADER_RE = re.compile(r"^@@\s+-(\d+)(?:,(\d+))?\s+\+(\d+)(?:,(\d+))?\s+@@")


class PatchApplyError(ValueError):
    pass


def _strip_fence(patch_text: str) -> str:
    text = patch_text.strip()
    if text.startswith("```diff") and text.endswith("```"):
        return "\n".join(text.splitlines()[1:-1])
    if text.startswith("```") and text.endswith("```"):
        return "\n".join(text.splitlines()[1:-1])
    return text


def apply_unified_patch(original_text: str, patch_text: str) -> str:
    """Apply a unified diff patch to a single file.

    Supports patches containing one or more hunks for a single file. Raises
    PatchApplyError if hunk matching fails.
    """
    patch = _strip_fence(patch_text)
    patch_lines = patch.splitlines()

    # Remove optional file header lines.
    while patch_lines and (patch_lines[0].startswith("--- ") or patch_lines[0].startswith("+++ ")):
        patch_lines.pop(0)

    lines = original_text.splitlines()
    delta = 0
    i = 0

    while i < len(patch_lines):
        header = patch_lines[i]
        match = _HUNK_HEADER_RE.match(header)
        if not match:
            i += 1
            continue

        old_start = int(match.group(1))
        i += 1

        old_chunk: list[str] = []
        new_chunk: list[str] = []

        while i < len(patch_lines) and not patch_lines[i].startswith("@@"):
            line = patch_lines[i]
            if line.startswith("\\"):
                i += 1
                continue
            if line.startswith(" "):
                value = line[1:]
                old_chunk.append(value)
                new_chunk.append(value)
            elif line.startswith("-"):
                old_chunk.append(line[1:])
            elif line.startswith("+"):
                new_chunk.append(line[1:])
            else:
                raise PatchApplyError(f"Invalid patch line: {line}")
            i += 1

        expected_index = max(0, old_start - 1 + delta)
        candidate_slice = lines[expected_index : expected_index + len(old_chunk)]

        if candidate_slice != old_chunk:
            # try a small local search window to tolerate drift
            found_index = None
            window_start = max(0, expected_index - 8)
            window_end = min(len(lines), expected_index + 8)
            for idx in range(window_start, window_end + 1):
                if lines[idx : idx + len(old_chunk)] == old_chunk:
                    found_index = idx
                    break
            if found_index is None:
                raise PatchApplyError("Patch hunk context did not match target file")
            expected_index = found_index

        lines[expected_index : expected_index + len(old_chunk)] = new_chunk
        delta += len(new_chunk) - len(old_chunk)

    return "\n".join(lines) + ("\n" if original_text.endswith("\n") else "")
