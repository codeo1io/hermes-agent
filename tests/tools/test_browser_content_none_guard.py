"""Tests for the None guard on browser_tool LLM response content.

browser_vision() renders its result payload through
``tools.browser_tool._vision_analysis_or_fallback``: reasoning-only models
(DeepSeek-R1, QwQ) legally return ``content=None``, and the payload must always
carry a usable analysis string instead of crashing on ``None.strip()``.

The old _extract_relevant_content snapshot-summarization path was removed —
oversized snapshots now always truncate-and-store (no auxiliary LLM), so its
None-guard tests are gone with it.
"""

from tools.browser_tool import _vision_analysis_or_fallback


# ── browser_vision ─────────────────────────────────────────────────────────

class TestBrowserVisionNoneGuard:
    """tools/browser_tool.py — browser_vision() analysis extraction"""

    def test_none_content_produces_fallback_message(self):
        """When the vision model returns None content, the payload carries a
        fixed fallback message."""
        assert _vision_analysis_or_fallback(None) == "Vision analysis returned no content."

    def test_whitespace_only_content_falls_back(self):
        """Blank analysis is indistinguishable from None for the caller."""
        assert _vision_analysis_or_fallback("   \n\t ") == "Vision analysis returned no content."

    def test_empty_string_falls_back(self):
        assert _vision_analysis_or_fallback("") == "Vision analysis returned no content."

    def test_normal_content_passes_through_stripped(self):
        """Normal analysis content passes through, whitespace-stripped."""
        assert _vision_analysis_or_fallback("  The page shows a login form.  ") == (
            "The page shows a login form."
        )
