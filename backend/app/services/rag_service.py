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
from typing import Optional

from app.config.settings import settings

logger = logging.getLogger(__name__)

# ── Constants ─────────────────────────────────────────────────────────────────
_EMBED_MODEL_NAME    = "all-MiniLM-L6-v2"   # 384-dim, free, local, CPU
NAMESPACE_HEALTHCARE = "healthcare"

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


# ── Public API ────────────────────────────────────────────────────────────────

async def get_industry_context(
    query_text: str,
    namespace: str = NAMESPACE_HEALTHCARE,
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
    if not query_text or not query_text.strip():
        return None

    try:
        model = _get_embed_model()
        if model is None:
            return None

        index = _get_pinecone_index()
        if index is None:
            return None

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
            return None

        # Prefer S1 tier first, then fill remaining slots from other tiers
        s1 = [
            m for m in passing
            if (m.get("metadata") or {}).get("solution_tier_code", "").startswith("S1")
        ]
        others = [m for m in passing if m not in s1]
        ordered = (s1 + others)[:top_k]

        if not ordered:
            return None

        header = (
            "## STARK DIGITAL HEALTHCARE KNOWLEDGE BASE\n"
            "The following are verified, deliverable solutions from Stark Digital's "
            "healthcare portfolio. Use these as your primary reference when recommending "
            "solutions to this client. Present in the client's language and tone.\n"
            "Do NOT copy verbatim — synthesise and personalise based on their specific problem.\n"
        )
        blocks = [_format_match(m, i + 1) for i, m in enumerate(ordered)]
        return header + "\n" + "\n\n".join(blocks)

    except Exception:
        logger.exception(
            "RAG: error during context retrieval for namespace '%s' — "
            "falling back to LLM general knowledge.",
            namespace,
        )
        return None
