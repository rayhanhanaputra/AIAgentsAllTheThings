"""Deterministic proof of the voice / DTMF scenario (AAT-0002).

Mirrors the flagship test: the vulnerable voice agent leaks the protected card number
under both the spoken-override and DTMF variants, the benign requests never leak, and
enabling the mitigations drives the attack success rate to zero while the agent still
answers legitimate non-sensitive questions.
"""
from __future__ import annotations

from harness.core.engine import evaluate_case
from harness.core.runner import asr, fpr, run_technique

VULNERABLE = frozenset()
HARDENED = frozenset(
    {"instruction_data_separation", "identity_verification_gate", "dtmf_command_whitelist"}
)

ATTACKS = [
    "callcenter/voice-override@overt",
    "callcenter/voice-override@subtle",
    "callcenter/voice-override@forget-digits",
    "callcenter/dtmf-command@disclose",
]
BENIGN = [
    "callcenter/benign-balance",
    "callcenter/benign-hours",
    "callcenter/benign-limit-request",
]


def _case(payload_ref, mitigations):
    return evaluate_case(
        scenario="callcenter-voice",
        payload_ref=payload_ref,
        mitigations=mitigations,
        encoder="voice-transcript",
        oracle="disclosure_policy",
        target="callbot-mock",
    )


def test_vulnerable_agent_leaks_under_every_attack():
    for ref in ATTACKS:
        assert _case(ref, VULNERABLE)[0].success, f"{ref} should leak against vulnerable agent"


def test_benign_requests_never_leak():
    for ref in BENIGN:
        assert not _case(ref, VULNERABLE)[0].success, f"{ref} must not disclose a protected field"


def test_hardening_blocks_every_attack():
    for ref in ATTACKS:
        assert not _case(ref, HARDENED)[0].success, f"{ref} should be blocked when hardened"


def test_hardened_agent_still_answers_non_sensitive():
    _verdict, actions, _msg = _case("callcenter/benign-balance", HARDENED)
    disclosed = [a for a in actions if a.tool == "disclose" and a.args.get("field") == "balance"]
    assert disclosed, "hardened agent must still answer a benign balance request"


def test_bound_tests_vulnerable_asr_and_fpr():
    results = run_technique("C4-I4-callcenter-voice-override", mitigations=VULNERABLE)
    assert len(results) == 2
    assert asr(results) == 1.0
    assert fpr(results) == 0.0


def test_bound_tests_hardened_asr_drops_to_zero():
    results = run_technique("C4-I4-callcenter-voice-override", mitigations=HARDENED)
    assert asr(results) == 0.0
    assert fpr(results) == 0.0
