from __future__ import annotations

from cast_client import CastClient
from config import Settings


def test_content_type_for_hls_uses_cast_supported_mime_type() -> None:
    client = CastClient(Settings(_env_file=None))

    assert (
        client._content_type_for("http://example.test/hls/noise_white/stream.m3u8")
        == "application/x-mpegurl"
    )


def test_media_info_for_hls_declares_audio_ts_segments() -> None:
    client = CastClient(Settings(_env_file=None))

    assert client._media_info_for(
        "http://example.test/hls/noise_white/stream.m3u8"
    ) == {"hlsSegmentFormat": "ts_aac"}
