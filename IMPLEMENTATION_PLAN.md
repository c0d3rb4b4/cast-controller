# cast-controller Implementation Plan

This plan implements the REST-based Google Cast controller described in
`README.md`, deploys it with a pipeline similar to `noise-stream`, and documents
the finished service in `mediawall-documents`.

## Implementation Status

Last updated: 2026-05-21.

- [x] Phase 1: Project scaffold.
- [x] Phase 2: State and API semantics.
- [x] Phase 3: Cast device control implementation.
- [x] Phase 4: Reconcile and auto-heal loop implementation.
- [x] Phase 5: Containerization assets.
- [x] Phase 6: Automated tests and local compose validation.
- [x] Phase 7: GitHub Actions deployment workflow.
- [x] Phase 8: Home Assistant integration documented; live verification pending.
- [x] Phase 9: `mediawall-documents` deployment guide and cross links.

Verification notes:

- [x] `python -m pytest` passes locally.
- [x] `docker-compose config -q` passes locally.
- [x] `python -m compileall -q src` passes locally.
- [ ] `docker-compose build` was attempted locally, but Docker Desktop's Linux
      engine was not running or available.
- [ ] Real Cast device `/start` and `/stop` verification on the LAN is still
      pending.
- [ ] Home Assistant `rest_command` calls are documented but have not been
      executed from Home Assistant yet.
- [ ] GitHub Actions deployment has not been run from `main` yet.

## Target Behavior

- Run `cast-controller` as a Dockerized Python/FastAPI service on `192.168.68.84`.
- Expose the API on `http://192.168.68.84:8091`.
- Target the Nest Home Mini at `192.168.68.13` for Cast playback.
- Control Google Cast devices through REST endpoints:
  - `POST /start`
  - `POST /stop`
  - `GET /status`
  - `GET /health`
  - `GET /devices`
- Persist desired playback state so playback can be restored after restarts.
- Use `noise-stream` as the audio source:
  - Base URL: `http://192.168.68.84:8081`
  - White noise: `http://192.168.68.84:8081/hls/noise_white/stream.m3u8`
  - Pink noise: `http://192.168.68.84:8081/hls/noise_pink/stream.m3u8`
  - Brown noise: `http://192.168.68.84:8081/hls/noise_brown/stream.m3u8`

Important: Cast devices must be able to fetch the stream URL directly, so the
controller should use the LAN URL above instead of a Docker-only hostname such
as `noise-stream`.

Port selection note: `8090` is reserved for ntfy. A repository-wide scan found
existing service references on `8000`-`8005`, `8080`-`8082`, and `8090`; `8091`
had no project references and was not listening on `192.168.68.84` during the
check.

## Phase 1: Project Scaffold - Complete

Create the application structure:

```text
cast-controller/
  .github/workflows/deploy.yml
  config/app.env.example
  src/
    app.py
    cast_client.py
    config.py
    models.py
    reconcile.py
    state_store.py
  tests/
  docker-compose.yml
  Dockerfile
  requirements.txt
  README.md
```

Implementation tasks:

- Add FastAPI, Uvicorn, Pydantic settings, pychromecast, zeroconf, pytest, and
  HTTP test dependencies to `requirements.txt`.
- Add typed request/response models for start, stop, status, health, and device
  discovery responses.
- Load configuration from environment variables matching the README:
  - `DEFAULT_DEVICE_NAME`
  - `DEFAULT_STREAM_URL`
  - `DEFAULT_VOLUME`
  - `RECONCILE_INTERVAL_S`
  - `MIN_RECAST_INTERVAL_S`
  - `CAST_START_GRACE_S`
  - `PORT`
  - `STATE_PATH`
  - `LOG_LEVEL`
- Add optional noise-stream convenience config:
  - `NOISE_STREAM_BASE_URL=http://192.168.68.84:8081`
  - `DEFAULT_NOISE_TYPE=white`
- Add optional fixed Cast target config:
  - `DEFAULT_DEVICE_HOST=192.168.68.13`
  - `DEFAULT_DEVICE_NAME` should still be configurable because the friendly
    name may differ from the hardware model name.

Deliverable:

- A runnable FastAPI service with placeholder Cast behavior and working
  `/health` and `/status` endpoints.

## Phase 2: State and API Semantics - Complete

Implement desired-state persistence and idempotent API behavior.

Tasks:

- Use a JSON state file at `/data/state.json` by default.
- Persist:
  - desired state: `on` or `off`
  - observed state: `playing`, `paused`, `idle`, or `unknown`
  - device name
  - stream URL
  - volume
  - last action
  - failure count
  - timestamps for last cast attempt and last success
- Make `POST /start` idempotent:
  - Merge request values with configured defaults.
  - If `stream_url` is omitted, use `DEFAULT_STREAM_URL`.
  - If `DEFAULT_STREAM_URL` is omitted, build it from
    `NOISE_STREAM_BASE_URL` and `DEFAULT_NOISE_TYPE`.
  - Save desired state as `on`.
  - Request an immediate reconcile.
