from __future__ import annotations

import pytest

from cast_client import CastResult
from config import Settings
from models import ControllerState, DesiredState, DeviceInfo, ObservedState, utc_now
from reconcile import Reconciler
from state_store import StateStore


class FakeCastClient:
    def __init__(self, result: CastResult):
        self.result = result
        self.cast_calls = 0
        self.stop_calls = 0

    async def cast_stream(self, **kwargs):
        self.cast_calls += 1
        return self.result

    async def stop(self, **kwargs):
        self.stop_calls += 1
        return CastResult(
            ok=True,
            action="stop_sent",
            observed=ObservedState.IDLE,
        )


@pytest.mark.anyio
async def test_reconcile_on_casts_when_not_playing(tmp_path) -> None:
    settings = Settings(
        _env_file=None,
        state_path=tmp_path / "state.json",
        default_device_host="192.168.68.13",
    )
    store = StateStore(settings.state_path)
    fake = FakeCastClient(
        CastResult(ok=True, action="cast_sent", observed=ObservedState.PLAYING)
    )
    store.save(
        ControllerState(
            desired=DesiredState.ON,
            observed=ObservedState.IDLE,
            device="Bedroom Nest Mini",
            stream_url="http://example.test/noise.m3u8",
        )
    )

    state = await Reconciler(
        settings=settings,
        state_store=store,
        cast_client=fake,
    ).reconcile_once()

    assert fake.cast_calls == 1
    assert state.observed == ObservedState.PLAYING
    assert state.last_action == "cast_sent"
    assert state.failure_count == 0


@pytest.mark.anyio
async def test_reconcile_on_does_nothing_when_already_playing(tmp_path) -> None:
    settings = Settings(
        _env_file=None,
        state_path=tmp_path / "state.json",
        default_device_host="192.168.68.13",
    )
    store = StateStore(settings.state_path)
    fake = FakeCastClient(
        CastResult(ok=True, action="cast_sent", observed=ObservedState.PLAYING)
    )
    store.save(
        ControllerState(
            desired=DesiredState.ON,
            observed=ObservedState.PLAYING,
            device="Bedroom Nest Mini",
            stream_url="http://example.test/noise.m3u8",
        )
    )

    state = await Reconciler(
        settings=settings,
        state_store=store,
        cast_client=fake,
    ).reconcile_once()

    assert fake.cast_calls == 0
    assert state.last_action == "already_playing"


@pytest.mark.anyio
async def test_reconcile_on_rate_limits_recent_cast(tmp_path) -> None:
    settings = Settings(
        _env_file=None,
        state_path=tmp_path / "state.json",
        default_device_host="192.168.68.13",
        min_recast_interval_s=60,
    )
    store = StateStore(settings.state_path)
    fake = FakeCastClient(
        CastResult(ok=True, action="cast_sent", observed=ObservedState.PLAYING)
    )
    now = utc_now()
    store.save(
        ControllerState(
            desired=DesiredState.ON,
            observed=ObservedState.PAUSED,
            device="Bedroom Nest Mini",
            stream_url="http://example.test/noise.m3u8",
            last_cast_attempt_at=now,
        )
    )

    state = await Reconciler(
        settings=settings,
        state_store=store,
        cast_client=fake,
    ).reconcile_once(now=now)

    assert fake.cast_calls == 0
    assert state.last_action == "recast_rate_limited"


@pytest.mark.anyio
async def test_reconcile_on_does_not_rate_limit_idle_cast_result(tmp_path) -> None:
    settings = Settings(
        _env_file=None,
        state_path=tmp_path / "state.json",
        default_device_host="192.168.68.13",
        min_recast_interval_s=60,
    )
    store = StateStore(settings.state_path)
    fake = FakeCastClient(
        CastResult(ok=True, action="cast_sent", observed=ObservedState.IDLE)
    )
    now = utc_now()
    store.save(
        ControllerState(
            desired=DesiredState.ON,
            observed=ObservedState.UNKNOWN,
            device="Bedroom Nest Mini",
            stream_url="http://example.test/noise.m3u8",
        )
    )
    reconciler = Reconciler(
        settings=settings,
        state_store=store,
        cast_client=fake,
    )

    first = await reconciler.reconcile_once(now=now)
    second = await reconciler.reconcile_once(now=now)

    assert fake.cast_calls == 2
    assert first.observed == ObservedState.IDLE
    assert first.last_action == "cast_sent_not_playing"
    assert first.failure_count == 0
    assert first.last_success_at is None
    assert second.last_action == "cast_sent_not_playing"


