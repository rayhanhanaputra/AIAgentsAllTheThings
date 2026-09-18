"""Target plugins.

`agribot-mock` is a deterministic reference agent and is always available.
`agribot-llm` drives a real LLM and is imported best-effort (it needs an SDK and an
API key); its absence never breaks the harness.
"""
from . import agribot_mock  # noqa: F401
from . import callbot_mock  # noqa: F401
from . import relaybot_mock  # noqa: F401
from . import scanbot_mock  # noqa: F401
from . import resolverbot_mock  # noqa: F401
from . import homebot_mock  # noqa: F401
from . import controlbot_mock  # noqa: F401
from . import processbot_mock  # noqa: F401

try:
    from . import agribot_llm  # noqa: F401
except Exception:  # pragma: no cover - optional dependency or missing credentials
    pass
