from __future__ import annotations

import secrets
from pathlib import Path

from flask import Flask, session

from cloudspend.config import Settings
from cloudspend.storage import ScanStore


def create_app(settings: Settings | None = None) -> Flask:
    settings = settings or Settings.from_env()
    settings.ensure_local_dirs(Path.cwd())
    app = Flask(__name__, template_folder="templates", static_folder="static")
    app.secret_key = settings.secret_key
    app.config["MAX_CONTENT_LENGTH"] = settings.max_upload_bytes
    app.config["CLOUDSPEND_SETTINGS"] = settings
    app.config["CLOUDSPEND_STORE"] = ScanStore(settings.database_url)

    from cloudspend.web.routes import bp

    app.register_blueprint(bp)

    @app.context_processor
    def inject_csrf():
        token = session.get("csrf_token")
        if not token:
            token = secrets.token_urlsafe(32)
            session["csrf_token"] = token
        return {"csrf_token": token}

    @app.after_request
    def secure_headers(response):
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault("Permissions-Policy", "geolocation=(), microphone=(), camera=()")
        response.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; font-src 'self' https://fonts.gstatic.com; img-src 'self' data:; connect-src 'self' http://127.0.0.1:*; base-uri 'self'; frame-ancestors 'none'",
        )
        return response

    return app
