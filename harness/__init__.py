"""AIAgentsAllTheThings testing harness.

The harness runs a technique end-to-end against a target agent and decides,
mechanically, whether the attack caused an unsafe privileged action:

    Scenario -> Payload -> Encoder -> Transport -> Target -> Oracle -> Report

See harness/README.md for the plugin model and the command-line interface.
"""

__version__ = "0.1.0"
