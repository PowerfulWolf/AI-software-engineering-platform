"""Read projections of immutable gaps and their approved resolutions."""

from ai_software_engineer.domain.model import DomainModel
from ai_software_engineer.knowledge.gaps import KnowledgeGap, KnowledgeResolution
from ai_software_engineer.knowledge.models import KnowledgeError
from ai_software_engineer.knowledge.store import KnowledgeRecordStore


class KnowledgeGapView(DomainModel):
    gap: KnowledgeGap
    resolution: KnowledgeResolution | None = None
    is_current: bool


def read_gap_view(
    records: KnowledgeRecordStore, gap: KnowledgeGap, *, current_gap_id: str | None
) -> KnowledgeGapView:
    gap.validate_integrity()
    resolution = records.find("gap-resolutions", gap.gap_id, KnowledgeResolution)
    if resolution is not None:
        resolution.validate_integrity()
        if (
            resolution.gap_id != gap.gap_id
            or resolution.previous_run_id != gap.binding.run_id
            or records.get("resolutions", resolution.resolution_id, KnowledgeResolution)
            != resolution
        ):
            raise KnowledgeError("RESOLUTION_LINEAGE")
    return KnowledgeGapView(gap=gap, resolution=resolution, is_current=gap.gap_id == current_gap_id)
