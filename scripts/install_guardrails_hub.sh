#!/usr/bin/env bash
# Install Guardrails Hub validators into the active venv (large downloads: torch, models).
# Must run from the repository root so .guardrails/hub_registry.json is updated.

set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

if ! command -v guardrails >/dev/null 2>&1; then
  echo "guardrails CLI not found. Install deps first: pip install -r backend/requirements.txt" >&2
  exit 1
fi

# Optional: export HF_TOKEN=... for higher Hub rate limits (see https://huggingface.co/settings/tokens)

guardrails hub install hub://guardrails/toxic_language
guardrails hub install hub://guardrails/detect_jailbreak
guardrails hub install hub://guardrails/competitor_check

echo "Guardrails Hub validators installed. Registry: $ROOT/.guardrails/hub_registry.json"
