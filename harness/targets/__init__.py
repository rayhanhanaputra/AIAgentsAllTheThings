"""Target plugins.

Deterministic reference agents are always available. `llm-agent` provides the single
OpenAI-compatible live-model adapter for every scenario that declares an agent spec.
"""
from . import agribot_mock  # noqa: F401
from . import callbot_mock  # noqa: F401
from . import relaybot_mock  # noqa: F401
from . import scanbot_mock  # noqa: F401
from . import resolverbot_mock  # noqa: F401
from . import homebot_mock  # noqa: F401
from . import controlbot_mock  # noqa: F401
from . import processbot_mock  # noqa: F401
from . import llm_agent  # noqa: F401
from . import http_agent  # noqa: F401
from . import tcp_agent  # noqa: F401
