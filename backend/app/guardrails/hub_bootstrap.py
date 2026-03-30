"""Point Guardrails Hub at the repo-root registry (not process cwd).

The guardrails library resolves ``.guardrails/hub_registry.json`` relative to
``os.getcwd()``, which breaks when uvicorn is started from ``backend/`` while
the registry lives at the repository root. We pin the path so
``from guardrails.hub import ...`` resolves consistently.
"""

from pathlib import Path

import guardrails.hub.registry as hub_registry_module

# hub_bootstrap.py → guardrails → app → backend → repo root
_REPO_ROOT = Path(__file__).resolve().parents[3]


def get_registry_path() -> Path:
    return _REPO_ROOT / ".guardrails" / "hub_registry.json"


hub_registry_module.get_registry_path = get_registry_path  # type: ignore[method-assign]
