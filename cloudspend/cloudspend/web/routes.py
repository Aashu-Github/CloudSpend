from __future__ import annotations

import csv
import io
import json
import tempfile
from decimal import Decimal
from pathlib import Path

from flask import Blueprint, abort, current_app, jsonify, redirect, render_template, request, send_file, session, url_for

from cloudspend.ai.fixture_generator import generate_ai_bundle, write_bundle_zip
from cloudspend.ai.provider import AIProviderError, get_ai_provider
from cloudspend.ai.schema_mapper import propose_mapping
from cloudspend.config import Settings
from cloudspend.ingestion.parse_csv import parse_csv
from cloudspend.ingestion.parse_json import parse_json
from cloudspend.ingestion.parse_xlsx import parse_xlsx
from cloudspend.ingestion.validators import UploadValidationError, validate_original_filename
from cloudspend.optimizer.engine import optimize
from cloudspend.optimizer.pricing import monthly_equivalent
from cloudspend.providers.aws_live import AwsProvider
from cloudspend.providers.file_upload import FileProvider
from cloudspend.providers.fixture import FixtureProvider
from cloudspend.storage import ScanStore

bp = Blueprint("web", __name__)


def _settings() -> Settings:
    return current_app.config["CLOUDSPEND_SETTINGS"]


def _store() -> ScanStore:
    return current_app.config["CLOUDSPEND_STORE"]


def _csrf_ok() -> bool:
    expected = session.get("csrf_token")
    provided = request.form.get("csrf_token") or request.headers.get("X-CSRF-Token")
    return bool(expected and provided and secrets_compare(expected, provided))


def secrets_compare(a: str, b: str) -> bool:
    import hmac

    return hmac.compare_digest(a, b)


def _require_csrf() -> None:
    if not _csrf_ok():
        abort(400, description="Invalid CSRF token.")


def _mapping_preview(path: Path) -> tuple[list[str], dict[str, str], list[dict]]:
    """Build a minimal, redacted-by-schema-mapper preview; never sends whole uploads to AI."""
    suffix = path.suffix.lower()
    if suffix == ".csv":
        df = parse_csv(path).head(10)
        return [str(c) for c in df.columns], {str(c): str(df[c].dtype) for c in df.columns}, df.fillna("").to_dict(orient="records")
    if suffix == ".xlsx":
        df = parse_xlsx(path).head(10)
        return [str(c) for c in df.columns], {str(c): str(df[c].dtype) for c in df.columns}, df.fillna("").to_dict(orient="records")
    if suffix == ".json":
        payload = parse_json(path)
        if isinstance(payload, dict):
            columns = list(payload.keys())
            return columns, {str(k): type(v).__name__ for k, v in payload.items()}, [payload]
        if isinstance(payload, list) and payload and isinstance(payload[0], dict):
            columns = sorted({str(k) for row in payload[:10] if isinstance(row, dict) for k in row})
            return columns, {c: "unknown" for c in columns}, [row for row in payload[:10] if isinstance(row, dict)]
    return [], {}, []


def _save(provider_result, source_mode: str) -> str:
    result = optimize(provider_result.resources, _settings())
    return _store().save_scan(
        result,
        source_mode=source_mode,
        source_info=provider_result.source_info,
        warnings=provider_result.warnings,
        errors=provider_result.errors,
    )


def _dashboard_values(scan: dict) -> dict:
    resources = scan["resources"]
    recs = scan["recommendations"]
    observed = Decimal("0")
    cost_basis_counts: dict[str, int] = {"actual": 0, "allocated": 0, "estimated": 0, "unavailable": 0}
    for resource in resources:
        value, basis = monthly_equivalent(resource.costs)
        cost_basis_counts[basis] = cost_basis_counts.get(basis, 0) + 1
        if value is not None:
            observed += value
    best_by_resource: dict[str, Decimal] = {}
    for rec in recs:
        if rec.estimated_monthly_savings is not None:
            best_by_resource[rec.resource_id] = max(best_by_resource.get(rec.resource_id, Decimal("0")), rec.estimated_monthly_savings)
    savings = sum(best_by_resource.values(), Decimal("0"))
    pct = float((savings / observed * 100) if observed > 0 else 0)
    chart = []
    rec_resources = {r.resource_id for r in recs}
    for resource in resources:
        cpu = resource.metrics.get("CPUUtilization")
        cost, basis = monthly_equivalent(resource.costs)
        if resource.resource_type == "ec2_instance":
            chart.append({
                "id": resource.resource_id,
                "name": resource.name or resource.resource_id,
                "cpu": cpu.avg if cpu and cpu.avg is not None else None,
                "cost": float(cost) if cost is not None else None,
                "basis": basis,
                "opportunity": resource.resource_id in rec_resources,
                "environment": resource.environment,
            })
    scan_info = {
        "ec2_resources": sum(1 for r in resources if r.resource_type == "ec2_instance"),
        "ebs_resources": sum(1 for r in resources if r.resource_type == "ebs_volume"),
        "resources_with_metrics": sum(1 for r in resources if r.metrics),
        "resources_with_memory": sum(1 for r in resources if "mem_used_percent" in r.metrics or "MemoryUtilization" in r.metrics),
        "rules_executed": 5,
    }
    return {
        "observed": observed.quantize(Decimal("0.01")),
        "savings": savings.quantize(Decimal("0.01")),
        "savings_pct": round(pct, 1),
        "cost_basis_counts": cost_basis_counts,
        "chart": chart,
        "scan_info": scan_info,
        "environments": sorted({r.environment for r in resources}),
    }


