from __future__ import annotations

import argparse
import json
from pathlib import Path

from cloudspend.ai.fixture_generator import generate_ai_bundle, generate_deterministic_bundle, write_bundle_zip
from cloudspend.ai.provider import get_ai_provider
from cloudspend.config import Settings
from cloudspend.optimizer.engine import optimize
from cloudspend.providers.aws_live import AwsProvider
from cloudspend.providers.file_upload import FileProvider
from cloudspend.providers.fixture import FixtureProvider


def _json_dump(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")


def _report(provider_result, settings: Settings) -> dict:
    result = optimize(provider_result.resources, settings)
    return {
        "source_info": provider_result.source_info,
        "warnings": provider_result.warnings,
        "errors": provider_result.errors,
        "summary": {
            "resources": len(result.resources),
            "opportunities": len(result.recommendations),
            "observed_monthly_spend": str(result.observed_spend),
            "potential_monthly_savings": str(result.potential_savings),
        },
        "resources": [r.model_dump(mode="json") for r in result.resources],
        "recommendations": [r.model_dump(mode="json") for r in result.recommendations],
    }


def cmd_analyze_file(args: argparse.Namespace) -> int:
    settings = Settings.from_env()
    provider_result = FileProvider(args.path, settings).load()
    report = _report(provider_result, settings)
    if args.output:
        _json_dump(Path(args.output), report)
        print(f"Wrote report: {args.output}")
    else:
        print(json.dumps(report, indent=2, default=str))
    return 0


def cmd_analyze_demo(args: argparse.Namespace) -> int:
    settings = Settings.from_env()
    root = Path(__file__).resolve().parents[1]
    sample = Path(args.path) if args.path else root / "samples" / "mock_aws_bundle.zip"
    report = _report(FixtureProvider(sample, settings).load(), settings)
    if args.output:
        _json_dump(Path(args.output), report)
        print(f"Wrote report: {args.output}")
    else:
        print(json.dumps(report, indent=2, default=str))
    return 0


def cmd_scan_aws(args: argparse.Namespace) -> int:
    settings = Settings.from_env()
    regions = [r.strip() for r in args.regions.split(",") if r.strip()]
    provider = AwsProvider(profile_name=args.profile or None, regions=regions, settings=settings)
    report = _report(provider.load(), settings)
    if args.output:
        _json_dump(Path(args.output), report)
        print(f"Wrote report: {args.output}")
    else:
        print(json.dumps(report, indent=2, default=str))
    return 0


def cmd_generate_fixture(args: argparse.Namespace) -> int:
    settings = Settings.from_env()
    regions = [r.strip() for r in args.regions.split(",") if r.strip()]
    volume_count = args.volumes if args.volumes is not None else max(3, args.resources // 4)
    if args.ai:
        provider = get_ai_provider(settings)
        payloads = generate_ai_bundle(
            provider,
            scenario=args.scenario,
            instance_count=args.resources,
            volume_count=volume_count,
            regions=regions,
            window_days=args.window_days,
            seed=args.seed,
        )
    else:
        payloads = generate_deterministic_bundle(
            scenario=args.scenario,
            instance_count=args.resources,
            volume_count=volume_count,
            regions=regions,
            window_days=args.window_days,
            seed=args.seed,
        )
    output = write_bundle_zip(payloads, args.output)
    print(f"Generated validated fixture: {output}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="cloudspend", description="CloudSpend local-first AWS FinOps analyzer")
    sub = parser.add_subparsers(dest="command", required=True)

    file_parser = sub.add_parser("analyze-file", help="Analyze JSON/CSV/XLSX/ZIP input")
    file_parser.add_argument("path")
    file_parser.add_argument("--output", "-o")
    file_parser.set_defaults(func=cmd_analyze_file)

    demo_parser = sub.add_parser("analyze-demo", help="Analyze the bundled synthetic AWS fixture")
    demo_parser.add_argument("--path")
    demo_parser.add_argument("--output", "-o")
    demo_parser.set_defaults(func=cmd_analyze_demo)

    aws_parser = sub.add_parser("scan-aws", help="Run a read-only live AWS scan")
    aws_parser.add_argument("--profile", default="")
    aws_parser.add_argument("--regions", default="us-east-1")
    aws_parser.add_argument("--output", "-o")
    aws_parser.set_defaults(func=cmd_scan_aws)

    fixture = sub.add_parser("generate-fixture", help="Generate a validated AWS-like mock bundle")
    fixture.add_argument("--scenario", default="mixed-fleet")
    fixture.add_argument("--resources", type=int, default=12, help="Number of EC2 instances")
    fixture.add_argument("--volumes", type=int)
    fixture.add_argument("--regions", default="us-east-1")
    fixture.add_argument("--window-days", type=int, default=14)
    fixture.add_argument("--seed", type=int, default=42)
    fixture.add_argument("--output", default="samples/mock_aws_bundle.zip")
    fixture.add_argument("--ai", action="store_true", help="Use configured optional AI provider instead of deterministic generation")
    fixture.set_defaults(func=cmd_generate_fixture)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
