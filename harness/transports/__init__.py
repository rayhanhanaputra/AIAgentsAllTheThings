"""Transport plugins.

The harness executes techniques in-process over the deterministic `direct` transport.
The realistic channels a technique names in its declarative test (mqtt, voice, gpio,
...) are documented channel labels; the live demonstration over a real channel lives
in the simulators under sims/, which drive a broker directly.
"""
from . import direct  # noqa: F401
