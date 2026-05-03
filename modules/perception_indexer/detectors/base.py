from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class DetectorResult:
    detector_name: str
    score: float
    possible_page_type: str
    region_ids: list[str] = field(default_factory=list)
    element_ids: list[str] = field(default_factory=list)
    text_ids: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
