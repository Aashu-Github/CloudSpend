# CloudSpend

**Automated Cloud Cost Visualizer & Optimizer**

CloudSpend is a local-first AWS FinOps project that ingests infrastructure, utilization, and cost data, normalizes every source into the same canonical model, identifies waste with deterministic rules, and explains the evidence behind potential savings.

It supports three interchangeable data paths:

1. **Demo mode** — bundled, deterministic mock AWS API responses.
2. **File mode** — drag/drop or CLI ingestion for `.json`, `.csv`, `.xlsx`, and `.zip`.
3. **Live AWS mode** — Boto3 using an existing AWS profile, IAM Identity Center/SSO session, environment credentials, or another standard credential-chain source.

The optimizer does **not** know which provider produced the data. All providers end at canonical Pydantic objects before the rule engine runs.

```text
Demo Fixture ----\
Uploaded File ----> Provider / Adapter -> Canonical Model -> Validation -> Rule Engine -> Results
Live Boto3 ------/
```

CloudSpend is read-only in the MVP. It generates advisory findings; it does not stop instances, resize infrastructure, or delete volumes.

## What is implemented

- Static GitHub Pages frontend in `docs/` with the `#050508` background and `#69acc2` accent design system.
- Flask/Jinja local UI plus a Flask REST API for the hosted demo/file-analysis frontend.
- Offline-bundled Plotly.js dashboard visualization.
- Deterministic seeded AWS-like fixture generator.
- Optional Ollama-compatible AI fixture generation, schema mapping, and plain-language explanation boundary.
- Native detection/normalization for selected EC2, EBS, CloudWatch, and Cost Explorer response shapes.
- Canonical JSON and tabular import plus selected CUR-like CSV/XLSX import.
- Secure manifest-driven ZIP ingestion with traversal, file-count, expansion-size, and compression-ratio checks.
- Versioned optimization rules for idle EC2, rightsizing, scheduling, unattached EBS, and cost anomalies.
- Explicit `actual_resource_cost`, `allocated_cost`, and `estimated_resource_cost` provenance.
- SQLite scan history, JSON/CSV report export, rule evidence, and missing-data warnings.
- Read-only Boto3 adapter with regional partial-failure handling.
- Pytest coverage for deterministic generation, normalization, rules, security, persistence, AI validation, web routes, and Moto-backed AWS inventory.

## Stack

- Python 3.11+
- Flask REST API + Jinja2 for local mode
- GitHub Pages + HTML/CSS/vanilla JavaScript for hosted frontend
- Boto3
- Pandas
- Pydantic
- SQLAlchemy + SQLite
- Plotly.js
- Pytest
- Moto
- Optional Ollama-compatible local AI provider

No Kubernetes, Kafka, Redis, Celery, or JavaScript framework is required.

## Repository layout

```text
cloudspend/
├── app.py
├── pyproject.toml
├── render.yaml
├── .env.example
├── docs/                 # GitHub Pages frontend
│   ├── index.html
│   ├── import.html
│   ├── aws.html
│   ├── scan.html
│   ├── resource.html
│   └── assets/
├── cloudspend/
│   ├── config.py
│   ├── storage.py
│   ├── models/
│   │   ├── canonical.py
│   │   └── recommendations.py
│   ├── providers/
│   │   ├── base.py
│   │   ├── aws_live.py
│   │   ├── fixture.py
│   │   └── file_upload.py
│   ├── ingestion/
│   │   ├── detect.py
│   │   ├── parse_json.py
│   │   ├── parse_csv.py
│   │   ├── parse_xlsx.py
│   │   ├── parse_zip.py
│   │   ├── normalize.py
│   │   └── validators.py
│   ├── optimizer/
│   │   ├── engine.py
│   │   ├── pricing.py
│   │   ├── idle_ec2.py
│   │   ├── rightsize_ec2.py
│   │   ├── orphan_ebs.py
│   │   ├── schedule_candidates.py
│   │   └── cost_anomaly.py
│   ├── ai/
│   │   ├── provider.py
│   │   ├── prompts.py
│   │   ├── fixture_generator.py
│   │   ├── schema_mapper.py
│   │   └── explainer.py
│   ├── web/
│   │   ├── routes.py
│   │   ├── templates/
│   │   └── static/
│   └── cli.py
├── examples/
│   └── cloudspend-readonly-policy.json
├── schemas/
│   ├── mock_bundle.schema.json
│   └── canonical_resource.schema.json
├── samples/
│   ├── mock_aws_bundle.zip
│   ├── CloudSpend_mock_aws_bundle.zip
│   ├── ec2_describe_instances.json
│   └── cur_like_sample.csv
├── scripts/
│   ├── setup.sh
│   ├── run.sh
│   ├── test.sh
│   ├── run_pages.sh
│   └── generate_demo.sh
├── GITHUB_PAGES_SETUP.md
└── tests/
```

## Hosted architecture

The portfolio deployment is split so GitHub Pages can host the real frontend while the Python logic remains unchanged behind a Flask API:

