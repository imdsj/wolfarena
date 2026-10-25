"""Background service for server-authoritative room deadlines."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable

from .realtime import RealtimeHub
from .rooms import InMemoryRoomRepository, RoomMutation

logger = logging.getLogger(__name__)


class RoomTimerService:
    """Scan deadlines and broadcast each committed timeout immediately."""

    def __init__(
        self,
        repository: InMemoryRoomRepository,
        realtime: RealtimeHub,
        *,
        interval_seconds: float = 0.1,
        clock: Callable[[], float] = time.time,
    ) -> None:
        if interval_seconds <= 0:
            raise ValueError("interval_seconds 必须大于 0")
        self._repository = repository
        self._realtime = realtime
        self._interval_seconds = interval_seconds
        self._clock = clock
        self._task: asyncio.Task[None] | None = None
        self._stopping = asyncio.Event()

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    def start(self) -> None:
        if self.running:
            return
        self._stopping.clear()
        self._task = asyncio.create_task(self._run(), name="wolfarena-room-timers")

    async def stop(self) -> None:
        self._stopping.set()
        task = self._task
        self._task = None
        if task is None:
            return
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    async def tick(self, *, now: float | None = None) -> tuple[RoomMutation, ...]:
        mutations = self._repository.process_expired_deadlines(
            self._clock() if now is None else now
        )
        for mutation in mutations:
            await self._realtime.broadcast_mutation(mutation)
        return mutations

    async def _run(self) -> None:
        while not self._stopping.is_set():
            try:
                await self.tick()
            except Exception:
                # A malformed room must not stop timers for every other room.
                logger.exception("Room timer scan failed")
            await asyncio.sleep(self._interval_seconds)
