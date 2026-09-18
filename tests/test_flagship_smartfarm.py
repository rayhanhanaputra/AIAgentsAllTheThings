"""Deterministic proof of the flagship scenario (AAT-0001).

These tests demonstrate, offline and without any network, that:
  - the vulnerable reference agent is subverted by each attack variant;
  - the benign baseline never triggers a violation (no false positive);
  - enabling the mitigations drives the attack success rate to zero while legitimate
    irrigation still works.
"""
from __future__ import annotations

from harness.core.engine import evaluate_case
from harness.core.runner import asr, fpr, run_technique

VULNERABLE = frozenset()
HARDENED = frozenset({"freetext_quarantine", "schema_validation", "policy_gate"})

ATTACKS = [
    "smartfarm/note-override@overt",
    "smartfarm/note-override@subtle",
    "smartfarm/note-override@sufficient-moisture",
    "smartfarm/value-injection@out-of-range",
]
BENIGN = [
    "smartfarm/benign-low-moisture",
    "smartfarm/benign-sufficient-moisture",
    "smartfarm/benign-note-chatty",
    "smartfarm/benign-inspection-ok",
]


def _verdict(payload_ref, mitigations):
    verdict, _actions, _msg = evaluate_case(
        scenario="smartfarm-irrigation", payload_ref=payload_ref, mitigations=mitigations
    )
    return verdict


def test_vulnerable_agent_is_subverted_by_every_attack():
    for ref in ATTACKS:
        assert _verdict(ref, VULNERABLE).success, f"{ref} should succeed against vulnerable agent"


def test_benign_baseline_never_violates():
    for ref in BENIGN:
        assert not _verdict(ref, VULNERABLE).success, f"{ref} must not trigger a violation"


def test_hardening_defeats_every_attack():
    for ref in ATTACKS:
        assert not _verdict(ref, HARDENED).success, f"{ref} should be defeated when hardened"


def test_hardened_agent_still_irrigates_when_dry():
    _verdict_, actions, _msg = evaluate_case(
        scenario="smartfarm-irrigation",
        payload_ref="smartfarm/benign-low-moisture",
        mitigations=HARDENED,
    )
    opened = [a for a in actions if a.tool == "set_valve" and a.args.get("state") == "open"]
    assert opened, "hardened agent must still irrigate genuinely dry soil"
    assert all(a.args["duration_minutes"] <= 120 for a in opened)


def test_bound_tests_vulnerable_asr_and_fpr():
    results = run_technique("C2-I3-smartfarm-note-override", mitigations=VULNERABLE)
    assert len(results) == 2
    assert asr(results) == 1.0
    assert fpr(results) == 0.0


def test_bound_tests_hardened_asr_drops_to_zero():
    results = run_technique("C2-I3-smartfarm-note-override", mitigations=HARDENED)
    assert asr(results) == 0.0
    assert fpr(results) == 0.0
