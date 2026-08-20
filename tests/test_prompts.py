"""Tests for winery/prompts.py — prompt integrity."""

from winery import prompts


class TestPromptFormats:
    def test_research_plan_prompt_is_formattable(self):
        q = "Why did Concorde fail?"
        formatted = prompts.RESEARCH_PLAN_PROMPT.format(question=q)
        assert q in formatted
        assert "{question}" not in formatted  # template fully consumed

    def test_synthesis_prompt_is_formattable(self):
        formatted = prompts.SYNTHESIS_PROMPT.format(
            question="Q", sources_text="S"
        )
        assert "Q" in formatted
        assert "S" in formatted
        assert "{question}" not in formatted
        assert "{sources_text}" not in formatted

    def test_system_prompt_has_no_placeholders(self):
        assert "{" not in prompts.NANOFOSSIL_SYSTEM_PROMPT or "\\n" in prompts.NANOFOSSIL_SYSTEM_PROMPT
        # (system prompt has no format placeholders — it's used raw)