- Make `POST /stop` idempotent:
  - Save desired state as `off`.
  - Request an immediate reconcile.
- Return stable JSON responses matching the README examples.

Deliverable:

- API behavior can be tested without a Cast device by mocking the Cast client.

## Phase 3: Cast Device Control - Complete, Manual Verification Pending

Implement the pychromecast integration behind a small adapter.

Tasks:

- Discover devices by friendly name.
- If `DEFAULT_DEVICE_HOST=192.168.68.13` is configured, try direct connection to
  that host before falling back to full network discovery.
- Cache device UUID/IP after successful discovery.
- Connect to the Cast device before sending commands.
- Start playback with the HLS stream URL and an appropriate content type:
  - `application/vnd.apple.mpegurl` for `.m3u8`
- Apply volume if provided.
- Stop or pause playback when desired state is `off`.
- Normalize Cast player states into internal observed states.
- Treat discovery failures and `UNKNOWN` player state as recoverable.

Docker networking note:

- Use `network_mode: host` in `docker-compose.yml` on the Linux service server.
  Google Cast discovery/control depends on LAN multicast traffic, which is much
  more reliable from host networking than from a bridged Docker network.

Deliverable:

- Manual `/start` and `/stop` calls can control a real Cast target from
  `192.168.68.84`.

## Phase 4: Reconcile and Auto-Heal Loop - Complete, Long-Run Verification Pending

Implement the background loop described in the README.

Tasks:

- Start an asyncio background task during FastAPI lifespan startup.
- Run every `RECONCILE_INTERVAL_S`.
- If desired state is `on`:
  - Rediscover later if the device is unavailable.
  - Re-cast if observed state is not `playing`.
  - Respect `MIN_RECAST_INTERVAL_S`.
  - Apply exponential backoff after repeated failures.
- If desired state is `off`:
  - Stop playback if observed state is still `playing` or `paused`.
- Update persisted state after each reconcile attempt.
- Add structured logs for API requests, discovery, cast requests, stops,
  reconcile actions, failures, and backoff decisions.

Deliverable:

- Playback is restored automatically after accidental pauses, Cast disconnects,
  or service restarts.

## Phase 5: Containerization - Complete, Docker Build Pending

Add Docker assets similar to `noise-stream`.

Tasks:

- Create a Python 3.11 slim `Dockerfile`.
- Install runtime dependencies needed by health checks, at minimum `curl`.
- Copy `requirements.txt` first for build caching.
- Copy `src/` into `/app/src`.
- Set:
  - `PYTHONPATH=/app/src`
  - `PORT=8091`
  - `STATE_PATH=/data/state.json`
- Create `/data` for persistent state.
- Run Uvicorn on `0.0.0.0:8091`.
- Add a container health check for `http://localhost:8091/health`.
- Create `docker-compose.yml` with:
  - `container_name: cast-controller`
  - `network_mode: host`
  - `./config:/app/config:ro`
  - `./data:/data`
  - restart policy `unless-stopped`
  - labels matching the local logging convention:
    - `logging=promtail`
    - `service=cast-controller`
    - `environment=production`

Deliverable:

- `docker compose build` and `docker compose up -d` start a healthy local
  service.

## Phase 6: Tests and Local Verification - Automated Tests Complete

Add focused tests around the high-risk behavior.

Tasks:

- Unit test config loading and default noise URL construction.
- Unit test JSON state persistence.
- Unit test idempotent `/start` and `/stop` behavior.
- Unit test reconcile decisions with a fake Cast client:
  - desired `on` plus idle observed state triggers cast
  - desired `on` plus playing observed state does nothing
  - desired `off` plus playing observed state triggers stop
  - recast is rate-limited
  - repeated failures back off
- Add a lightweight health/status API test.

Manual verification commands:

```bash
docker compose build
docker compose up -d
curl http://localhost:8091/health
curl http://localhost:8091/status
curl -X POST http://localhost:8091/start \
  -H "Content-Type: application/json" \
  -d '{"device":"Bedroom Nest Mini","stream_url":"http://192.168.68.84:8081/hls/noise_white/stream.m3u8","volume":0.25}'
curl -X POST http://localhost:8091/stop \
  -H "Content-Type: application/json" \
  -d '{"device":"Bedroom Nest Mini"}'
```

Deliverable:

- Automated tests cover controller logic without requiring a Cast device, and a
  manual test path verifies real device behavior on the LAN.

## Phase 7: Deployment Pipeline - Workflow Complete, Deployment Run Pending

Create `.github/workflows/deploy.yml` using the same deployment pattern as
`noise-stream`.

Pipeline behavior:

- Trigger on push to `main`.
- Run on the self-hosted GitHub Actions runner.
- Checkout the repository.
- Sync files to the service server:

```bash
rsync -avz --delete \
  --exclude '.git' \
  --exclude '__pycache__' \
  --exclude '*.pyc' \
  --exclude '.pytest_cache' \
  --exclude 'config/app.env' \
  --exclude 'data' \
  ./ ${{ secrets.DEPLOY_USER }}@192.168.68.84:~/cast-controller/
```