```text
GitHub Pages (docs/)
        |
        | HTTPS JSON / file upload
        v
Flask API on Render
        |
        +--> providers -> canonical Pydantic models -> deterministic optimizer
        +--> temporary SQLite scan results
```

The hosted frontend can run the demo, upload supported AWS exports, display recommendations, render charts, inspect resource evidence, and download reports. **Live AWS is intentionally local-only** because a GitHub Pages site cannot access a visitor's local AWS CLI/SSO credential chain and CloudSpend does not ask users to paste long-term AWS secrets into a browser.

Deployment instructions are in [`GITHUB_PAGES_SETUP.md`](GITHUB_PAGES_SETUP.md). The included `render.yaml` defines the backend service and `.github/workflows/pages.yml` publishes `docs/` to GitHub Pages.

### Preview the split frontend locally

Run the Flask API/local application in one terminal:

```bash
./scripts/run.sh
```

Then run the GitHub Pages frontend in a second terminal:

```bash
./scripts/run_pages.sh
```

Open `http://127.0.0.1:8000`. On localhost, the static frontend automatically calls `http://127.0.0.1:8080`.

## Prerequisites

Required: Bash, Git, and Python 3.11 or newer.

Optional for live AWS mode: AWS CLI v2 and a profile/session with read-only permissions for the resources being scanned.

Optional for local AI features: Ollama or another compatible local model server.

## First-time setup

```bash
git clone https://github.com/Aashu-Github/cloudspend.git
cd cloudspend
chmod +x scripts/*.sh
./scripts/setup.sh
```

`setup.sh` creates `.venv`, installs the package and development dependencies, creates `.env` from `.env.example` if needed, and creates the local data directory.

## Run the zero-cost demo

```bash
./scripts/run.sh --demo
```

Then open:

```text
http://127.0.0.1:8080
```

The terminal also prints the preloaded demo scan URL. Demo analysis uses `samples/mock_aws_bundle.zip`; it does not call AWS or require AI.

## Drop a file into the website

```bash
./scripts/run.sh
```

Open the **Import** page and drag a supported file into the upload zone. After server-side safety validation, the app detects the source shape, normalizes it, validates canonical resources, runs the deterministic optimizer, and navigates to results.

Supported MVP formats:

- `.json` — selected native AWS response family or CloudSpend canonical export.
- `.csv` — canonical rows or selected CUR-like data.
- `.xlsx` — canonical/CUR-like worksheet tables; macros are not executed and `.xlsm` is rejected.
- `.zip` — CloudSpend bundle with `manifest.json` plus the expected AWS-like response files.

PDF/prose ingestion is intentionally outside the MVP.

### CLI file mode

```bash
python -m cloudspend.cli analyze-file ./my-export.csv --output ./out/report.json
```

You can also preload a file into the web app:

```bash
./scripts/run.sh --file ./samples/mock_aws_bundle.zip
```

## Generate deterministic mock AWS API responses

```bash
./scripts/generate_demo.sh --scenario mixed-fleet --resources 50 --seed 42
```

The default output is `samples/mock_aws_bundle.zip`. The bundle contains:

```text
manifest.json
ec2_describe_instances.json
ec2_describe_volumes.json
cloudwatch_get_metric_data.json
cost_explorer_get_cost_and_usage_with_resources.json
```

The deterministic generator is seed-reproducible. It produces steady, idle, low-utilization, schedule-shaped, bursty, and non-optimizable resources. Cross-file resource IDs, timestamps, attachments, and non-negative costs are validated before the ZIP is written.

## Hosted REST API

The GitHub Pages frontend uses the stateless public endpoints below. These endpoints do not change the deterministic recommendation authority.

```text
GET  /api/public/health
POST /api/public/demo
POST /api/public/import
GET  /api/public/scans/<scan_id>
GET  /api/public/scans/<scan_id>/resources/<resource_id>
```

Browser CORS access is restricted by the `CORS_ORIGINS` environment variable. Local Jinja form actions keep their session CSRF checks.

## Live AWS mode

CloudSpend uses Boto3's standard credential provider chain. **Do not paste long-term access keys into CloudSpend.**

### AWS CLI profile

```bash
aws configure --profile cloudspend-readonly
aws sts get-caller-identity --profile cloudspend-readonly
./scripts/run.sh --aws-profile cloudspend-readonly --regions us-east-1
```

### IAM Identity Center / SSO

```bash
aws configure sso --profile cloudspend-sso
aws sso login --profile cloudspend-sso
./scripts/run.sh --aws-profile cloudspend-sso --regions us-east-1,us-west-2
```

The live adapter collects EC2 inventory, EBS inventory, EC2 CloudWatch CPU/network metrics, and resource-level Cost Explorer data when that account capability is enabled and permitted. Cost Explorer denial/unavailability does not fail the inventory scan.

A least-privilege starting example is in `examples/cloudspend-readonly-policy.json`.

## Recommendation rules

CloudSpend's recommendation authority is deterministic and versioned.

