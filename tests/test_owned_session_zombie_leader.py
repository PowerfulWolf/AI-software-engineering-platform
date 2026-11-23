from __future__ import annotations

import struct

from ai_software_engineer.owned_sessions import _zombie_leader_identity


def _record(*, pid: int, pgid: int, state: int, sec: int = 1_795_417_157, usec: int = 918_165):
    raw = bytearray(648)
    struct.pack_into("<qi", raw, 0, sec, usec)
    raw[36] = state
    struct.pack_into("<i", raw, 40, pid)
    struct.pack_into("<i", raw, 564, pgid)
    return bytes(raw)


def test_unreaped_session_leader_zombie_keeps_its_birth_identity() -> None:
    identity = _zombie_leader_identity(4242, _record(pid=4242, pgid=4242, state=5))
    assert identity is not None
    assert identity.process_id == identity.group_id == identity.session_id == 4242
    assert identity.birth_identity == "darwin-time:1795417157:918165"


def test_non_leader_live_or_mismatched_records_are_not_admitted() -> None:
    assert _zombie_leader_identity(4242, _record(pid=4242, pgid=1, state=5)) is None
    assert _zombie_leader_identity(4242, _record(pid=4242, pgid=4242, state=2)) is None
    assert _zombie_leader_identity(4242, _record(pid=4243, pgid=4242, state=5)) is None
    assert _zombie_leader_identity(4242, _record(pid=4242, pgid=4242, state=5, sec=0)) is None
    assert _zombie_leader_identity(4242, b"") is None
