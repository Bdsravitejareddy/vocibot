from dataclasses import dataclass, field
from uuid import uuid4


@dataclass
class LocalPipelineDiagnostics:
    timings: dict[str, float] = field(default_factory=dict)
    warnings: list[dict[str, str]] = field(default_factory=list)

    def record_timing(self, stage: str, milliseconds: float) -> None:
        self.timings[stage] = milliseconds

    def record_warning(self, category: str, message: str) -> None:
        self.warnings.append({"category": category, "message": message})


@dataclass(frozen=True)
class MockEMRResult:
    updated: bool
    reference: str


class MockEMRUpdater:
    def update(self, record: dict) -> MockEMRResult:
        return MockEMRResult(updated=True, reference=f"mock-emr-{uuid4().hex[:10]}")
