from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

from config import Settings
from models import DeviceInfo, ObservedState

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CastResult:
    ok: bool
    action: str
    observed: ObservedState = ObservedState.UNKNOWN
    message: str | None = None
    device: DeviceInfo | None = None


class CastClient:
    """Small async adapter around pychromecast's blocking API."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self._cached_devices: dict[str, DeviceInfo] = {}

    async def list_devices(self) -> list[DeviceInfo]:
        return await asyncio.to_thread(self._list_devices_sync)

    async def cast_stream(
        self,
        *,
        device: str | None,
        device_host: str | None,
        stream_url: str,
        volume: float | None,
    ) -> CastResult:
        return await asyncio.to_thread(
            self._cast_stream_sync,
            device=device,
            device_host=device_host,
            stream_url=stream_url,
            volume=volume,
        )

    async def stop(
        self,
        *,
        device: str | None,
        device_host: str | None,
    ) -> CastResult:
        return await asyncio.to_thread(
            self._stop_sync,
            device=device,
            device_host=device_host,
        )

    def _cast_stream_sync(
        self,
        *,
        device: str | None,
        device_host: str | None,
        stream_url: str,
        volume: float | None,
    ) -> CastResult:
        cast, browser = self._find_cast(device=device, device_host=device_host)
        if cast is None:
            return CastResult(
                ok=False,
                action="device_unavailable",
                observed=ObservedState.UNKNOWN,
                message="Cast device was not found",
            )

        try:
            cast.wait(timeout=self.settings.cast_start_grace_s)
            if volume is not None:
                cast.set_volume(volume)

            content_type = self._content_type_for(stream_url)
            cast.media_controller.play_media(
                stream_url,
                content_type,
                title="Mediawall Noise Stream",
                autoplay=True,
                stream_type="LIVE",
            )
            cast.media_controller.block_until_active(
                timeout=self.settings.cast_start_grace_s
            )
            observed = self._wait_for_player_state(cast.media_controller)
            device_info = self._device_info_from_cast(cast)
            self._cache_device(device_info)
            logger.info(
                "cast_stream_sent device=%s host=%s stream_url=%s observed=%s",
                device_info.name,
                device_info.host,
                stream_url,
                observed.value,
            )
            return CastResult(
                ok=True,
                action="reconcile_cast",
                observed=observed,
                device=device_info,
            )
        except Exception as exc:
            logger.exception("cast_stream_failed")
            return CastResult(
                ok=False,
                action="cast_failed",
                observed=ObservedState.UNKNOWN,
                message=str(exc),
            )
        finally:
            self._stop_browser(browser)
            self._disconnect_cast(cast)

    def _stop_sync(self, *, device: str | None, device_host: str | None) -> CastResult:
        cast, browser = self._find_cast(device=device, device_host=device_host)
        if cast is None:
            return CastResult(
                ok=False,
                action="device_unavailable",
                observed=ObservedState.UNKNOWN,
                message="Cast device was not found",
            )

        try:
            cast.wait(timeout=self.settings.cast_start_grace_s)
            media_controller = cast.media_controller
            try:
                media_controller.update_status()
                media_controller.block_until_active(
                    timeout=self.settings.cast_start_grace_s
                )
            except Exception:
                logger.debug("cast_stop_status_update_failed", exc_info=True)

            media_controller.stop()
            cast.quit_app()
            observed = ObservedState.IDLE
            device_info = self._device_info_from_cast(cast)
            self._cache_device(device_info)
            logger.info(
                "cast_stop_sent device=%s host=%s observed=%s",
                device_info.name,
                device_info.host,
                observed.value,
            )
            return CastResult(
                ok=True,
                action="reconcile_stop",
                observed=observed,
                device=device_info,
            )
        except Exception as exc:
            logger.exception("cast_stop_failed")
            return CastResult(
                ok=False,
                action="stop_failed",
                observed=ObservedState.UNKNOWN,
                message=str(exc),
            )
        finally:
            self._stop_browser(browser)
            self._disconnect_cast(cast)

    def _list_devices_sync(self) -> list[DeviceInfo]:
        import pychromecast

        browser = None
        try:
            casts, browser = pychromecast.get_chromecasts(
                tries=1,
                timeout=self.settings.cast_start_grace_s,
                known_hosts=self._known_hosts(),
            )
            devices = [self._device_info_from_cast(cast) for cast in casts]
            for device in devices:
                self._cache_device(device)
            logger.info("cast_devices_discovered count=%s", len(devices))
            return devices
        except Exception:
            logger.exception("cast_device_discovery_failed")
            return []
        finally:
            self._stop_browser(browser)
            for cast in locals().get("casts", []):
                self._disconnect_cast(cast)

    def _find_cast(
        self,
        *,
        device: str | None,
        device_host: str | None,
    ) -> tuple[Any | None, Any | None]:
        import pychromecast

        target_host = device_host or self._cached_host_for(device)
        if target_host:
            try:
                cast = pychromecast.get_chromecast_from_host(
                    (
                        target_host,
                        8009,
                        self._cached_uuid_for(device),
                        None,
                        device,
                    ),
                    tries=1,
                    timeout=self.settings.cast_start_grace_s,
                )
                logger.info("cast_direct_connection_succeeded host=%s", target_host)
                return cast, None
            except Exception:
                logger.exception("cast_direct_connection_failed host=%s", target_host)

        if not device:
            return None, None

        browser = None
        try:
            casts, browser = pychromecast.get_listed_chromecasts(
                friendly_names=[device],
                tries=1,
                timeout=self.settings.cast_start_grace_s,
                discovery_timeout=self.settings.cast_start_grace_s,
                known_hosts=self._known_hosts(),
            )
            if not casts:
                logger.warning("cast_discovery_no_match device=%s", device)
                return None, browser

            cast = casts[0]
            logger.info("cast_discovery_match device=%s uri=%s", device, cast.uri)
            return cast, browser
        except Exception:
            logger.exception("cast_discovery_failed device=%s", device)
            self._stop_browser(browser)
            return None, None

    def _cache_device(self, device: DeviceInfo) -> None:
        for key in {device.name, device.host, device.uuid}:
            if key:
                self._cached_devices[key] = device

    def _cached_host_for(self, device: str | None) -> str | None:
        if not device:
            return None
        cached = self._cached_devices.get(device)
        return cached.host if cached else None

    def _cached_uuid_for(self, device: str | None) -> str | None:
        if not device:
            return None
        cached = self._cached_devices.get(device)
        return cached.uuid if cached else None

    def _known_hosts(self) -> list[str]:
        hosts = []
        if self.settings.default_device_host:
            hosts.append(self.settings.default_device_host)
        hosts.extend(
            device.host
            for device in self._cached_devices.values()
            if device.host is not None
        )
        return sorted(set(hosts))

    def _device_info_from_cast(self, cast: Any) -> DeviceInfo:
        host, port = self._split_uri(getattr(cast, "uri", None))
        uuid = getattr(cast, "uuid", None)
        return DeviceInfo(
            name=getattr(cast, "name", None),
            host=host,
            port=port,
            uuid=str(uuid) if uuid is not None else None,
            model_name=getattr(cast, "model_name", None),
        )

    def _split_uri(self, uri: str | None) -> tuple[str | None, int | None]:
        if not uri:
            return None, None

        if "://" not in uri:
            uri = f"cast://{uri}"

        parsed = urlparse(uri)
        return parsed.hostname, parsed.port

    def _content_type_for(self, stream_url: str) -> str:
        path = urlparse(stream_url).path.lower()
        if path.endswith(".m3u8"):
            return "application/x-mpegurl"
        if path.endswith(".mp3"):
            return "audio/mpeg"
        return "audio/mpeg"

    def _normalize_player_state(self, player_state: str | None) -> ObservedState:
        match player_state:
            case "PLAYING" | "BUFFERING":
                return ObservedState.PLAYING
            case "PAUSED":
                return ObservedState.PAUSED
            case "IDLE":
                return ObservedState.IDLE
            case _:
                return ObservedState.UNKNOWN

    def _wait_for_player_state(self, media_controller: Any) -> ObservedState:
        deadline = time.monotonic() + self.settings.cast_start_grace_s
        observed = ObservedState.UNKNOWN

        while True:
            media_controller.update_status()
            observed = self._normalize_player_state(
                getattr(media_controller.status, "player_state", None)
            )
            if observed == ObservedState.PLAYING or time.monotonic() >= deadline:
                return observed

            time.sleep(0.25)

    def _stop_browser(self, browser: Any | None) -> None:
        if browser is None:
            return
        try:
            browser.stop_discovery()
        except Exception:
            logger.debug("cast_browser_stop_failed", exc_info=True)

    def _disconnect_cast(self, cast: Any | None) -> None:
        if cast is None:
            return
        try:
            cast.disconnect(timeout=1, blocking=True)
        except Exception:
            logger.debug("cast_disconnect_failed", exc_info=True)