@bp.get("/")
def home():
    recent = _store().list_scans(5)
    return render_template("home.html", recent=recent)


@bp.get("/import")
def import_page():
    return render_template("import.html", settings=_settings())


@bp.get("/aws")
def aws_page():
    return render_template("aws.html", settings=_settings())


@bp.get("/methodology")
def methodology():
    return render_template("methodology.html", settings=_settings())


@bp.get("/stack")
def stack():
    return render_template("stack.html")


@bp.post("/api/demo")
def api_demo():
    _require_csrf()
    sample = Path(current_app.root_path).parent.parent / "samples" / "mock_aws_bundle.zip"
    try:
        scan_id = _save(FixtureProvider(sample, _settings()).load(), "demo")
    except Exception as exc:
        return render_template("error.html", message=f"Demo could not be loaded: {exc}"), 500
    return redirect(url_for("web.scan_dashboard", scan_id=scan_id), code=303)


@bp.post("/api/import")
def api_import():
    _require_csrf()
    upload = request.files.get("file")
    if upload is None or not upload.filename:
        return jsonify({"error": "Choose a file to import."}), 400
    try:
        validate_original_filename(upload.filename)
        suffix = Path(upload.filename).suffix.lower()
        with tempfile.TemporaryDirectory(prefix="cloudspend_upload_") as temp:
            temp_path = Path(temp) / f"upload{suffix}"
            upload.save(temp_path)
            try:
                provider_result = FileProvider(temp_path, _settings(), display_name=upload.filename).load()
            except UploadValidationError as exc:
                response = {"error": str(exc), "mapping_available": _settings().ai_provider != "none"}
                if _settings().ai_provider != "none" and "not recognized" in str(exc).lower():
                    try:
                        columns, inferred_types, samples = _mapping_preview(temp_path)
                        if columns:
                            proposal = propose_mapping(get_ai_provider(_settings()), columns, inferred_types, samples)
                            response["mapping_proposal"] = proposal.model_dump(mode="json")
                            # Mapping proposals are never silently applied in MVP.
                            response["requires_review"] = True
                    except Exception as map_exc:
                        current_app.logger.info("AI mapping fallback unavailable: %s", type(map_exc).__name__)
                return jsonify(response), 422
            scan_id = _save(provider_result, "file")
        return jsonify({"scan_id": scan_id, "redirect": url_for("web.scan_dashboard", scan_id=scan_id)})
    except UploadValidationError as exc:
        return jsonify({"error": str(exc)}), 422
    except Exception as exc:
        current_app.logger.warning("Import failed: %s", type(exc).__name__)
        return jsonify({"error": "Import failed safely. Verify that the file matches a supported AWS/CloudSpend schema."}), 400


def _wants_json() -> bool:
    return request.headers.get("X-Requested-With") == "fetch" or request.accept_mimetypes.best == "application/json"


