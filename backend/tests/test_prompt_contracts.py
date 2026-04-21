from app.prompts.discovery_prompt import DISCOVERY_SMART_PROMPT
from app.prompts.solution_advisor_prompt import SOLUTION_ADVISOR_PROMPT, SOLUTION_ADVISOR_RAG_PROMPT


def test_solution_advisor_prompt_has_specificity_rule():
    assert "## SPECIFICITY RULE (WHEN YOU ARE RECOMMENDING A SOLUTION):" in SOLUTION_ADVISOR_PROMPT
    assert "explicitly name the exact system type you would build" in SOLUTION_ADVISOR_PROMPT
    assert "## SPECIFICITY RULE (WHEN YOU ARE RECOMMENDING A SOLUTION):" in SOLUTION_ADVISOR_RAG_PROMPT
    assert "explicitly name the exact system type you would build" in SOLUTION_ADVISOR_RAG_PROMPT


def test_discovery_prompt_mentions_specificity_rule():
    assert "explicitly name the exact system type you would build" in DISCOVERY_SMART_PROMPT

