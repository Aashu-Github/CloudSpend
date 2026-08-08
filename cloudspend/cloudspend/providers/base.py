from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from pydantic import BaseModel, Field

from cloudspend.models.canonical import CloudResource


class ProviderResult(BaseModel):
    resources: list[CloudResource]
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    source_info: dict[str, Any] = Field(default_factory=dict)


class BaseProvider(ABC):
    @abstractmethod
    def load(self) -> ProviderResult:
        raise NotImplementedError