@bp.post("/api/aws/scan")
def api_aws_scan():
    _require_csrf()
    profile = request.form.get("profile", "").strip() or None
    regions = [x.strip() for x in request.form.get("regions", "us-east-1").split(",") if x.strip()]
    if not regions:
        regions = ["us-east-1"]
    try:
        provider_result = AwsProvider(profile_name=profile, regions=regions, settings=_settings()).load()
        scan_id = _save(provider_result, "live")
        destination = url_for("web.scan_dashboard", scan_id=scan_id)
        if _wants_json():
            return jsonify({"scan_id": scan_id, "redirect": destination})
        return redirect(destination, code=303)
    except Exception as exc:
        current_app.logger.warning("Live AWS scan failed: %s", type(exc).__name__)
        message = (
            "CloudSpend could not connect to AWS with the supplied local configuration. "
            "Check that your AWS CLI or SSO session is authenticated and that the profile and regions are valid."
        )
        if _wants_json():
            return jsonify({"error": message}), 400
        return render_template("error.html", message=message), 400


@bp.get("/scans/<scan_id>")
def scan_dashboard(scan_id: str):
    scan = _store().get_scan(scan_id)
    if not scan:
        abort(404)
    metrics = _dashboard_values(scan)
    recs_by_id: dict[str, list] = {}
    for rec in scan["recommendations"]:
        recs_by_id.setdefault(rec.resource_id, []).append(rec)
    return render_template("scan.html", scan=scan, **metrics, recs_by_id=recs_by_id)


@bp.get("/scans/<scan_id>/resources/<path:resource_id>")
def resource_detail(scan_id: str, resource_id: str):
    found = _store().get_resource(scan_id, resource_id)
    if not found:
        abort(404)
    resource, recs = found
    chart_metrics = {
        name: {"timestamps": [ts.isoformat() for ts in metric.timestamps], "values": metric.values, "unit": metric.unit}
        for name, metric in resource.metrics.items()
        if metric.timestamps and metric.values
    }
    return render_template("resource.html", scan_id=scan_id, resource=resource, recommendations=recs, chart_metrics=chart_metrics)


@bp.get("/api/scans/<scan_id>/resources")
def api_resources(scan_id: str):
    scan = _store().get_scan(scan_id)
    if not scan:
        abort(404)
    return jsonify([r.model_dump(mode="json") for r in scan["resources"]])


@bp.get("/api/scans/<scan_id>/recommendations")
def api_recommendations(scan_id: str):
    scan = _store().get_scan(scan_id)
    if not scan:
        abort(404)
    return jsonify([r.model_dump(mode="json") for r in scan["recommendations"]])


@bp.get("/api/resources/<path:resource_id>")
def api_resource(resource_id: str):
    scan_id = request.args.get("scan_id")
    if not scan_id:
        return jsonify({"error": "scan_id query parameter is required"}), 400
    found = _store().get_resource(scan_id, resource_id)
    if not found:
        abort(404)
    resource, recs = found
    return jsonify({"resource": resource.model_dump(mode="json"), "recommendations": [r.model_dump(mode="json") for r in recs]})


@bp.get("/api/export/<scan_id>.json")
def export_json(scan_id: str):
    scan = _store().get_scan(scan_id)
    if not scan:
        abort(404)
    payload = {
        "scan_id": scan_id,
        "created_at": scan["created_at"].isoformat() if scan["created_at"] else None,
        "source_mode": scan["source_mode"],
        "source_info": scan["source_info"],
        "warnings": scan["warnings"],
        "errors": scan["errors"],
        "resources": [r.model_dump(mode="json") for r in scan["resources"]],
        "recommendations": [r.model_dump(mode="json") for r in scan["recommendations"]],
    }
    data = json.dumps(payload, indent=2, default=str).encode("utf-8")
    return send_file(io.BytesIO(data), mimetype="application/json", as_attachment=True, download_name=f"cloudspend-{scan_id}.json")


@bp.get("/api/export/<scan_id>.csv")
@bp.get("/api/export/<scan_id>-recommendations.csv")
def export_csv(scan_id: str):
    scan = _store().get_scan(scan_id)
    if not scan:
        abort(404)
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=["rule_id", "rule_version", "category", "resource_id", "confidence", "current_monthly_cost", "estimated_monthly_savings", "savings_basis", "suggested_action", "missing_signals"])
    writer.writeheader()
    for rec in scan["recommendations"]:
        writer.writerow({
            "rule_id": rec.rule_id,
            "rule_version": rec.rule_version,
            "category": rec.category,
            "resource_id": rec.resource_id,
            "confidence": rec.confidence,
            "current_monthly_cost": rec.current_monthly_cost,
            "estimated_monthly_savings": rec.estimated_monthly_savings,
            "savings_basis": rec.savings_basis,
            "suggested_action": rec.suggested_action,
            "missing_signals": "; ".join(rec.missing_signals),
        })
    data = buffer.getvalue().encode("utf-8")
    return send_file(io.BytesIO(data), mimetype="text/csv", as_attachment=True, download_name=f"cloudspend-{scan_id}-recommendations.csv")


