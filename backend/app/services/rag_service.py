"""
RAG service — industry-specific Pinecone context retrieval.

Uses sentence-transformers (free, local, CPU) for embedding queries at
runtime.  The model and Pinecone connection are loaded once via module-level
singletons and reused across all requests.

Public API:
    is_healthcare_context(industry, problem_text) -> bool
    get_industry_context(query_text, namespace, top_k, threshold) -> str | None

Always fails gracefully — any error returns None so the conversation
continues normally on LLM general knowledge.
"""

import logging
from functools import lru_cache
from typing import Any, Optional, TypedDict

from app.config.settings import settings

logger = logging.getLogger(__name__)

# ── Constants ─────────────────────────────────────────────────────────────────
_EMBED_MODEL_NAME = "all-MiniLM-L6-v2"  # 384-dim, free, local, CPU
NAMESPACE_HEALTHCARE = "healthcare"
NAMESPACE_INSURANCE = "insurance"

# Vocabulary that reliably signals a healthcare-domain conversation.
# Even one match in the problem text qualifies — these are all domain-specific.
_HEALTHCARE_SIGNALS: frozenset[str] = frozenset({
    "patient", "patients", "hospital", "hospitals", "clinic", "clinics",
    "clinical", "medical", "doctor", "physician", "nurse", "healthcare",
    "health care", "ehr", "emr", "nabh", "hipaa", "pharmacy", "pharmaceutical",
    "drug", "drugs", "diagnosis", "diagnostic", "diagnostics", "treatment",
    "appointment", "appointments", "billing", "claim", "claims", "insurance",
    "tpa", "ayushman", "pmjay", "radiology", "imaging", "mri", "pathology",
    "telehealth", "telemedicine", "mental health", "chronic", "wellness",
    "surgery", "ward", "icu", "discharge", "admission", "inpatient", "outpatient",
    "fhir", "hl7", "disha", "abha", "abdm", "health record", "medtech",
    "healthtech", "lab results", "laboratory", "care coordinator", "patient care",
    "patient data", "medical records", "clinical workflow", "revenue cycle",
})

_INSURANCE_SIGNALS: frozenset[str] = frozenset(
    {
        "insurance",
        "insurer",
        "insurers",
        "policy",
        "policyholder",
        "policyholders",
        "premium",
        "renewal",
        "claim",
        "claims",
        "fnol",
        "first notice of loss",
        "tpa",
        "underwriting",
        "uw",
        "fraud",
        "siu",
        "survey",
        "surveyor",
        "guidewire",
        "duck creek",
        "claims management system",
        "cms",
        "motor claim",
        "health claim",
        "cashless",
        "settlement",
        "endorsement",
        "k yc",
        "kyc",
        "risk scoring",
        "rate card",
        "irda",
        "irdai",
        "insurtech",
        "broker",
        "agent",
        "channel partner",
        "proposal form",
    }
)

# ── Singletons ────────────────────────────────────────────────────────────────

@lru_cache(maxsize=1)
def _get_embed_model():
    """
    Load the sentence-transformer model once.  Cached for process lifetime.
    Returns None if the library is not installed — RAG is silently disabled.
    """
    try:
        from sentence_transformers import SentenceTransformer  # noqa: PLC0415
        model = SentenceTransformer(_EMBED_MODEL_NAME)
        logger.info("RAG: embedding model '%s' loaded.", _EMBED_MODEL_NAME)
        return model
    except Exception:
        logger.exception("RAG: failed to load embedding model — RAG disabled.")
        return None


@lru_cache(maxsize=1)
def _get_pinecone_index():
    """
    Connect to Pinecone once.  Cached for process lifetime.
    Returns None when Pinecone is not configured or connection fails.
    """
    api_key    = settings.pinecone_api_key
    index_name = settings.pinecone_index_name
    if not api_key or not index_name:
        logger.warning("RAG: Pinecone credentials not configured — RAG disabled.")
        return None
    try:
        from pinecone import Pinecone  # noqa: PLC0415
        pc    = Pinecone(api_key=api_key)
        index = pc.Index(index_name)
        logger.info("RAG: connected to Pinecone index '%s'.", index_name)
        return index
    except Exception:
        logger.exception("RAG: failed to connect to Pinecone — RAG disabled.")
        return None


# ── Domain detection ──────────────────────────────────────────────────────────

def is_healthcare_context(industry: str, problem_text: str) -> bool:
    """
    Return True when the conversation signals a healthcare-domain problem.

    Checks:
    1. The orchestrator-extracted industry field (e.g. "healthcare", "hospital")
    2. Keyword scan of the raw problem text (any single strong signal qualifies)
    """
    combined = f"{industry or ''} {problem_text or ''}".lower()
    return any(sig in combined for sig in _HEALTHCARE_SIGNALS)


def is_insurance_context(industry: str, problem_text: str) -> bool:
    combined = f"{industry or ''} {problem_text or ''}".lower()
    return any(sig in combined for sig in _INSURANCE_SIGNALS)

# ── Formatting helpers ────────────────────────────────────────────────────────