- Ensure `~/cast-controller/config/app.env` exists:
  - Copy from `config/app.env.example` when present.
  - Otherwise create a minimal default config.
- Ensure `~/cast-controller/data` exists for persistent state.
- Validate Docker Compose config.
- Stop the existing container with `docker compose down || true`.
- Build the image.
- Start the service with `docker compose up -d`.
- Confirm the `cast-controller` container is running.
- Wait for internal health:

```bash
docker exec cast-controller curl -fsS http://localhost:8091/health
```

- Run an external health check from the runner:

```bash
curl -sf http://192.168.68.84:8091/health
```

Required GitHub secret:

- `DEPLOY_USER`: SSH username on `192.168.68.84`.

Default production config:

```env
DEFAULT_DEVICE_NAME=
DEFAULT_DEVICE_HOST=192.168.68.13
NOISE_STREAM_BASE_URL=http://192.168.68.84:8081
DEFAULT_NOISE_TYPE=white
DEFAULT_STREAM_URL=http://192.168.68.84:8081/hls/noise_white/stream.m3u8
DEFAULT_VOLUME=0.25
RECONCILE_INTERVAL_S=30
MIN_RECAST_INTERVAL_S=60
CAST_START_GRACE_S=5
PORT=8091
STATE_PATH=/data/state.json
LOG_LEVEL=info
```

Deliverable:

- Pushes to `main` deploy `cast-controller` to `192.168.68.84` in the same
  operational style as `noise-stream`.

## Phase 8: Home Assistant Integration - Documented, Live Verification Pending

Document and verify LAN calls from Home Assistant or other automations.

Example commands:

```yaml
rest_command:
  sleep_noise_start_white:
    url: "http://192.168.68.84:8091/start"
    method: POST
    content_type: "application/json"
    payload: '{"device":"Bedroom Nest Mini","stream_url":"http://192.168.68.84:8081/hls/noise_white/stream.m3u8","volume":0.25}'

  sleep_noise_start_pink:
    url: "http://192.168.68.84:8091/start"
    method: POST
    content_type: "application/json"
    payload: '{"device":"Bedroom Nest Mini","stream_url":"http://192.168.68.84:8081/hls/noise_pink/stream.m3u8","volume":0.25}'

  sleep_noise_start_brown:
    url: "http://192.168.68.84:8091/start"
    method: POST
    content_type: "application/json"
    payload: '{"device":"Bedroom Nest Mini","stream_url":"http://192.168.68.84:8081/hls/noise_brown/stream.m3u8","volume":0.25}'

  sleep_noise_stop:
    url: "http://192.168.68.84:8091/stop"
    method: POST
    content_type: "application/json"
    payload: '{"device":"Bedroom Nest Mini"}'
```

Deliverable:

- Home Assistant can start white, pink, or brown noise through
  `cast-controller` without casting from a phone.

## Phase 9: Documentation in mediawall-documents - Complete

After implementation and deployment are verified, add deployment documentation
under `mediawall-documents`.

Tasks:

- Create `mediawall-documents/installation/cast-controller-deployment.md`.
- Match the structure of
  `mediawall-documents/installation/noise-stream-deployment.md`.
- Include:
  - architecture diagram showing GitHub, self-hosted runner, service server,
    `cast-controller`, `noise-stream`, and Cast devices
  - server roles and IP addresses
  - service port: `8091`
  - noise-stream dependency and URLs
  - Docker host networking rationale for Cast discovery
  - GitHub Actions deployment flow
  - required `DEPLOY_USER` secret
  - service server setup steps
  - configuration reference
  - health/status verification commands
  - `/start` and `/stop` examples
  - Home Assistant `rest_command` examples
  - logs and troubleshooting
  - maintenance and state-file reset guidance
- Update cross references:
  - Add a link from `noise-stream-deployment.md` to the new
    cast-controller guide.
  - Add a link from any relevant installation index or overview document if one
    exists.
- Add a short README update in `cast-controller/README.md` pointing readers to
  the deployment guide once it exists.

Deliverable:

- Operators can deploy, configure, verify, and troubleshoot `cast-controller`
  using the shared documentation set.

## Acceptance Criteria

- `GET http://192.168.68.84:8091/health` returns HTTP 200 after deployment.
- `GET http://192.168.68.84:8091/status` returns persisted controller state.
- `POST /start` starts one of the noise-stream HLS URLs on the configured Cast
  device, expected to be the Nest Home Mini at `192.168.68.13`.
- `POST /start` is safe to call repeatedly.
- `POST /stop` stops playback and is safe to call repeatedly.
- Restarting the container preserves desired state from `/data/state.json`.
- If playback stops unexpectedly while desired state is `on`, the reconcile loop
  re-casts after the configured grace/rate-limit window.
- GitHub Actions deploys to `~/cast-controller` on `192.168.68.84`.
- Deployment preserves `config/app.env` and `/data`.
- `mediawall-documents` contains the final deployment guide and cross links.
