from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import Body, FastAPI, HTTPException
from fastapi.responses import HTMLResponse

from cast_client import CastClient
from config import Settings, get_settings
from models import (
    ActionResponse,
    ControllerState,
    DesiredState,
    DevicesResponse,
    HealthResponse,
    StartRequest,
    StopRequest,
    ObservedState,
    VolumeRequest,
    VolumeResponse,
    utc_now,
)
from reconcile import Reconciler
from state_store import StateStore


CONTROL_PAGE_HTML = """<!doctype html>
<html lang="en" data-theme="dark">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Cast Control</title>
  <style>
    :root {
      color-scheme: dark;
      --bg: #0d0f10;
      --fg: #e7e5e4;
      --muted: #8c8f94;
      --border: rgba(255, 255, 255, 0.16);
      --active: #139447;
      --active-pressed: #0f7839;
      --toggle-bg: #2b2f34;
      --toggle-knob: #f2f2ef;
      font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont,
        "Segoe UI", sans-serif;
    }

    html[data-theme="light"] {
      color-scheme: light;
      --bg: #f5f5f2;
      --fg: #16181a;
      --muted: #777a80;
      --border: rgba(22, 24, 26, 0.18);
      --active: #22a957;
      --active-pressed: #198844;
      --toggle-bg: #d7d9dc;
      --toggle-knob: #151719;
    }

    * {
      box-sizing: border-box;
    }

    body {
      min-height: 100dvh;
      margin: 0;
      background: var(--bg);
      color: var(--fg);
      overflow: hidden;
    }

    .top-controls {
      position: fixed;
      top: max(16px, env(safe-area-inset-top));
      right: max(14px, env(safe-area-inset-right));
      left: max(14px, env(safe-area-inset-left));
      z-index: 2;
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 14px;
    }

    .volume-panel {
      display: flex;
      flex: 1 1 auto;
      flex-direction: column;
      gap: 7px;
      min-width: 0;
      max-width: 560px;
    }

    .volume-control {
      display: flex;
      align-items: center;
      gap: 10px;
      min-width: 0;
      color: var(--muted);
      font-size: 1rem;
      font-weight: 700;
      line-height: 1;
    }

    .volume-slider {
      flex: 1 1 auto;
      min-width: 0;
      height: 30px;
      accent-color: var(--active);
      cursor: pointer;
    }

    .volume-value {
      width: 4ch;
      text-align: right;
      color: var(--muted);
    }

    .volume-steps {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 8px;
      width: min(180px, 100%);
    }

    .volume-step {
      min-height: 32px;
      border: 1px solid var(--border);
      border-radius: 8px;
      background: var(--bg);
      color: var(--muted);
      font-size: 1.25rem;
      font-weight: 800;
      line-height: 1;
      appearance: none;
      cursor: pointer;
      touch-action: manipulation;
    }

    .volume-step:active {
      background: var(--active);
      color: var(--fg);
    }

    .theme-toggle {
      flex: 0 0 auto;
      width: 54px;
      height: 30px;
      border: 1px solid var(--border);
      border-radius: 999px;
      background: var(--toggle-bg);
      padding: 3px;
      appearance: none;
      cursor: pointer;
      touch-action: manipulation;
    }

    .theme-toggle span {
      display: block;
      width: 22px;
      height: 22px;
      border-radius: 50%;
      background: var(--toggle-knob);
      transform: translateX(0);
      transition: transform 150ms ease;
    }

    html[data-theme="light"] .theme-toggle span {
      transform: translateX(24px);
    }

    .controls {
      display: flex;
      flex-direction: column;
      gap: 14px;
      min-height: 100dvh;
      padding: max(120px, calc(env(safe-area-inset-top) + 114px))
        max(14px, env(safe-area-inset-right))
        max(14px, env(safe-area-inset-bottom))
        max(14px, env(safe-area-inset-left));
    }

    .noise-button {
      flex: 1 1 0;
      min-height: 128px;
      border: 1px solid var(--border);
      border-radius: 8px;
      background: var(--bg);
      color: var(--muted);
      font-size: clamp(3.25rem, 13vw, 8rem);
      font-weight: 900;
      line-height: 1;
      letter-spacing: 0;
      appearance: none;
      cursor: pointer;
      touch-action: manipulation;
      transition:
        background 120ms ease,
        border-color 120ms ease,
        color 120ms ease,
        transform 80ms ease;
    }

    .noise-button:active {
      transform: scale(0.99);
    }

    .noise-button.active {
      background: var(--active);
      border-color: transparent;
    }

    .noise-button.active:active {
      background: var(--active-pressed);
    }

    .noise-button.active[data-noise="white"] {
      color: #ffffff;
    }

    .noise-button.active[data-noise="pink"] {
      color: #ff8ab8;
    }

    .noise-button.active[data-noise="brown"] {
      color: #5a3219;
    }

    .noise-button:disabled {
      cursor: progress;
    }

    .noise-button.error {
      border-color: #f04438;
    }

    @media (prefers-reduced-motion: reduce) {
      .theme-toggle span,
      .noise-button {
        transition: none;
      }
    }
  </style>
</head>
<body>
  <div class="top-controls">
    <div class="volume-panel">
      <label class="volume-control" for="volumeSlider">
        <input class="volume-slider" id="volumeSlider" type="range" min="0" max="100" step="1" value="10">
        <output class="volume-value" id="volumeValue" for="volumeSlider">10%</output>
      </label>
      <div class="volume-steps" aria-label="Volume steps">
        <button class="volume-step" id="volumeDown" type="button" aria-label="Decrease volume">-</button>
        <button class="volume-step" id="volumeUp" type="button" aria-label="Increase volume">+</button>
      </div>
    </div>
    <button class="theme-toggle" id="themeToggle" type="button" aria-label="Toggle light and dark mode">
      <span></span>
    </button>
  </div>
  <main class="controls" aria-label="Cast stream controls">
    <button class="noise-button" type="button" data-noise="white">WHITE</button>
    <button class="noise-button" type="button" data-noise="pink">PINK</button>
    <button class="noise-button" type="button" data-noise="brown">BROWN</button>
  </main>
  <script>
    const root = document.documentElement;
    const themeToggle = document.getElementById("themeToggle");
    const volumeSlider = document.getElementById("volumeSlider");
    const volumeValue = document.getElementById("volumeValue");
    const volumeDown = document.getElementById("volumeDown");
    const volumeUp = document.getElementById("volumeUp");
    const buttons = [...document.querySelectorAll(".noise-button")];
    const defaultVolumePercent = 10;
    const volumeStep = 3;
    let activeNoise = null;
    let pending = false;
    let volumeEditing = false;

    const savedTheme = localStorage.getItem("cast-control-theme");
    root.dataset.theme = savedTheme === "light" ? "light" : "dark";

    function setActive(noise) {
      activeNoise = noise;
      buttons.forEach((button) => {
        button.classList.toggle("active", button.dataset.noise === noise);
        button.classList.remove("error");
        button.setAttribute(
          "aria-pressed",
          button.dataset.noise === noise ? "true" : "false"
        );
      });
    }

    function setPending(value) {
      pending = value;
      buttons.forEach((button) => {
        button.disabled = value;
      });
    }

    function updateVolumeLabel() {
      volumeValue.textContent = `${volumeSlider.value}%`;
    }

    function setVolumePercent(percent) {
      volumeSlider.value = String(Math.max(0, Math.min(100, percent)));
      updateVolumeLabel();
    }

    function selectedVolume() {
      return Number((Number(volumeSlider.value) / 100).toFixed(2));
    }

    function volumePercentFromStatus(state) {
      if (!state || state.volume === null || state.volume === undefined) {
        return defaultVolumePercent;
      }

      const volume = Number(state.volume);
      if (!Number.isFinite(volume)) {
        return defaultVolumePercent;
      }

      return Math.round(volume * 100);
    }

    function inferNoiseType(state) {
      if (
        !state ||
        state.desired !== "on" ||
        state.observed !== "playing" ||
        !state.stream_url
      ) {
        return null;
      }

      const streamUrl = String(state.stream_url).toLowerCase();
      return ["white", "pink", "brown"].find((noise) =>
        streamUrl.includes(`noise_${noise}`)
      ) || null;
    }

    async function postJson(path, body) {
      const response = await fetch(path, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });

      if (!response.ok) {
        throw new Error(`${path} failed with ${response.status}`);
      }

      return response.json();
    }

    async function refreshStatus() {
      try {
        const response = await fetch("/status", { cache: "no-store" });
        if (!response.ok) {
          return;
        }

        const state = await response.json();
        setActive(inferNoiseType(state));
        if (!volumeEditing) {
          setVolumePercent(volumePercentFromStatus(state));
        }
      } catch (error) {
        console.error(error);
      }
    }

    async function commitVolume() {
      const result = await postJson("/volume", { volume: selectedVolume() });
      if (!result.ok) {
        throw new Error(result.action);
      }
      setVolumePercent(result.percent);
    }

    async function stepVolume(direction) {
      setVolumePercent(Number(volumeSlider.value) + direction * volumeStep);
      try {
        await commitVolume();
      } catch (error) {
        console.error(error);
      }
    }

    async function handleNoiseTap(button) {
      if (pending) {
        return;
      }

      const noise = button.dataset.noise;
      setPending(true);

      try {
        if (activeNoise === noise) {
          await postJson("/stop", {});
          setActive(null);
        } else {
          await postJson("/start", { noise_type: noise, volume: selectedVolume() });
          setActive(noise);
          window.setTimeout(refreshStatus, 7000);
        }
      } catch (error) {
        console.error(error);
        button.classList.add("error");
      } finally {
        setPending(false);
      }
    }

    themeToggle.addEventListener("click", () => {
      const nextTheme = root.dataset.theme === "dark" ? "light" : "dark";
      root.dataset.theme = nextTheme;
      localStorage.setItem("cast-control-theme", nextTheme);
    });

    volumeSlider.addEventListener("input", () => {
      volumeEditing = true;
      updateVolumeLabel();
    });
    volumeSlider.addEventListener("change", async () => {
      try {
        await commitVolume();
      } catch (error) {
        console.error(error);
      } finally {
        volumeEditing = false;
        refreshStatus();
      }
    });
    volumeSlider.addEventListener("blur", () => {
      volumeEditing = false;
    });
    volumeDown.addEventListener("click", () => stepVolume(-1));
    volumeUp.addEventListener("click", () => stepVolume(1));

    buttons.forEach((button) => {
      button.setAttribute("aria-pressed", "false");
      button.addEventListener("click", () => handleNoiseTap(button));
    });

    updateVolumeLabel();
    refreshStatus();
    window.setInterval(refreshStatus, 10000);
  </script>
</body>
</html>
"""


