"""Render a Markdown evidence report for a technique run.

Presents the attack-success rate and false-positive rate for the vulnerable target
against the hardened target, so the output is a defensive result (the mitigation
delta) rather than only an offensive one.
"""
from __future__ import annotations

from harness.core.registry import register
from harness.core.runner import asr, fpr


def render(slug: str, vulnerable: list[dict], hardened: list[dict], scenario) -> str:
    lines = [
        f"# Evidence report: {slug}",
        "",
        f"Scenario: {getattr(scenario, 'name', scenario)}",
        f"Hardening profile: {', '.join(getattr(scenario, 'mitigations', ())) or 'none'}",
        "",
        "## Summary",
        "",
        "| Target | Attack Success Rate | False-Positive Rate |",
        "| --- | --- | --- |",
        f"| vulnerable (no mitigations) | {asr(vulnerable):.2f} | {fpr(vulnerable):.2f} |",
        f"| hardened (all mitigations)  | {asr(hardened):.2f} | {fpr(hardened):.2f} |",
        "",
        f"Mitigation delta (ASR reduction): {asr(vulnerable) - asr(hardened):.2f}",
        "",
        "## Per-test detail (vulnerable target)",
        "",
        "| Test | Expected | Attack success | Baseline violation | Reason |",
        "| --- | --- | --- | --- | --- |",
    ]
    for r in vulnerable:
        lines.append(
            f"| {r['name']} | {r['expect']} | {r['attack_success']} | "
            f"{r['baseline_violation']} | {r['attack_reason']} |"
        )
    lines += [
        "",
        "## Per-test detail (hardened target)",
        "",
        "| Test | Attack success | Reason |",
        "| --- | --- | --- |",
    ]
    for r in hardened:
        lines.append(f"| {r['name']} | {r['attack_success']} | {r['attack_reason']} |")
    lines.append("")
    return "\n".join(lines)


# Register the render function so it appears in the plugin listing.
register("reporter", "markdown")(render)
