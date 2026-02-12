from worker.patch_apply import PatchApplyError, apply_unified_patch


def test_apply_unified_patch_single_hunk() -> None:
    original = "a\nb\nc\n"
    patch = "@@ -1,3 +1,3 @@\n a\n-b\n+x\n c"

    result = apply_unified_patch(original, patch)
    assert result == "a\nx\nc\n"


def test_apply_unified_patch_code_fence() -> None:
    original = "line1\nline2\n"
    patch = "```diff\n@@ -1,2 +1,2 @@\n line1\n-line2\n+line2_updated\n```"

    result = apply_unified_patch(original, patch)
    assert result == "line1\nline2_updated\n"


def test_apply_unified_patch_mismatch_raises() -> None:
    original = "a\nb\n"
    patch = "@@ -1,2 +1,2 @@\n x\n-b\n+y"

    try:
        apply_unified_patch(original, patch)
        assert False, "expected PatchApplyError"
    except PatchApplyError:
        assert True
