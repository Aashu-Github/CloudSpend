from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from sqlalchemy import DateTime, String, Text, create_engine, select
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column

from cloudspend.models.canonical import CloudResource
from cloudspend.models.recommendations import Recommendation
from cloudspend.optimizer.engine import OptimizationResult


class Base(DeclarativeBase):
    pass


class ScanRecord(Base):
    __tablename__ = "scans"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    source_mode: Mapped[str] = mapped_column(String(32))
    source_info_json: Mapped[str] = mapped_column(Text, default="{}")
    warnings_json: Mapped[str] = mapped_column(Text, default="[]")
    errors_json: Mapped[str] = mapped_column(Text, default="[]")
    resources_json: Mapped[str] = mapped_column(Text)
    recommendations_json: Mapped[str] = mapped_column(Text)


class ScanStore:
    def __init__(self, database_url: str):
        self.database_url = database_url
        if database_url.startswith("sqlite:///./"):
            relative = database_url.removeprefix("sqlite:///./")
            Path(relative).parent.mkdir(parents=True, exist_ok=True)
        self.engine = create_engine(database_url, future=True)
        Base.metadata.create_all(self.engine)

    def save_scan(
        self,
        result: OptimizationResult,
        source_mode: str,
        source_info: dict[str, Any] | None = None,
        warnings: list[str] | None = None,
        errors: list[str] | None = None,
    ) -> str:
        scan_id = str(uuid4())
        resources = [r.model_dump(mode="json") for r in result.resources]
        recs = [r.model_dump(mode="json") for r in result.recommendations]
        record = ScanRecord(
            id=scan_id,
            source_mode=source_mode,
            source_info_json=json.dumps(source_info or {}, default=str),
            warnings_json=json.dumps(warnings or [], default=str),
            errors_json=json.dumps(errors or [], default=str),
            resources_json=json.dumps(resources, default=str),
            recommendations_json=json.dumps(recs, default=str),
        )
        with Session(self.engine) as session:
            session.add(record)
            session.commit()
        return scan_id

    def get_scan(self, scan_id: str) -> dict[str, Any] | None:
        with Session(self.engine) as session:
            record = session.get(ScanRecord, scan_id)
            if record is None:
                return None
            return self._deserialize(record)

    def list_scans(self, limit: int = 10) -> list[dict[str, Any]]:
        with Session(self.engine) as session:
            records = session.scalars(select(ScanRecord).order_by(ScanRecord.created_at.desc()).limit(limit)).all()
            return [self._deserialize(r, include_payload=False) for r in records]

    def get_resource(self, scan_id: str, resource_id: str) -> tuple[CloudResource, list[Recommendation]] | None:
        scan = self.get_scan(scan_id)
        if not scan:
            return None
        resource = next((r for r in scan["resources"] if r.resource_id == resource_id), None)
        if resource is None:
            return None
        recs = [r for r in scan["recommendations"] if r.resource_id == resource_id]
        return resource, recs

    @staticmethod
    def _deserialize(record: ScanRecord, include_payload: bool = True) -> dict[str, Any]:
        base: dict[str, Any] = {
            "id": record.id,
            "created_at": record.created_at,
            "source_mode": record.source_mode,
            "source_info": json.loads(record.source_info_json or "{}"),
            "warnings": json.loads(record.warnings_json or "[]"),
            "errors": json.loads(record.errors_json or "[]"),
        }
        if include_payload:
            base["resources"] = [CloudResource.model_validate(x) for x in json.loads(record.resources_json)]
            base["recommendations"] = [Recommendation.model_validate(x) for x in json.loads(record.recommendations_json)]
        return base
