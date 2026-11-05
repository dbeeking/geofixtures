"""Command-line interface."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from importlib import util
from pathlib import Path
from typing import Any

from ._version import __version__
from .api import describe_case, list_cases, load_policy, run_suite, validate
from .environment import environment_versions, pdal_version
from .materialize import materialize
from .models import GeoFixturesError, Limits
from .registry import default_registry
from .runner.policy import StrictPolicy
from .runner.results import (
    junit_xml,
    observed_differences,
    text_report,
    write_json_report,
    write_junit_report,
)

EXIT_OK = 0
EXIT_FAILED = 1
EXIT_ERROR = 2


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> Any:
        self.exit(EXIT_ERROR, f"geofixtures: error: {message}\n")


def _limits(args: argparse.Namespace) -> Limits:
    defaults = Limits()
    return Limits(
        max_features=args.max_features or defaults.max_features,
        max_pixels=defaults.max_pixels,
        max_points=defaults.max_points,
        max_bytes=args.max_bytes or defaults.max_bytes,
    )


def _add_limits(command: argparse.ArgumentParser) -> None:
    command.add_argument("--max-features", type=int, help="Largest feature count a generator may create")
    command.add_argument("--max-bytes", type=int, help="Largest fixture size in bytes")


def build_parser() -> argparse.ArgumentParser:
    parser = _Parser(prog="geofixtures", description="Deterministic geospatial test fixtures")
    parser.add_argument("--version", action="version", version=f"geofixtures {__version__}")
    commands = parser.add_subparsers(dest="command", required=True, parser_class=_Parser)

    command = commands.add_parser("list", help="List cases")
    command.add_argument("--select", action="append", help="id, tag:x, category:x, op:x, or suite:x")
    command.add_argument("--format", choices=["text", "json"], default="text")

    command = commands.add_parser("describe", help="Show one case")
    command.add_argument("case_id")
    command.add_argument("--format", choices=["text", "json"], default="text")

    command = commands.add_parser("generate", help="Write cases to disk")
    command.add_argument("case_id", nargs="?")
    command.add_argument("--select", action="append")
    command.add_argument("--output", type=Path, required=True)
    command.add_argument("--seed", type=int)
    command.add_argument("--overwrite", action="store_true", help="Replace an existing fixture")
    _add_limits(command)

    command = commands.add_parser("validate", help="Check a manifest and its files")
    command.add_argument("manifest", type=Path)

    command = commands.add_parser("run", help="Run cases against an adapter")
    command.add_argument("--select", action="append")
    command.add_argument("--adapter", default="reference", help="reference, landfuse, or module:Class")
    command.add_argument("--report", type=Path, help="Write a report to this path")
    command.add_argument("--format", choices=["json", "junit"], default="json", help="Report format")
    command.add_argument("--seed", type=int)
    command.add_argument("--output", type=Path, help="Keep generated fixtures in this folder")
    command.add_argument("--keep-failures", type=Path, help="Copy outputs of cases that didn't pass here")
    command.add_argument("--timeout", type=float, help="Seconds allowed for each case. Implies --isolate")
    command.add_argument("--isolate", action="store_true", help="Run the adapter in its own process")
    command.add_argument("--strict", action="store_true", help="Fail unless every selected case passes")
    command.add_argument("--policy", type=Path, help="TOML file of allowed gaps. Implies --strict")
    command.add_argument("--offline", action=argparse.BooleanOptionalAction, default=True)
    _add_limits(command)

    command = commands.add_parser("report", help="Render a saved JSON report")
    command.add_argument("results", type=Path)
    command.add_argument("--format", choices=["text", "junit", "json"], default="text")
    command.add_argument("--output", type=Path)
    command.add_argument("--compare", type=Path, help="List observed differences from another JSON report")

    command = commands.add_parser("doctor", help="Show installed optional features")
    command.add_argument("--format", choices=["text", "json"], default="text")
    return parser


def _print_cases(cases: list[dict[str, Any]], output_format: str) -> None:
    if output_format == "json":
        print(json.dumps(cases, indent=2, sort_keys=True))
        return
    for case in cases:
        print(f"{case['case_id']:<34} {case['category']:<10} {case['title']}")


def _describe(args: argparse.Namespace) -> int:
    case = describe_case(args.case_id)
    if args.format == "json":
        print(json.dumps(case, indent=2, sort_keys=True))
        return EXIT_OK
    for key in (
        "case_id",
        "case_version",
        "title",
        "category",
        "operation",
        "expected_status",
        "oracle_method",
    ):
        print(f"{key}: {case[key]}")
    print(f"tags: {', '.join(case['tags'])}")
    print(f"requires: {', '.join(case['requires'])}")
    print(f"formats: {', '.join(case['formats'])}")
    print(f"derivation: {case['derivation']}")
    return EXIT_OK


def _generate(args: argparse.Namespace) -> int:
    registry = default_registry()
    if args.case_id:
        fixture = materialize(
            args.case_id, args.output, seed=args.seed, overwrite=args.overwrite, limits=_limits(args)
        )
        print(fixture.manifest_path)
        return EXIT_OK
    for spec in registry.select(args.select):
        fixture = materialize(
            spec, args.output / spec.case_id, seed=args.seed, overwrite=args.overwrite, limits=_limits(args)
        )
        print(fixture.manifest_path)
    return EXIT_OK


def _validate(args: argparse.Namespace) -> int:
    report = validate(args.manifest)
    if report.ok:
        print(f"OK {report.manifest_path}")
        return EXIT_OK
    for error in report.errors:
        print(f"INVALID {error}", file=sys.stderr)
    return EXIT_ERROR


def _policy(args: argparse.Namespace) -> StrictPolicy | None:
    if args.policy is not None:
        return load_policy(args.policy)
    return StrictPolicy() if args.strict else None


def _run(args: argparse.Namespace) -> int:
    result = run_suite(
        args.select,
        args.adapter,
        seed=args.seed,
        timeout=args.timeout,
        workspace=args.output,
        retain_dir=args.keep_failures,
        limits=_limits(args),
        offline=args.offline,
        isolate=args.isolate,
        policy=_policy(args),
    )
    report = result.to_dict()
    if args.report:
        if args.format == "junit":
            write_junit_report(args.report, report)
        else:
            write_json_report(args.report, report)
    print(text_report(report))
    for case in result.cases:
        if case.status.value in ("FAIL", "ERROR"):
            print(f"\n{case.failure_text()}", file=sys.stderr)
    return result.exit_code()


def _report(args: argparse.Namespace) -> int:
    report = json.loads(args.results.read_text())
    if args.compare:
        differences = observed_differences(report, json.loads(args.compare.read_text()))
        print(json.dumps(differences, indent=2, sort_keys=True))
        return EXIT_OK
    if args.format == "junit":
        text = junit_xml(report)
    elif args.format == "json":
        text = json.dumps(report, indent=2, sort_keys=True)
    else:
        text = text_report(report)
    if args.output:
        args.output.write_text(text + "\n")
    else:
        print(text)
    return EXIT_OK


def _doctor(args: argparse.Namespace) -> int:
    features = {
        "vector": all(util.find_spec(name) for name in ("pyarrow", "pyproj", "shapely")),
        "raster": util.find_spec("rasterio") is not None,
        "lidar": all(util.find_spec(name) for name in ("laspy", "pyproj")),
        "pytest": util.find_spec("pytest") is not None,
        "pdal_cli": pdal_version(),
        "landfuse": util.find_spec("landfuse") is not None,
    }
    details = {"environment": environment_versions(), "features": features}
    if args.format == "json":
        print(json.dumps(details, indent=2, sort_keys=True))
        return EXIT_OK
    for key, value in details["environment"].items():
        print(f"{key}: {value}")
    for key, value in features.items():
        print(f"{key}: {value}")
    return EXIT_OK


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "list":
            _print_cases(list_cases(args.select), args.format)
            return EXIT_OK
        handlers = {
            "describe": _describe,
            "generate": _generate,
            "validate": _validate,
            "run": _run,
            "report": _report,
            "doctor": _doctor,
        }
        return handlers[args.command](args)
    except (GeoFixturesError, OSError, ValueError) as exc:
        print(f"geofixtures: error: {exc}", file=sys.stderr)
        return EXIT_ERROR


if __name__ == "__main__":
    raise SystemExit(main())
