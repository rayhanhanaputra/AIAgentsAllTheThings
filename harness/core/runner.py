"""Load declarative tests, run them, and aggregate attack-success statistics."""
from __future__ import annotations

from pathlib import Path
from typing import Iterable

import yaml

from harness.core.engine import evaluate_case, oracle_name

# Package-relative so the declarative tests are found whether running from the repo,
# an editable install, or a wheel (they ship as package data; see pyproject.toml).
TESTS_DIR = Path(__file__).resolve().parents[1] / "tests"


def available_techniques() -> list[str]:
    if not TESTS_DIR.is_dir():
        return []
    return sorted(p.name for p in TESTS_DIR.iterdir() if p.is_dir())


def load_tests(slug: str) -> list[dict]:
    # Reject empty, traversal, or unknown names before touching the filesystem.
    if slug not in set(available_techniques()):
        raise FileNotFoundError(f"no declarative tests for technique '{slug}'")
    folder = TESTS_DIR / slug
    tests = [yaml.safe_load(p.read_text()) for p in sorted(folder.glob("*.yaml"))]
    return [t for t in tests if t]


def run_technique(
    slug: str,
    mitigations: Iterable[str] = (),
    transport: str = "direct",
    target: str | None = None,
) -> list[dict]:
    """Run every declarative test bound to a technique.

    For each test the attack payload and its benign twin are delivered. Returns one
    result dict per test with the attack verdict and the baseline (false-positive)
    verdict. `target` overrides the target declared in each test when given.
    """
    mitigations = frozenset(mitigations)
    results = []
    for test in load_tests(slug):
        common = dict(
            scenario=test["scenario"],
            mitigations=mitigations,
            encoder=test.get("encoder", "json-field"),
            transport=transport,
            oracle=oracle_name(test.get("oracle")),
            target=target or test.get("target", "agribot-mock"),
        )
        attack_verdict, attack_actions, _ = evaluate_case(payload_ref=test["payload"], **common)
        baseline_verdict, _, _ = evaluate_case(payload_ref=test["baseline"], **common)
        results.append(
            {
                "name": test.get("name", test["payload"]),
                "guid": test.get("auto_generated_guid"),
                "expect": test.get("expect", "success"),
                "attack_success": attack_verdict.success,
                "attack_reason": attack_verdict.reason,
                "baseline_violation": baseline_verdict.success,
                "actions": attack_actions,
            }
        )
    return results


def _mean(values: list[bool]) -> float:
    return round(sum(1 for v in values if v) / len(values), 3) if values else 0.0


def asr(results: list[dict]) -> float:
    """Attack Success Rate."""
    return _mean([r["attack_success"] for r in results])


def fpr(results: list[dict]) -> float:
    """False-Positive Rate over the benign baselines."""
    return _mean([r["baseline_violation"] for r in results])
