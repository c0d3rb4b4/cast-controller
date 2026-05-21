from __future__ import annotations

import asyncio
import logging
from contextlib import suppress
from datetime import datetime

from cast_client import CastClient
from config import Settings
from models import ControllerState, DesiredState, ObservedState, utc_now
from state_store import StateStore

logger = logging.getLogger(__name__)


class Reconciler:
    def __init__(
        self,
        *,
        settings: Settings,
        state_store: StateStore,
        cast_client: CastClient,
    ):
        self.settings = settings
        self.state_store = state_store
        self.cast_client = cast_client
        self._task: asyncio.Task[None] | None = None
        self._trigger: asyncio.Event | None = None
        self._stopping = False
        self._pending_trigger = False

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    async def start(self) -> None:
        if self.running:
            return

        self._stopping = False
        self._trigger = asyncio.Event()
        if self._pending_trigger:
            self._trigger.set()
            self._pending_trigger = False
        self._task = asyncio.create_task(self._run_loop(), name="cast-reconciler")

    async def stop(self) -> None:
        self._stopping = True
        if self._trigger is not None:
            self._trigger.set()
        if self._task is not None:
            self._task.cancel()
            with suppress(asyncio.CancelledError):
                await self._task

    def request_now(self) -> None:
        logger.info("reconcile_requested")
        if self._trigger is None:
            self._pending_trigger = True
            return
        self._trigger.set()

    async def _run_loop(self) -> None:
        logger.info("reconcile_loop_started")
        while not self._stopping:
            if self._trigger is not None:
                self._trigger.clear()

            try:
                await self.reconcile_once()
            except Exception:
                logger.exception("reconcile_loop_error")

            if self._trigger is None:
                await asyncio.sleep(self.settings.reconcile_interval_s)
                continue

            try:
                await asyncio.wait_for(
                    self._trigger.wait(),
                    timeout=self.settings.reconcile_interval_s,
                )
            except asyncio.TimeoutError:
                pass

    async def reconcile_once(self, now: datetime | None = None) -> ControllerState:
        now = now or utc_now()
        state = self.state_store.load()

        if state.desired == DesiredState.ON:
            return await self._reconcile_on(state, now)

        return await self._reconcile_off(state)

    async def _reconcile_on(
        self,
        state: ControllerState,
        now: datetime,
    ) -> ControllerState:
        if state.observed == ObservedState.PLAYING:
            state.last_action = "already_playing"
            return self.state_store.save(state)

        blocked_reason = self._recast_blocked_reason(state, now)
        if blocked_reason is not None:
            state.last_action = blocked_reason
            return self.state_store.save(state)

        if not state.stream_url or not (state.device or self.settings.default_device_host):
            state.failure_count += 1
            state.last_action = "missing_cast_target"
            return self.state_store.save(state)

        state.last_cast_attempt_at = now
        try:
            result = await self.cast_client.cast_stream(
                device=state.device,
                device_host=state.device_host or self.settings.default_device_host,
                stream_url=state.stream_url,
                volume=state.volume,
            )
        except Exception:
            logger.exception("reconcile_cast_failed")
            state.failure_count += 1
            state.observed = ObservedState.UNKNOWN
            state.last_action = "reconcile_cast_failed"
            return self.state_store.save(state)

        state.observed = result.observed
        state.last_action = result.action
        self._apply_device_info(state, result.device)
        if result.ok and state.observed == ObservedState.PLAYING:
            state.failure_count = 0
            state.last_success_at = now
        elif result.ok:
            state.failure_count = 0
            state.last_action = f"{result.action}_not_playing"
        else:
            state.failure_count += 1

        return self.state_store.save(state)

    async def _reconcile_off(self, state: ControllerState) -> ControllerState:
        should_stop = state.observed in {
            ObservedState.PLAYING,
            ObservedState.PAUSED,
        } or state.last_action == "stop_requested"
        if not should_stop:
            return state

        try:
            result = await self.cast_client.stop(
                device=state.device,
                device_host=state.device_host or self.settings.default_device_host,
            )
        except Exception:
            logger.exception("reconcile_stop_failed")
            state.failure_count += 1
            state.observed = ObservedState.UNKNOWN
            state.last_action = "reconcile_stop_failed"
            return self.state_store.save(state)

        state.observed = result.observed
        state.last_action = result.action
        self._apply_device_info(state, result.device)
        if result.ok:
            state.failure_count = 0
            state.last_success_at = utc_now()
        else:
            state.failure_count += 1

        return self.state_store.save(state)

    def _recast_blocked_reason(
        self,
        state: ControllerState,
        now: datetime,
    ) -> str | None:
        if state.last_cast_attempt_at is None:
            return None

        elapsed_s = (now - state.last_cast_attempt_at).total_seconds()
        if state.failure_count > 0:
            if elapsed_s < self._failure_backoff_s(state.failure_count):
                return "recast_backoff"

        if state.observed in {ObservedState.IDLE, ObservedState.UNKNOWN}:
            return None

        if elapsed_s < self.settings.min_recast_interval_s:
            return "recast_rate_limited"

        return None

    def _failure_backoff_s(self, failure_count: int) -> float:
        base_delay = max(self.settings.min_recast_interval_s, 1)
        return min(base_delay * (2 ** max(failure_count - 1, 0)), 900)

    def _apply_device_info(self, state: ControllerState, device_info) -> None:
        if device_info is None:
            return

        state.device = device_info.name or state.device
        state.device_host = device_info.host or state.device_host
        state.device_port = device_info.port or state.device_port
        state.device_uuid = device_info.uuid or state.device_uuid
        state.device_model_name = device_info.model_name or state.device_model_name
