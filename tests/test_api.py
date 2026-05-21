from __future__ import annotations

from fastapi.testclient import TestClient

from app import create_app
from cast_client import CastResult
from config import Settings
from models import ControllerState, DesiredState, ObservedState, utc_now


class FakeCastClient:
    def __init__(self, stop_result: CastResult | None = None):
        self.stop_result = stop_result or CastResult(
            ok=True,
            action="reconcile_stop",
            observed=ObservedState.IDLE,
        )
        self.stop_calls = 0

    async def list_devices(self):
        return []

    async def stop(self, **kwargs):
        self.stop_calls += 1
        return self.stop_result


def make_client(tmp_path, cast_client: FakeCastClient | None = None) -> TestClient:
    settings = Settings(
        _env_file=None,
        default_device_name="Bedroom Nest Mini",
        default_device_host="192.168.68.13",
        default_stream_url=None,
        noise_stream_base_url="http://192.168.68.84:8081",
        default_noise_type="white",
        state_path=tmp_path / "state.json",
    )
    app = create_app(
        settings=settings,
        cast_client=cast_client or FakeCastClient(),
        start_background=False,
    )
    return TestClient(app)


def test_health_and_initial_status(tmp_path) -> None:
    client = make_client(tmp_path)

    health = client.get("/health")
    status = client.get("/status")

    assert health.status_code == 200
    assert health.json()["ok"] is True
    assert health.json()["reconcile_running"] is False
    assert status.status_code == 200
    assert status.json()["desired"] == "off"
    assert status.json()["observed"] == "unknown"


def test_control_page_is_served(tmp_path) -> None:
    client = make_client(tmp_path)

    response = client.get("/control")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert 'data-theme="dark"' in response.text
    assert "WHITE" in response.text
    assert "PINK" in response.text
    assert "BROWN" in response.text
    assert 'id="volumeSlider"' in response.text
    assert 'min="0" max="100" step="1" value="10"' in response.text
    assert "10%" in response.text
    assert "volume: selectedVolume()" in response.text
    assert 'state.observed !== "playing"' in response.text
    assert "window.setInterval(refreshStatus, 10000)" in response.text
    assert 'postJson("/stop", {})' in response.text


def test_start_is_idempotent_and_uses_defaults(tmp_path) -> None:
    client = make_client(tmp_path)

    first = client.post("/start", json={})
    second = client.post("/start", json={})
    status = client.get("/status")

    assert first.status_code == 200
    assert first.json() == {
        "ok": True,
        "desired": "on",
        "action": "cast_requested",
    }
    assert second.status_code == 200
    assert second.json() == first.json()
    assert status.json()["desired"] == "on"
    assert status.json()["device"] == "Bedroom Nest Mini"
    assert (
        status.json()["stream_url"]
        == "http://192.168.68.84:8081/hls/noise_white/stream.m3u8"
    )
    assert status.json()["volume"] == 0.25
    assert status.json()["last_action"] == "cast_requested"
    assert status.json()["failure_count"] == 0
    assert status.json()["last_cast_attempt_at"] is None


def test_start_clears_backoff_and_stale_observed_state(tmp_path) -> None:
    client = make_client(tmp_path)
    state_store = client.app.state.state_store
    state_store.save(
        ControllerState(
            desired=DesiredState.ON,
            observed=ObservedState.PLAYING,
            device="Bedroom Nest Mini",
            device_host="192.168.68.13",
            stream_url="http://192.168.68.84:8081/hls/noise_white/stream.m3u8",
            volume=0.25,
            failure_count=3,
            last_cast_attempt_at=utc_now(),
            last_action="recast_backoff",
        )
    )

    response = client.post("/start", json={})
    status = client.get("/status")

    assert response.status_code == 200
    assert status.json()["desired"] == "on"
    assert status.json()["observed"] == "unknown"
    assert status.json()["failure_count"] == 0
    assert status.json()["last_cast_attempt_at"] is None
    assert status.json()["last_action"] == "cast_requested"


def test_start_accepts_noise_type_override(tmp_path) -> None:
    client = make_client(tmp_path)

    response = client.post("/start", json={"noise_type": "brown", "volume": 0.4})
    status = client.get("/status")

    assert response.status_code == 200
    assert (
        status.json()["stream_url"]
        == "http://192.168.68.84:8081/hls/noise_brown/stream.m3u8"
    )
    assert status.json()["volume"] == 0.4


def test_stop_is_idempotent(tmp_path) -> None:
    fake = FakeCastClient()
    client = make_client(tmp_path, cast_client=fake)

    client.post("/start", json={"device": "Bedroom Nest Mini"})
    first = client.post("/stop", json={})
    second = client.post("/stop", json={})
    status = client.get("/status")

    assert first.status_code == 200
    assert first.json() == {
        "ok": True,
        "desired": "off",
        "action": "stop_requested",
    }
    assert second.status_code == 200
    assert second.json() == first.json()
    assert fake.stop_calls == 2
    assert status.json()["desired"] == "off"
    assert status.json()["observed"] == "idle"
    assert status.json()["last_action"] == "reconcile_stop"


def test_stop_attempts_cast_stop_immediately_even_when_observed_unknown(tmp_path) -> None:
    fake = FakeCastClient()
    client = make_client(tmp_path, cast_client=fake)
    state_store = client.app.state.state_store
    state_store.save(
        ControllerState(
            desired=DesiredState.ON,
            observed=ObservedState.UNKNOWN,
            device_host="192.168.68.13",
            stream_url="http://192.168.68.84:8081/hls/noise_white/stream.m3u8",
            volume=0.25,
            failure_count=3,
            last_cast_attempt_at=utc_now(),
        )
    )

    response = client.post("/stop", json={})
    status = client.get("/status")

    assert response.status_code == 200
    assert response.json() == {
        "ok": True,
        "desired": "off",
        "action": "stop_requested",
    }
    assert fake.stop_calls == 1
    assert status.json()["desired"] == "off"
    assert status.json()["observed"] == "idle"
    assert status.json()["failure_count"] == 0
    assert status.json()["last_cast_attempt_at"] is None


def test_stop_failure_preserves_retryable_stop_requested_state(tmp_path) -> None:
    fake = FakeCastClient(
        stop_result=CastResult(
            ok=False,
            action="device_unavailable",
            observed=ObservedState.UNKNOWN,
        )
    )
    client = make_client(tmp_path, cast_client=fake)

    response = client.post("/stop", json={})
    status = client.get("/status")

    assert response.status_code == 200
    assert response.json() == {
        "ok": True,
        "desired": "off",
        "action": "stop_requested",
    }
    assert fake.stop_calls == 1
    assert status.json()["desired"] == "off"
    assert status.json()["observed"] == "unknown"
    assert status.json()["failure_count"] == 1
    assert status.json()["last_action"] == "stop_requested"
