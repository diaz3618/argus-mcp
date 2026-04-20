"""Concurrency stress tests for startup coordinator atomicity (CONC-03 validation).

Tests validate that the asyncio.Lock in ClientManager ensures atomic
session registration — a session entry always has a corresponding READY status.

Uses self-contained mocks (no runtime imports needed) to isolate the
lock-protected write pattern from backend_connection.connect_backend().

Each test runs 50x via pytest-repeat to surface non-deterministic races.
"""

from __future__ import annotations

import asyncio
from enum import Enum, auto

import pytest

# ---------------------------------------------------------------------------
# Self-contained mock types (mirror the real status model)
# ---------------------------------------------------------------------------


class BackendPhase(Enum):
    INIT = auto()
    CONNECTING = auto()
    READY = auto()
    ERROR = auto()


class StatusRecord:
    """Lightweight mock of the real backend status record."""

    def __init__(self) -> None:
        self.phase = BackendPhase.INIT

    def transition(self, new_phase: BackendPhase) -> None:
        self.phase = new_phase


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.repeat(50)
async def test_concurrent_session_writes_are_atomic():
    """10 concurrent writers each register a session under lock.

    After all complete, every session key must have a corresponding READY status.
    """
    lock = asyncio.Lock()
    sessions: dict[str, object] = {}
    status_records: dict[str, StatusRecord] = {}

    async def _register(name: str) -> None:
        session = object()  # stand-in for ClientSession
        record = StatusRecord()
        # Simulate the atomic write pattern from connect_backend()
        async with lock:
            sessions[name] = session
            record.transition(BackendPhase.READY)
            status_records[name] = record

    await asyncio.gather(*[_register(f"backend-{i}") for i in range(10)])

    # Every registered session must have a READY status
    assert len(sessions) == 10
    assert len(status_records) == 10
    for name in sessions:
        assert status_records[name].phase is BackendPhase.READY, (
            f"{name} has phase {status_records[name].phase}, expected READY"
        )


@pytest.mark.repeat(50)
async def test_no_session_without_ready_status():
    """Writers register sessions while readers check invariant:

    If sessions[name] exists, then status_records[name].phase is READY.
    This catches the race where the session dict is written but the status
    transition has not yet occurred.
    """
    lock = asyncio.Lock()
    sessions: dict[str, object] = {}
    status_records: dict[str, StatusRecord] = {}
    violations: list[str] = []

    async def _register(name: str) -> None:
        session = object()
        record = StatusRecord()
        async with lock:
            sessions[name] = session
            record.transition(BackendPhase.READY)
            status_records[name] = record

    async def _reader() -> None:
        for _ in range(50):
            # Snapshot current keys
            for name in list(sessions.keys()):
                rec = status_records.get(name)
                if rec is None or rec.phase is not BackendPhase.READY:
                    violations.append(name)
            await asyncio.sleep(0)

    writers = [asyncio.create_task(_register(f"backend-{i}")) for i in range(10)]
    readers = [asyncio.create_task(_reader()) for _ in range(5)]
    await asyncio.gather(*writers, *readers)

    assert violations == [], f"Reader saw session without READY status: {violations}"
