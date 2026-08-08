from __future__ import annotations

import argparse
from pathlib import Path

from cloudspend.optimizer.engine import optimize
from cloudspend.providers.aws_live import AwsProvider
from cloudspend.providers.file_upload import FileProvider
from cloudspend.providers.fixture import FixtureProvider
from cloudspend.web import create_app


def _args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(add_help=True)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--demo", action="store_true", help="Preload the bundled demo fixture")
    mode.add_argument("--file", help="Preload and analyze a supported local file")
    mode.add_argument("--aws-profile", help="Preload a read-only live AWS scan using this profile")
    parser.add_argument("--regions", default="us-east-1", help="Comma-separated regions for live AWS mode")
    return parser.parse_args()


app = create_app()


def _preload(args: argparse.Namespace) -> str | None:
    settings = app.config["CLOUDSPEND_SETTINGS"]
    store = app.config["CLOUDSPEND_STORE"]
    if args.demo:
        sample = Path(__file__).resolve().parent / "samples" / "mock_aws_bundle.zip"
        provider_result = FixtureProvider(sample, settings).load()
        source_mode = "demo"
    elif args.file:
        provider_result = FileProvider(args.file, settings).load()
        source_mode = "file"
    elif args.aws_profile:
        regions = [r.strip() for r in args.regions.split(",") if r.strip()]
        provider_result = AwsProvider(profile_name=args.aws_profile, regions=regions, settings=settings).load()
        source_mode = "live"
    else:
        return None
    optimized = optimize(provider_result.resources, settings)
    return store.save_scan(
        optimized,
        source_mode=source_mode,
        source_info=provider_result.source_info,
        warnings=provider_result.warnings,
        errors=provider_result.errors,
    )


if __name__ == "__main__":
    args = _args()
    startup_scan = _preload(args)
    if startup_scan:
        print(f"CloudSpend preloaded scan: http://127.0.0.1:{app.config['CLOUDSPEND_SETTINGS'].port}/scans/{startup_scan}")
    settings = app.config["CLOUDSPEND_SETTINGS"]
    app.run(host=settings.host, port=settings.port, debug=settings.app_env == "development", use_reloader=False)
