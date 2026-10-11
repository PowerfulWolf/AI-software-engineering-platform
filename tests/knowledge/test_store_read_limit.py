"""Read projections bound a namespace before parsing any record bytes."""

from pathlib import Path

import pytest

from ai_software_engineer.domain.model import DomainModel
from ai_software_engineer.knowledge.models import KnowledgeError
from ai_software_engineer.knowledge.store import KnowledgeRecordStore


class Record(DomainModel):
    value: int


def test_list_limit_rejects_namespace_before_reading_records(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    writer = KnowledgeRecordStore(tmp_path)
    for index in range(3):
        writer.put("records", str(index), Record(value=index))
    reader = KnowledgeRecordStore(tmp_path, read_only=True)

    def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("over-limit namespace must not read payloads")

    monkeypatch.setattr(reader, "_read_name", forbidden)
    with pytest.raises(KnowledgeError, match="STORE_RECORD_LIMIT"):
        reader.list("records", Record, limit=2)


def test_list_limit_preserves_default_order_and_namespace_isolation(tmp_path: Path) -> None:
    writer = KnowledgeRecordStore(tmp_path)
    for index in range(2):
        writer.put("records", str(index), Record(value=index))
    for index in range(4):
        writer.put("other-records", str(index), Record(value=index))
    reader = KnowledgeRecordStore(tmp_path, read_only=True)
    before = {path.name: path.read_bytes() for path in tmp_path.iterdir()}
    assert reader.list("records", Record, limit=2) == reader.list("records", Record)
    assert reader.list("absent", Record, limit=1) == ()
    assert {path.name: path.read_bytes() for path in tmp_path.iterdir()} == before


@pytest.mark.parametrize("limit", [0, -1, True])
def test_list_rejects_invalid_limit(tmp_path: Path, limit: int) -> None:
    with pytest.raises(KnowledgeError, match="STORE_RECORD_LIMIT"):
        KnowledgeRecordStore(tmp_path).list("records", Record, limit=limit)
