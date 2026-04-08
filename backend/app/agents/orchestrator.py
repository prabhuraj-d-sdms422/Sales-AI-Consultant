import json
import re

from langchain_core.messages import HumanMessage, SystemMessage

from app.config.llm_provider import get_classification_llm
from app.config.settings import settings
from app.models.state import ConversationState
from app.prompts.orchestrator_prompt import ORCHESTRATOR_SYSTEM_PROMPT
from app.services.conversation_memory_service import update_summary_if_needed
from app.services.session_service import save_state
from app.services.token_cost_service import (
    add_usage_totals,
    extract_token_usage_from_message,
    get_active_provider_and_model,
)
from app.utils.intent_classes import IntentClass  # noqa: F401 (kept for conversion agent imports)

# Fields that come exclusively from the intake form and must never be
# extracted or overwritten from conversation messages.
_FORM_ONLY_FIELDS = frozenset({"name", "email", "phone", "location"})


def _parse_orchestrator_response(content: str) -> dict:
    try:
        start = content.find("{")
        end = content.rfind("}") + 1
        if start >= 0 and end > start:
            return json.loads(content[start:end])
    except Exception:
        pass
    return {
        "intent": "GENERAL_INQUIRY",
        "confidence": 0.5,
        "next_agent": "discovery",
        "agent_mode": "CONVERSATIONAL",
    }


def _build_classification_prompt(state: ConversationState, message: str) -> str:
    stage = state.get("conversation_stage", "GREETING")
    profile = state.get("client_profile") or {}
    known_info = [k for k, v in profile.items() if v]
    return f"""Conversation stage: {stage}
Client profile fields collected: {", ".join(known_info) if known_info else "none yet"}

Client message: "{message}"

Classify this message and determine routing. Return JSON only."""


def _sanitize_next_agent(agent: str) -> str:
    allowed = {"discovery", "solution_advisor", "objection_handler", "conversion", "case_study"}
    if agent not in allowed:
        return "discovery"
    return agent


def _trim_labeled_value(val: str) -> str:
    """Stop at next field when user pasted multiple labels on one line."""
    v = val.strip()
    if not v:
        return v
    lower = v.lower()
    for marker in (
        ". problem:",
        "| problem:",
        "| problem",
        "| industry:",
        "| budget",
        "| urgency",
        ", problem:",
    ):
        idx = lower.find(marker)
        if idx != -1:
            v = v[:idx].strip()
            lower = v.lower()
    return v.rstrip(".,|")


def _extract_profile_fields(text: str) -> dict:
    """Lightweight backup extraction when the classifier JSON omits profile_updates.

    Only extracts business-context fields (company, industry, problem, budget,
    urgency, decision_maker). name / email / phone / location are collected via
    the intake form at session start and must NEVER be extracted or overwritten
    from conversation messages.
    """
    out: dict = {}
    t = (text or "").strip()
    tl = t  # used for case-insensitive patterns

    # Company: Company: / company name / from <Org> (case-insensitive)
    comp_m = re.search(r"(?im)^\s*company\s*:\s*([^\n|]+)", t)
    if not comp_m:
        comp_m = re.search(
            r"\bcompany name\s*(?:is)?\s*[:.]?\s*([A-Za-z0-9][^\n|]{0,120})",
            tl,
            re.I,
        )
    if not comp_m:
        comp_m = re.search(
            r"\bfrom\s+([A-Za-z0-9][A-Za-z0-9\s&.,'()-]{1,100}?)(?=\s*[,.|]|\s+email\b|\s+phone\b|\s+industry\b|\s+problem\b|\s*$)",
            tl,
            re.I,
        )
    if comp_m:
        out["company"] = comp_m.group(1).strip().rstrip(".,|")

    # Labeled fields (Industry / Problem / Budget / Urgency / Decision maker)
    def _labeled(label: str) -> str | None:
        m = re.search(
            rf"(?im)\b{re.escape(label)}\s*:\s*([^\n|]+)",
            t,
        )
        if not m:
            return None
        val = m.group(1).strip()
        return val or None

    industry = _labeled("Industry")
    if industry:
        out["industry"] = _trim_labeled_value(industry)

    # store as problem_raw; downstream agents can refine to problem_understood
    problem = _labeled("Problem")
    if problem:
        out["problem_raw"] = _trim_labeled_value(problem)

    budget = _labeled("Budget signal") or _labeled("Budget") or _labeled("Budget Signal")
    if budget:
        out["budget_signal"] = _trim_labeled_value(budget)

    urgency = _labeled("Urgency") or _labeled("Timeline")
    if urgency:
        out["urgency"] = _trim_labeled_value(urgency)

    dm = _labeled("Decision maker") or _labeled("Decision Maker")
    if dm:
        dm_norm = dm.strip().lower()
        if dm_norm in {"yes", "y", "true", "i am", "i approve"}:
            out["decision_maker"] = True
        elif dm_norm in {"no", "n", "false"}:
            out["decision_maker"] = False
        else:
            out["decision_maker"] = dm

    return out


def _normalize_problem_text(text: str) -> str:
    t = str(text or "").strip()
    # Keep this conservative to avoid accidental conflation.
    t = re.sub(r"\s+", " ", t)
    return t.strip(" -–—•\t")