| Rule | Default evidence | Output |
|---|---|---|
| `EC2-IDLE-001` | running, >=7 days, CPU avg <5%, p95/max <20%, low network, no burst signal | review stop/schedule/terminate candidate |
| `EC2-RIGHTSIZE-001` | CPU avg <20%, p95 <40%, no burst concern; memory <40% if present | review one-size-down candidate |
| `EC2-SCHEDULE-001` | dev/test/staging or explicit eligibility, utilization concentrated in business hours | review schedule candidate |
| `EBS-ORPHAN-001` | available/no attachments, age >7 days | review/snapshot/delete candidate |
| `COST-ANOMALY-001` | latest daily spend exceeds rolling baseline by configured % and absolute threshold | alert for investigation; no invented root cause |

Missing EC2 memory telemetry is never interpreted as `0%`. It remains unknown and lowers confidence where relevant.

## Cost provenance

CloudSpend never relabels an estimate as billed actual cost. Each resource can carry:

- `actual_resource_cost`
- `allocated_cost`
- `estimated_resource_cost`

When resource-level Cost Explorer data is unavailable, a small local **us-east-1** pricing snapshot can provide clearly labeled portfolio/demo estimates for supported EC2/EBS types, including modeled gp3 IOPS/throughput add-ons. Other regions remain unavailable rather than reusing the wrong regional price. This is not a substitute for an AWS bill or the AWS Pricing API.

## Optional AI

AI is disabled by default:

```bash
AI_PROVIDER=none
```

For a local Ollama-compatible provider:

```bash
AI_PROVIDER=ollama
OLLAMA_BASE_URL=http://127.0.0.1:11434
OLLAMA_MODEL=<your-local-model>
```

AI may generate synthetic fixtures, propose mappings for unfamiliar schemas, or explain an existing deterministic finding. It may **not** change measured utilization, costs, rule thresholds, confidence, or remediation decisions. Generated fixture output must pass cross-file validation and canonical Pydantic validation before persistence.

Example:

```bash
python -m cloudspend.cli generate-fixture \
  --scenario "a 40-resource startup account with three obvious zombie resources, two spiky batch workers, and four unattached EBS volumes" \
  --resources 40 \
  --ai
```

## Security controls

- Binds to `127.0.0.1` by default.
- Uses the Boto3 credential chain; no secret-key form exists.
- Contains no destructive AWS API operations in the MVP.
- State-changing web endpoints use a per-session CSRF token.
- Uploaded files use allowlisted extensions, randomized temporary storage, size checks, and signature checks where practical.
- ZIP files are checked for path traversal, file count, total expansion size, and suspicious compression ratios before extraction.
- `.xlsm` and executable formats are rejected.
- Temporary raw uploads are deleted after parsing.
- Security headers/CSP are applied by the Flask app.
- Logs and persisted scan summaries are designed not to store AWS secrets.

## Tests

```bash
./scripts/test.sh
```

Or:

```bash
python -m pytest -q
```

The suite covers rule boundaries, deterministic fixture consistency, native/file normalization, cost provenance, upload traversal rejection, SQLite persistence, AI output validation, Flask smoke/security behavior, and Moto-backed EC2/EBS inventory.

## Environment variables

See `.env.example`. Important defaults include:

```text
HOST=127.0.0.1
PORT=8080
DATABASE_URL=sqlite:///./data/cloudspend.db
MAX_UPLOAD_MB=50
MAX_ZIP_FILES=50
MAX_ZIP_UNCOMPRESSED_MB=200
DEFAULT_OBSERVATION_DAYS=14
IDLE_CPU_AVG_THRESHOLD=5
IDLE_CPU_P95_THRESHOLD=20
RIGHTSIZE_CPU_AVG_THRESHOLD=20
RIGHTSIZE_CPU_P95_THRESHOLD=40
ORPHAN_EBS_MIN_AGE_DAYS=7
AI_PROVIDER=none
AWS_REGIONS=us-east-1
```

## UI design

The UI follows the layout language of the NBA Playoff Predictor reference site while preserving CloudSpend's dark palette: `#050508` primary background and `#69acc2` principal accent. It uses the reference-style split hero, editorial project list, compact mono navigation, bordered inner-page layouts, and DM Serif Display / DM Mono / Instrument Sans typography.

The Import page uses a native file-label interaction so clicking the drop area always opens the system file picker, while external JavaScript handles drag/drop and upload progress without violating the application's CSP. Live AWS scans are submitted asynchronously; credential/profile/region failures stay on the Live AWS page and appear in an in-page modal rather than navigating to an error page.

## Important limitations

- CloudSpend is not a replacement for AWS Compute Optimizer or Cost Optimization Hub.
- Resource-level Cost Explorer data is account-dependent and may require opt-in/permissions.
- EC2 guest memory normally requires CloudWatch Agent/custom telemetry.
- The local pricing snapshot is intentionally small, illustrative, and limited to `us-east-1`; unsupported regions/types stay unavailable.
- Live AWS behavior depends on account permissions, region support, and telemetry availability; partial success is surfaced instead of silently fabricated.
- Recommendations require human review.

## License

MIT
