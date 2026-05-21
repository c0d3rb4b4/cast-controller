from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import Body, FastAPI, HTTPException

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
)
from reconcile import Reconciler
from state_store import StateStore


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

        target_changed = stream_url != state.stream_url or device != state.device
        state.desired = DesiredState.ON
        state.device = device
        state.device_host = state.device_host or settings.default_device_host
        state.stream_url = stream_url
        state.volume = volume
        if target_changed:
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
        state.last_action = "stop_requested"
        state_store.save(state)
        reconciler.request_now()

        return ActionResponse(ok=True, desired=state.desired, action="stop_requested")

    @app.get("/devices", response_model=DevicesResponse)
    async def devices() -> DevicesResponse:
        return DevicesResponse(ok=True, devices=await cast_client.list_devices())

    return app


app = create_app()