def _append_unique_problem(existing: list[str] | None, new_problem: str) -> list[str]:
    problems: list[str] = list(existing or [])
    p = _normalize_problem_text(new_problem)
    if not p:
        return problems
    p_l = p.lower()
    for e in problems:
        if _normalize_problem_text(e).lower() == p_l:
            return problems
    problems.append(p)
    return problems


async def orchestrator_node(state: ConversationState) -> dict:
    llm = get_classification_llm()
    msgs = state.get("messages") or []
    last = msgs[-1]
    last_message = getattr(last, "content", str(last))
    if isinstance(last_message, list):
        last_message = "".join(str(x) for x in last_message)

    classification_prompt = _build_classification_prompt(state, last_message)
    response = await llm.ainvoke(
        [
            SystemMessage(content=ORCHESTRATOR_SYSTEM_PROMPT),
            HumanMessage(content=classification_prompt),
        ]
    )
    provider, model = get_active_provider_and_model()
    usage = extract_token_usage_from_message(response)
    session_token_usage = add_usage_totals(
        current=state.get("session_token_usage"),
        add_input_tokens=usage["input_tokens"],
        add_output_tokens=usage["output_tokens"],
        provider=provider,
        model=model,
    )
    last_call_token_usage = {
        "provider": provider,
        "model": model,
        **usage,
    }
    result = _parse_orchestrator_response(response.content or "")

    intent = str(result.get("intent", IntentClass.GENERAL_INQUIRY.value))
    confidence = float(result.get("confidence", 0.5))
    next_agent = _sanitize_next_agent(str(result.get("next_agent", "discovery")))
    updated_stage = str(result.get("updated_stage", state.get("conversation_stage", "GREETING")))
    agent_mode = str(result.get("agent_mode", "CONVERSATIONAL"))
    profile_updates = result.get("profile_updates") or {}
    if not isinstance(profile_updates, dict):
        profile_updates = {}
    extracted = _extract_profile_fields(last_message)
    lead_temperature = str(result.get("lead_temperature", state.get("lead_temperature", "cold")))

    if confidence < settings.intent_confidence_threshold:
        intent = IntentClass.LOW_CONFIDENCE.value
        next_agent = "discovery"
        agent_mode = "CONVERSATIONAL"

    base_profile = dict(state.get("client_profile") or {})
    base_problems = list(state.get("problems_identified") or [])

    def _is_empty(v: object) -> bool:
        if v is None:
            return True
        if isinstance(v, str) and not v.strip():
            return True
        return False

    # Merge strategy:
    # 1. Start from existing base profile (includes form data).
    # 2. Fill gaps from regex extraction (business fields only — form fields excluded).
    # 3. Apply LLM profile_updates, but NEVER overwrite form-collected fields.
    merged_profile = dict(base_profile)
    for k, v in extracted.items():
        if k in _FORM_ONLY_FIELDS:
            continue
        if _is_empty(v):
            continue
        if k not in merged_profile or _is_empty(merged_profile.get(k)):
            merged_profile[k] = v
    for k, v in profile_updates.items():
        if k in _FORM_ONLY_FIELDS:
            continue
        if _is_empty(v):
            continue
        merged_profile[k] = v

    # Accumulate problems across the session (multi-problem support).
    # Sources, in order:
    # - labeled extraction ("Problem:" in the latest user message)
    # - classifier profile_updates (problem_understood/problem_raw)
    problems_identified = base_problems
    if extracted.get("problem_raw"):
        problems_identified = _append_unique_problem(problems_identified, str(extracted["problem_raw"]))
    for key in ("problem_understood", "problem_raw"):
        v = profile_updates.get(key)
        if isinstance(v, str) and v.strip():
            problems_identified = _append_unique_problem(problems_identified, v)

    # Safe fallback for manipulation/prompt-injection attempts.
    # We intentionally do not let any sales agent generate a response in this case.
    manipulation_safe_fallback = (
        "I am here to help with business and technology requirements. "
        "What challenge can I help you solve today?"
    )

    updates: dict = {
        "current_intent": intent,
        "intent_confidence": confidence,
        "current_agent": next_agent,
        "conversation_stage": updated_stage,
        "agent_mode": agent_mode,
        "client_profile": merged_profile,
        "problems_identified": problems_identified,
        "lead_temperature": lead_temperature,
        "session_token_usage": session_token_usage,
        "last_call_token_usage": last_call_token_usage,
    }

    if intent == IntentClass.MANIPULATION_ATTEMPT.value:
        updates["current_response"] = manipulation_safe_fallback

    # Rolling summary refresh (best-effort, occasional) + turn counter increment.
    # We increment on every user turn; when a refresh runs it resets to 0.
    turns = int(state.get("summary_turns_since_update") or 0)
    updates["summary_turns_since_update"] = turns + 1
    merged_for_summary = {**dict(state), **updates}
    summary_updates = await update_summary_if_needed(merged_for_summary)  # best-effort
    updates.update(summary_updates)

    merged = {**dict(state), **updates}
    await save_state(state["session_id"], merged)
    return updates
