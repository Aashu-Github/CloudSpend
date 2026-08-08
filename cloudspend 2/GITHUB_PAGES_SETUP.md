# CloudSpend — GitHub Pages + Flask API deployment

CloudSpend now has two presentation modes without changing the core FinOps engine:

- `docs/` is a static GitHub Pages frontend.
- Flask remains the Python backend and exposes `/api/public/*` endpoints for demo/file analysis.
- The original Flask/Jinja UI remains available for local use, including Live AWS scanning.

## 1. Deploy the Flask API to Render

The repository includes `render.yaml`.

1. Push this repository to GitHub.
2. In Render, choose **New > Blueprint** and select the repository.
3. Render reads `render.yaml` and creates the `cloudspend-api` web service.
4. Wait for `/health` to report OK.
5. Render will normally use `https://cloudspend-api.onrender.com` if that service name is available.

If Render gives you a different URL, edit:

```text
docs/assets/config.js
```

and set `productionApiBaseUrl` to the exact Render URL.

The hosted database is intentionally SQLite under `/tmp`, so demo/import scan history is temporary and may disappear when the Render instance restarts. That is acceptable for the portfolio demo and avoids pretending the hosted demo is durable storage.

## 2. Enable GitHub Pages

The repository includes `.github/workflows/pages.yml`.

In GitHub:

1. Open **Settings > Pages**.
2. Under **Build and deployment**, choose **GitHub Actions** as the source.
3. Push to `main` or manually run **Deploy GitHub Pages frontend** from Actions.

For a repository named `cloudspend`, the frontend should become:

```text
https://aashu-github.github.io/cloudspend/
```

## 3. Hosted capabilities

The GitHub Pages version supports:

- Try Demo
- JSON/CSV/XLSX/ZIP file upload
- deterministic optimizer results
- recommendations and evidence
- cost/utilization charts
- resource details
- JSON/CSV export links

Live AWS remains local-only. GitHub Pages cannot access the AWS CLI profile or SSO session stored on a visitor's computer, and CloudSpend intentionally does not request AWS access keys in the browser.

## 4. Local development

Terminal 1 — Flask API/local app:

```bash
./scripts/run.sh
```

Terminal 2 — static Pages frontend preview:

```bash
./scripts/run_pages.sh
```

Open `http://127.0.0.1:8000`. The static frontend automatically uses `http://127.0.0.1:8080` as its API while running on localhost.

For a real read-only AWS scan, use the Flask/local UI or CLI:

```bash
./scripts/run.sh --aws-profile cloudspend-readonly --regions us-east-1
```
