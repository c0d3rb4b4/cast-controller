from __future__ import annotations

from models import ControllerState, DesiredState, ObservedState
from state_store import StateStore


def test_state_store_persists_json_state(tmp_path) -> None:
    store = StateStore(tmp_path / "state.json")
    state = ControllerState(
        desired=DesiredState.ON,
        observed=ObservedState.PAUSED,
        device="Bedroom Nest Mini",
        stream_url="http://example.test/noise.m3u8",
        volume=0.25,
        last_action="cast_requested",
        failure_count=2,
    )

    store.save(state)
    loaded = store.load()

    assert loaded.desired == DesiredState.ON
    assert loaded.observed == ObservedState.PAUSED
    assert loaded.device == "Bedroom Nest Mini"
    assert loaded.stream_url == "http://example.test/noise.m3u8"
    assert loaded.volume == 0.25
    assert loaded.last_action == "cast_requested"
    assert loaded.failure_count == 2

