"""Command-line interface for the harness.

Commands:
    aat list                                 list registered plugins
    aat run   <technique>                    verify a technique reproduces (vulnerable target)
    aat demo  <technique> [--json] [--out D]  vulnerable vs hardened, with a report
    aat ablate <technique>                    per-mitigation attack-success-rate table

All commands run offline over the in-process `direct` transport. The realistic
channel a technique names in its test is a documented label; the live demonstration
lives under sims/.
"""
from __future__ import annotations

import argparse
import itertools
import json
import sys
from pathlib import Path

from harness.core import registry
from harness.core.runner import (
    asr,
    available_techniques,
    fpr,
    load_tests,
    run_technique,
)


class CliError(Exception):
    """A user-facing error reported without a traceback."""


# --- helpers ---------------------------------------------------------------
def _scenario_for(technique: str):
    tests = load_tests(technique)
    if not tests:
        raise CliError(f"technique '{technique}' has no declarative tests")
    return registry.get("scenario", tests[0]["scenario"])


def _validate_target(name: str | None) -> None:
    if name is None:
        return
    try:
        registry.get("target", name)
    except KeyError:
        raise CliError(f"unknown target '{name}'. Available: {registry.available('target')}")


def _check_target_scenario(name: str | None, scenario_name: str) -> None:
    """A target that declares a scenario must match the technique's scenario, so a
    mismatched --target cannot silently report a (meaningless) 0.00 result."""
    if name is None:
        return
    declared = getattr(registry.get("target", name), "scenario", None)
    if declared is not None and declared != scenario_name:
        raise CliError(
            f"target '{name}' is for scenario '{declared}', not '{scenario_name}'; "
            f"choose a technique in that scenario, or omit --target"
        )


def _powerset(items):
    items = list(items)
    for r in range(len(items) + 1):
        yield from itertools.combinations(items, r)


# --- commands --------------------------------------------------------------
def _cmd_list(_args) -> int:
    for kind in registry.KINDS:
        print(f"{kind}:")
        for name in registry.available(kind):
            print(f"  - {name}")
    return 0


def _cmd_run(args) -> int:
    _validate_target(args.target)
    _check_target_scenario(args.target, _scenario_for(args.technique)().name)
    results = run_technique(args.technique, mitigations=frozenset(), target=args.target)
    ok = True
    print(f"technique: {args.technique}   target: {args.target or 'as declared'} (vulnerable)\n")
    for r in results:
        expected_success = r["expect"] == "success"
        passed = (r["attack_success"] == expected_success) and not r["baseline_violation"]
        ok = ok and passed
        mark = "PASS" if passed else "FAIL"
        print(f"[{mark}] {r['name']}")
        print(f"       attack_success={r['attack_success']} (expected {expected_success}), "
              f"baseline_violation={r['baseline_violation']}")
        print(f"       {r['attack_reason']}")
    print(f"\nASR={asr(results):.2f}  FPR={fpr(results):.2f}")
    return 0 if ok else 1


def _cmd_demo(args) -> int:
    _validate_target(args.target)
    scenario = _scenario_for(args.technique)()
    _check_target_scenario(args.target, scenario.name)
    hardened_mitigations = frozenset(getattr(scenario, "mitigations", ()))

    vulnerable = run_technique(args.technique, mitigations=frozenset(), target=args.target)
    hardened = run_technique(args.technique, mitigations=hardened_mitigations, target=args.target)

    from harness.reporters.markdown_reporter import render
    out_dir = Path(args.out)
    try:
        out_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise CliError(f"cannot write report to '{out_dir}': {exc}")
    report_path = out_dir / f"{args.technique}.md"
    report_path.write_text(render(args.technique, vulnerable, hardened, scenario))

    summary = {
        "technique": args.technique,
        "scenario": scenario.name,
        "vulnerable": {"asr": asr(vulnerable), "fpr": fpr(vulnerable)},
        "hardened": {"asr": asr(hardened), "fpr": fpr(hardened)},
        "mitigation_delta": round(asr(vulnerable) - asr(hardened), 3),
        "report": str(report_path),
    }

    if args.json:
        print(json.dumps(summary, indent=2))
    else:
        print(f"technique: {args.technique}   scenario: {scenario.name}\n")
        print(f"vulnerable  ASR={asr(vulnerable):.2f}  FPR={fpr(vulnerable):.2f}")
        print(f"hardened    ASR={asr(hardened):.2f}  FPR={fpr(hardened):.2f}")
        print(f"mitigation delta (ASR reduction): {summary['mitigation_delta']:.2f}")
        print(f"\nwrote report: {report_path}")
    return 0


def _cmd_ablate(args) -> int:
    _validate_target(args.target)
    scenario = _scenario_for(args.technique)()
    _check_target_scenario(args.target, scenario.name)
    mitigations = list(getattr(scenario, "mitigations", ()))

    print(f"technique: {args.technique}   scenario: {scenario.name}")
    print(f"mitigations available: {', '.join(mitigations) or 'none'}\n")
    width = max([len("(none)")] + [len("+".join(s)) for s in _powerset(mitigations) if s])
    print(f"{'mitigations'.ljust(width)}   ASR   FPR")
    for subset in _powerset(mitigations):
        results = run_technique(args.technique, mitigations=frozenset(subset), target=args.target)
        label = "+".join(subset) if subset else "(none)"
        print(f"{label.ljust(width)}   {asr(results):.2f}  {fpr(results):.2f}")
    return 0


# --- entry point -----------------------------------------------------------
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="aat", description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("list", help="list registered plugins").set_defaults(func=_cmd_list)

    p_run = sub.add_parser("run", help="verify a technique reproduces (vulnerable target)")
    p_run.add_argument("technique")
    p_run.add_argument("--target", default=None, help="override the target declared in the tests")
    p_run.set_defaults(func=_cmd_run)

    p_demo = sub.add_parser("demo", help="vulnerable vs hardened, with a report")
    p_demo.add_argument("technique")
    p_demo.add_argument("--target", default=None, help="override the target declared in the tests")
    p_demo.add_argument("--json", action="store_true", help="emit the summary as JSON")
    p_demo.add_argument("--out", default="out", help="directory for the Markdown report (default: out)")
    p_demo.set_defaults(func=_cmd_demo)

    p_ablate = sub.add_parser("ablate", help="per-mitigation-subset attack-success table")
    p_ablate.add_argument("technique")
    p_ablate.add_argument("--target", default=None, help="override the target declared in the tests")
    p_ablate.set_defaults(func=_cmd_ablate)

    return parser


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except CliError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except FileNotFoundError:
        print(
            f"error: unknown technique '{getattr(args, 'technique', '?')}'. "
            f"Available: {available_techniques()}",
            file=sys.stderr,
        )
        return 2
    except KeyError as exc:
        print(f"error: {str(exc).strip(chr(34))}", file=sys.stderr)
        return 2
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