@bp.get("/api/export/<scan_id>-resources.csv")
def export_resources_csv(scan_id: str):
    scan = _store().get_scan(scan_id)
    if not scan:
        abort(404)
    fields = [
        "resource_id", "resource_type", "name", "region", "state", "environment", "instance_type",
        "volume_type", "size_gib", "cpu_avg", "cpu_p95", "cpu_max", "actual_resource_cost",
        "allocated_cost", "estimated_resource_cost", "cost_source", "cost_confidence", "source_mode",
        "source_family", "source_metadata_json",
    ]
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=fields)
    writer.writeheader()
    for resource in scan["resources"]:
        cpu = resource.metrics.get("CPUUtilization")
        writer.writerow({
            "resource_id": resource.resource_id,
            "resource_type": resource.resource_type,
            "name": resource.name or "",
            "region": resource.region,
            "state": resource.state,
            "environment": resource.environment,
            "instance_type": resource.ec2.instance_type if resource.ec2 else "",
            "volume_type": resource.ebs.volume_type if resource.ebs else "",
            "size_gib": resource.ebs.size_gib if resource.ebs else "",
            "cpu_avg": cpu.avg if cpu else "",
            "cpu_p95": cpu.p95 if cpu else "",
            "cpu_max": cpu.max if cpu else "",
            "actual_resource_cost": resource.costs.actual_resource_cost if resource.costs.actual_resource_cost is not None else "",
            "allocated_cost": resource.costs.allocated_cost if resource.costs.allocated_cost is not None else "",
            "estimated_resource_cost": resource.costs.estimated_resource_cost if resource.costs.estimated_resource_cost is not None else "",
            "cost_source": resource.costs.source,
            "cost_confidence": resource.costs.confidence,
            "source_mode": resource.source_lineage.provider_mode,
            "source_family": resource.source_lineage.source_family or "",
            "source_metadata_json": json.dumps(resource.source_metadata, default=str),
        })
    data = buffer.getvalue().encode("utf-8")
    return send_file(io.BytesIO(data), mimetype="text/csv", as_attachment=True, download_name=f"cloudspend-{scan_id}-resources.csv")


@bp.post("/api/import/map")
def api_map_import():
    _require_csrf()
    if _settings().ai_provider == "none":
        return jsonify({"error": "AI mapping is disabled (AI_PROVIDER=none)."}), 409
    body = request.get_json(silent=True) or {}
    try:
        proposal = propose_mapping(
            get_ai_provider(_settings()),
            [str(x) for x in body.get("columns", [])],
            {str(k): str(v) for k, v in (body.get("inferred_types") or {}).items()},
            body.get("samples") or [],
        )
        return jsonify({**proposal.model_dump(mode="json"), "requires_review": proposal.overall_confidence < 0.85})
    except (AIProviderError, ValueError) as exc:
        return jsonify({"error": str(exc)}), 400


@bp.post("/api/ai/generate-fixture")
def api_generate_fixture():
    _require_csrf()
    body = request.get_json(silent=True) or {}
    if _settings().ai_provider == "none":
        return jsonify({"error": "AI fixture generation is disabled. Use the deterministic generator or set AI_PROVIDER=ollama."}), 409
    try:
        payloads = generate_ai_bundle(
            get_ai_provider(_settings()),
            scenario=str(body.get("scenario", "mixed AWS fleet")),
            instance_count=int(body.get("instance_count", 12)),
            volume_count=int(body.get("volume_count", 4)),
            regions=[str(r) for r in body.get("regions", ["us-east-1"])],
            window_days=int(body.get("window_days", 14)),
            seed=int(body.get("seed", 42)),
        )
        with tempfile.TemporaryDirectory(prefix="cloudspend_ai_fixture_") as temp:
            path = write_bundle_zip(payloads, Path(temp) / "cloudspend_ai_bundle.zip")
            data = path.read_bytes()
        return send_file(io.BytesIO(data), mimetype="application/zip", as_attachment=True, download_name="cloudspend_ai_bundle.zip")
    except (AIProviderError, ValueError) as exc:
        return jsonify({"error": str(exc)}), 400


@bp.app_errorhandler(413)
def too_large(_error):
    return jsonify({"error": f"Upload exceeds the configured {_settings().max_upload_mb} MB limit."}), 413
