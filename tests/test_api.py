from __future__ import annotations

from fastapi.testclient import TestClient

from app import create_app
from config import Settings


def make_client(tmp_path) -> TestClient:
    settings = Settings(
        _env_file=None,
        default_device_name="Bedroom Nest Mini",
        default_device_host="192.168.68.13",
        default_stream_url=None,
        noise_stream_base_url="http://192.168.68.84:8081",
        default_noise_type="white",
        state_path=tmp_path / "state.json",
    )
    app = create_app(settings=settings, start_background=False)
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
    client = make_client(tmp_path)

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
    assert status.json()["desired"] == "off"
    assert status.json()["last_action"] == "stop_requested"