def create_app(
    *,
    settings: Settings | None = None,
    state_store: StateStore | None = None,
    cast_client: CastClient | None = None,
    start_background: bool = True,
) -> FastAPI:
    settings = settings or get_settings()
    logging.basicConfig(
        level=settings.log_level.upper(),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    state_store = state_store or StateStore(settings.state_path)
    cast_client = cast_client or CastClient(settings)
    reconciler = Reconciler(
        settings=settings,
        state_store=state_store,
        cast_client=cast_client,
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if start_background:
            await reconciler.start()
        try:
            yield
        finally:
            await reconciler.stop()

    app = FastAPI(title="cast-controller", lifespan=lifespan)
    app.state.settings = settings
    app.state.state_store = state_store
    app.state.cast_client = cast_client
    app.state.reconciler = reconciler

    def apply_device_info(state: ControllerState, device_info) -> None:
        if device_info is None:
            return

        state.device = device_info.name or state.device
        state.device_host = device_info.host or state.device_host
        state.device_port = device_info.port or state.device_port
        state.device_uuid = device_info.uuid or state.device_uuid
        state.device_model_name = device_info.model_name or state.device_model_name

    def volume_percent(volume: float) -> int:
        return int(round(volume * 100))

    def volume_response(
        *,
        ok: bool,
        volume: float,
        action: str,
        applied: bool = False,
    ) -> VolumeResponse:
        return VolumeResponse(
            ok=ok,
            volume=volume,
            percent=volume_percent(volume),
            action=action,
            applied=applied,
        )

    @app.get("/health", response_model=HealthResponse)
    async def health() -> HealthResponse:
        state = state_store.load()
        return HealthResponse(
            ok=True,
            status="ok",
            reconcile_running=reconciler.running,
            desired=state.desired,
            observed=state.observed,
        )

    @app.get("/status", response_model=ControllerState)
    async def status() -> ControllerState:
        return state_store.load()

    @app.get("/control", response_class=HTMLResponse)
    async def control() -> HTMLResponse:
        return HTMLResponse(CONTROL_PAGE_HTML)

    @app.get("/volume", response_model=VolumeResponse)
    async def get_volume() -> VolumeResponse:
        state = state_store.load()
        volume = state.volume if state.volume is not None else settings.default_volume
        return volume_response(
            ok=True,
            volume=volume,
            action="volume_status",
        )

    @app.post("/volume", response_model=VolumeResponse)
    async def set_volume(
        request: VolumeRequest,
    ) -> VolumeResponse:
        state = state_store.load()
        state.volume = request.volume
        state.device = request.device or settings.default_device_name or state.device
        state.device_host = state.device_host or settings.default_device_host
        state.last_action = "volume_saved"
        state_store.save(state)

        should_apply = state.desired == DesiredState.ON or state.observed in {
            ObservedState.PLAYING,
            ObservedState.PAUSED,
        }
        if not should_apply:
            return volume_response(
                ok=True,
                volume=state.volume,
                action=state.last_action,
            )

        result = await cast_client.set_volume(
            device=state.device,
            device_host=state.device_host or settings.default_device_host,
            volume=state.volume,
        )
        apply_device_info(state, result.device)
        state.last_action = result.action
        if result.ok:
            state.last_success_at = utc_now()
        state_store.save(state)

        return volume_response(
            ok=result.ok,
            volume=state.volume,
            action=state.last_action,
            applied=result.ok,
        )

    @app.post("/start", response_model=ActionResponse)
    async def start(
        request: StartRequest | None = Body(default=None),
    ) -> ActionResponse:
        request = request or StartRequest()
        state = state_store.load()

        device = request.device or settings.default_device_name or state.device
        stream_url = (
            request.stream_url
            or settings.stream_url_for(
                request.noise_type.value if request.noise_type is not None else None
            )
            or state.stream_url
        )
        volume = request.volume if request.volume is not None else settings.default_volume

        if not stream_url:
            raise HTTPException(
                status_code=400,
                detail="stream_url is required when DEFAULT_STREAM_URL and NOISE_STREAM_BASE_URL are unset",
            )

        if not device and not settings.default_device_host:
            raise HTTPException(
                status_code=400,
                detail="device is required when DEFAULT_DEVICE_NAME and DEFAULT_DEVICE_HOST are unset",
            )

        state.desired = DesiredState.ON
        state.observed = ObservedState.UNKNOWN
        state.device = device
        state.device_host = state.device_host or settings.default_device_host
        state.stream_url = stream_url
        state.volume = volume
        state.failure_count = 0
        state.last_cast_attempt_at = None
        state.last_action = "cast_requested"
        state_store.save(state)
        reconciler.request_now()

        return ActionResponse(ok=True, desired=state.desired, action="cast_requested")

    @app.post("/stop", response_model=ActionResponse)
    async def stop(
        request: StopRequest | None = Body(default=None),
    ) -> ActionResponse:
        request = request or StopRequest()
        state = state_store.load()

        state.desired = DesiredState.OFF
        state.device = request.device or settings.default_device_name or state.device
        state.device_host = state.device_host or settings.default_device_host
        state.failure_count = 0
        state.last_cast_attempt_at = None
        state.last_action = "stop_requested"
        state_store.save(state)

        result = await cast_client.stop(
            device=state.device,
            device_host=state.device_host or settings.default_device_host,
        )
        apply_device_info(state, result.device)
        if result.ok:
            state.observed = result.observed
            state.last_action = result.action
            state.failure_count = 0
            state.last_success_at = utc_now()
        else:
            state.observed = ObservedState.UNKNOWN
            state.failure_count += 1
        reconciler.request_now()
        state_store.save(state)

        return ActionResponse(ok=True, desired=state.desired, action="stop_requested")

    @app.get("/devices", response_model=DevicesResponse)
    async def devices() -> DevicesResponse:
        return DevicesResponse(ok=True, devices=await cast_client.list_devices())

    return app


app = create_app()
