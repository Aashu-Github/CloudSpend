from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    return int(raw) if raw not in (None, "") else default


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    return float(raw) if raw not in (None, "") else default


@dataclass(slots=True)
class Settings:
    app_env: str = "development"
    host: str = "127.0.0.1"
    port: int = 8080
    database_url: str = "sqlite:///./data/cloudspend.db"
    max_upload_mb: int = 50
    max_zip_files: int = 50
    max_zip_uncompressed_mb: int = 200
    max_zip_compression_ratio: float = 100.0
    default_observation_days: int = 14
    idle_cpu_avg_threshold: float = 5.0
    idle_cpu_p95_threshold: float = 20.0
    idle_network_avg_bytes_threshold: float = 5_000_000.0
    rightsize_cpu_avg_threshold: float = 20.0
    rightsize_cpu_p95_threshold: float = 40.0
    orphan_ebs_min_age_days: int = 7
    anomaly_percent_threshold: float = 50.0
    anomaly_absolute_threshold: float = 10.0
    ai_provider: str = "none"
    ollama_base_url: str = "http://127.0.0.1:11434"
    ollama_model: str = ""
    aws_profile: str = ""
    aws_regions: str = "us-east-1"
    secret_key: str = "cloudspend-local-dev"

    @classmethod
    def from_env(cls) -> "Settings":
        try:
            from dotenv import load_dotenv

            load_dotenv()
        except Exception:
            pass
        return cls(
            app_env=os.getenv("APP_ENV", "development"),
            host=os.getenv("HOST", "127.0.0.1"),
            port=_env_int("PORT", 8080),
            database_url=os.getenv("DATABASE_URL", "sqlite:///./data/cloudspend.db"),
            max_upload_mb=_env_int("MAX_UPLOAD_MB", 50),
            max_zip_files=_env_int("MAX_ZIP_FILES", 50),
            max_zip_uncompressed_mb=_env_int("MAX_ZIP_UNCOMPRESSED_MB", 200),
            max_zip_compression_ratio=_env_float("MAX_ZIP_COMPRESSION_RATIO", 100.0),
            default_observation_days=_env_int("DEFAULT_OBSERVATION_DAYS", 14),
            idle_cpu_avg_threshold=_env_float("IDLE_CPU_AVG_THRESHOLD", 5.0),
            idle_cpu_p95_threshold=_env_float("IDLE_CPU_P95_THRESHOLD", 20.0),
            idle_network_avg_bytes_threshold=_env_float("IDLE_NETWORK_AVG_BYTES_THRESHOLD", 5_000_000.0),
            rightsize_cpu_avg_threshold=_env_float("RIGHTSIZE_CPU_AVG_THRESHOLD", 20.0),
            rightsize_cpu_p95_threshold=_env_float("RIGHTSIZE_CPU_P95_THRESHOLD", 40.0),
            orphan_ebs_min_age_days=_env_int("ORPHAN_EBS_MIN_AGE_DAYS", 7),
            anomaly_percent_threshold=_env_float("ANOMALY_PERCENT_THRESHOLD", 50.0),
            anomaly_absolute_threshold=_env_float("ANOMALY_ABSOLUTE_THRESHOLD", 10.0),
            ai_provider=os.getenv("AI_PROVIDER", "none").strip().lower(),
            ollama_base_url=os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434").rstrip("/"),
            ollama_model=os.getenv("OLLAMA_MODEL", ""),
            aws_profile=os.getenv("AWS_PROFILE", ""),
            aws_regions=os.getenv("AWS_REGIONS", "us-east-1"),
            secret_key=os.getenv("SECRET_KEY", "cloudspend-local-dev"),
        )

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024

    @property
    def max_zip_uncompressed_bytes(self) -> int:
        return self.max_zip_uncompressed_mb * 1024 * 1024

    def regions(self) -> list[str]:
        return [r.strip() for r in self.aws_regions.split(",") if r.strip()]

    def ensure_local_dirs(self, root: Path | None = None) -> None:
        root = root or Path.cwd()
        (root / "data").mkdir(parents=True, exist_ok=True)