def _format_match(match: dict, rank: int) -> str:
    m = match.get("metadata") or {}
    score = match.get("score", 0)

    lines = [
        f"--- Solution Match {rank} (similarity: {score:.2f}) ---",
        f"Problem:      {m.get('problem_title', '')}",
        f"Subcategory:  {m.get('subcategory', '')}",
        f"Solution ({m.get('tier_label') or m.get('solution_tier_code', '')}): "
        f"{m.get('solution_name', '')}",
    ]
    if m.get("explanation"):
        lines.append(f"What we build: {m['explanation']}")
    if m.get("tech_stack"):
        lines.append(f"Tech stack:    {m['tech_stack']}")
    if m.get("outcome"):
        lines.append(f"Outcomes:      {m['outcome']}")
    if m.get("best_for"):
        lines.append(f"Best for:      {m['best_for']}")
    if m.get("usp"):
        lines.append(f"Our edge:      {m['usp']}")
    if m.get("cost"):
        lines.append(f"Cost signal:   {m['cost']}")
    if m.get("timeline"):
        lines.append(f"Timeline:      {m['timeline']}")
    return "\n".join(lines)


def _namespace_label(namespace: str) -> str:
    if namespace == NAMESPACE_HEALTHCARE:
        return "HEALTHCARE"
    if namespace == NAMESPACE_INSURANCE:
        return "INSURANCE"
    return namespace.upper()


# ── Public API ────────────────────────────────────────────────────────────────

async def get_industry_context(
    query_text: str,
    namespace: str,
    top_k: int = 3,
    threshold: float = 0.70,
) -> Optional[str]:
    """
    Embed `query_text`, query Pinecone in `namespace`, and return a formatted
    context block ready to inject into the Solution Advisor prompt.

    Returns None when:
    - query_text is empty
    - embedding model failed to load
    - Pinecone connection failed
    - no result scores >= threshold
    - any exception during the process

    Tier preference: S1 (Best Performance) matches surface first; then other
    tiers fill remaining slots up to `top_k`.
    """
    ctx, _sources = await get_industry_context_with_sources(
        query_text=query_text,
        namespace=namespace,
        top_k=top_k,
        threshold=threshold,
    )
    return ctx


class RAGSource(TypedDict, total=False):
    id: str
    score: float
    namespace: str
    problem_title: str
    subcategory: str
    solution_tier_code: str
    tier_label: str
    solution_name: str
    outcome: str
    tech_stack: str


def _source_from_match(match: dict[str, Any], namespace: str) -> RAGSource:
    md = match.get("metadata") or {}
    return {
        "id": str(match.get("id") or ""),
        "score": float(match.get("score") or 0.0),
        "namespace": str(namespace),
        "problem_title": str(md.get("problem_title") or ""),
        "subcategory": str(md.get("subcategory") or ""),
        "solution_tier_code": str(md.get("solution_tier_code") or ""),
        "tier_label": str(md.get("tier_label") or ""),
        "solution_name": str(md.get("solution_name") or ""),
        "outcome": str(md.get("outcome") or ""),
        "tech_stack": str(md.get("tech_stack") or ""),
    }


async def get_industry_context_with_sources(
    query_text: str,
    namespace: str,
    top_k: int = 3,
    threshold: float = 0.70,
) -> tuple[Optional[str], list[RAGSource]]:
    """
    Same as get_industry_context(), but also returns structured source metadata
    for each match (ids/scores + key metadata fields).
    """
    if not query_text or not query_text.strip():
        return None, []

    try:
        model = _get_embed_model()
        if model is None:
            return None, []

        index = _get_pinecone_index()
        if index is None:
            return None, []

        # Embed synchronously — SentenceTransformer is CPU-bound, ~5-20 ms
        vector: list[float] = model.encode(query_text).tolist()

        # Fetch extra candidates so we can apply S1-preference ordering
        raw_results = index.query(
            vector=vector,
            top_k=top_k * 3,
            include_metadata=True,
            namespace=namespace,
        )

        all_matches: list[dict] = raw_results.get("matches") or []

        # Filter by similarity threshold
        passing = [m for m in all_matches if (m.get("score") or 0) >= threshold]
        if not passing:
            logger.debug(
                "RAG: no matches above %.2f in namespace '%s'.", threshold, namespace
            )
            return None, []

        # Prefer S1 tier first, then fill remaining slots from other tiers
        s1 = [
            m for m in passing
            if (m.get("metadata") or {}).get("solution_tier_code", "").startswith("S1")
        ]
        others = [m for m in passing if m not in s1]
        ordered = (s1 + others)[:top_k]

        if not ordered:
            return None, []

        label = _namespace_label(namespace)
        header = (
            f"## STARK DIGITAL {label} KNOWLEDGE BASE\n"
            "The following are documented solution approaches and implementation patterns from Stark Digital's "
            f"{label.lower()} portfolio. Use these as your primary reference when recommending "
            "solutions to this client. Present in the client's language and tone.\n"
            "If example numbers/outcomes are included in the records, treat them as expected benchmarks based on similar implementations, "
            "not already-achieved results for this client.\n"
            "Do NOT copy verbatim — synthesise and personalise based on their specific problem.\n"
        )
        blocks = [_format_match(m, i + 1) for i, m in enumerate(ordered)]
        sources = [_source_from_match(m, namespace=namespace) for m in ordered]
        return header + "\n" + "\n\n".join(blocks), sources

    except Exception:
        logger.exception(
            "RAG: error during context retrieval for namespace '%s' — "
            "falling back to LLM general knowledge.",
            namespace,
        )
        return None, []