@pytest.mark.anyio
async def test_reconcile_on_uses_exponential_backoff_after_failure(tmp_path) -> None:
    settings = Settings(
        _env_file=None,
        state_path=tmp_path / "state.json",
        default_device_host="192.168.68.13",
        min_recast_interval_s=60,
    )
    store = StateStore(settings.state_path)
    fake = FakeCastClient(
        CastResult(ok=True, action="cast_sent", observed=ObservedState.PLAYING)
    )
    now = utc_now()
    store.save(
        ControllerState(
            desired=DesiredState.ON,
            observed=ObservedState.UNKNOWN,
            device="Bedroom Nest Mini",
            stream_url="http://example.test/noise.m3u8",
            failure_count=3,
            last_cast_attempt_at=now,
        )
    )

    state = await Reconciler(
        settings=settings,
        state_store=store,
        cast_client=fake,
    ).reconcile_once(now=now)

    assert fake.cast_calls == 0
    assert state.last_action == "recast_backoff"


@pytest.mark.anyio
async def test_reconcile_applies_discovered_device_info(tmp_path) -> None:
    settings = Settings(
        _env_file=None,
        state_path=tmp_path / "state.json",
        default_device_host="192.168.68.13",
    )
    store = StateStore(settings.state_path)
    fake = FakeCastClient(
        CastResult(
            ok=True,
            action="cast_sent",
            observed=ObservedState.PLAYING,
            device=DeviceInfo(
                name="Bedroom Nest Mini",
                host="192.168.68.13",
                port=8009,
                uuid="abc123",
                model_name="Google Nest Mini",
            ),
        )
    )
    store.save(
        ControllerState(
            desired=DesiredState.ON,
            observed=ObservedState.IDLE,
            device="Bedroom Nest Mini",
            stream_url="http://example.test/noise.m3u8",
        )
    )

    state = await Reconciler(
        settings=settings,
        state_store=store,
        cast_client=fake,
    ).reconcile_once()

    assert state.device_host == "192.168.68.13"
    assert state.device_port == 8009
    assert state.device_uuid == "abc123"
    assert state.device_model_name == "Google Nest Mini"


@pytest.mark.anyio
async def test_reconcile_off_stops_when_playing(tmp_path) -> None:
    settings = Settings(
        _env_file=None,
        state_path=tmp_path / "state.json",
        default_device_host="192.168.68.13",
    )
    store = StateStore(settings.state_path)
    fake = FakeCastClient(
        CastResult(ok=True, action="cast_sent", observed=ObservedState.PLAYING)
    )
    store.save(
        ControllerState(
            desired=DesiredState.OFF,
            observed=ObservedState.PLAYING,
            device="Bedroom Nest Mini",
        )
    )

    state = await Reconciler(
        settings=settings,
        state_store=store,
        cast_client=fake,
    ).reconcile_once()

    assert fake.stop_calls == 1
    assert state.observed == ObservedState.IDLE
    assert state.last_action == "stop_sent"


@pytest.mark.anyio
async def test_reconcile_off_stops_after_explicit_stop_request_when_unknown(
    tmp_path,
) -> None:
    settings = Settings(
        _env_file=None,
        state_path=tmp_path / "state.json",
        default_device_host="192.168.68.13",
    )
    store = StateStore(settings.state_path)
    fake = FakeCastClient(
        CastResult(ok=True, action="cast_sent", observed=ObservedState.PLAYING)
    )
    store.save(
        ControllerState(
            desired=DesiredState.OFF,
            observed=ObservedState.UNKNOWN,
            device="Bedroom Nest Mini",
            last_action="stop_requested",
        )
    )

    state = await Reconciler(
        settings=settings,
        state_store=store,
        cast_client=fake,
    ).reconcile_once()

    assert fake.stop_calls == 1
    assert state.observed == ObservedState.IDLE
