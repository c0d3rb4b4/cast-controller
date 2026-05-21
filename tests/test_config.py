from __future__ import annotations

from config import Settings


def test_builds_default_noise_stream_url() -> None:
    settings = Settings(
        _env_file=None,
        default_stream_url=None,
        noise_stream_base_url="http://mediawall.local:8081/",
        default_noise_type="pink",
    )

    assert (
        settings.stream_url_for()
        == "http://mediawall.local:8081/hls/noise_pink/stream.m3u8"
    )


def test_explicit_default_stream_url_wins_without_noise_override() -> None:
    settings = Settings(
        _env_file=None,
        default_stream_url="http://example.test/custom.m3u8",
        noise_stream_base_url="http://mediawall.local:8081",
    )

    assert settings.stream_url_for() == "http://example.test/custom.m3u8"
    assert (
        settings.stream_url_for("brown")
        == "http://mediawall.local:8081/hls/noise_brown/stream.m3u8"
    )

