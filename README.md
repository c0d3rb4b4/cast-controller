# cast-controller

## Overview
`cast-controller` is a REST-based control service for Google Cast devices. It starts, stops, and **keeps audio playback alive** by continuously reconciling the desired playback state with the actual device state.

It is designed to be triggered by Home Assistant, Zigbee buttons, or simple REST calls, and to auto-heal if playback stops unexpectedly.

Deployment and operations are documented in the shared MediaWall guide:
[cast-controller Deployment Guide](../mediawall-documents/installation/cast-controller-deployment.md).

---

## Design goals
- No phone casting
- REST-driven control
- Auto-healing playback
- Idempotent start/stop calls
- Minimal user interaction
- Suitable for overnight use

---

## Core concepts

### Desired state
What the system *should* be doing:
- `on` → noise should be playing
- `off` → noise should be stopped

### Observed state
What the Cast device is currently doing:
- `playing`
- `paused`
- `idle`
- `unknown`

A background reconcile loop ensures observed state moves toward desired state.

---

## Endpoints

### `GET /control`
Serve a mobile-friendly control page with buttons for white, pink, and brown noise.
The page calls `/start` with the selected `noise_type` and volume slider value, and calls `/stop` when the active button is tapped again.

---

### `POST /start`
Start or ensure playback on a Cast device.

**Request**
```json
{
  "device": "Bedroom Nest Mini",
  "stream_url": "http://192.168.68.84:8081/hls/noise_white/stream.m3u8",
  "volume": 0.25
}
```

**Behavior**
- Sets desired state to `on`
- Discovers the Cast device
- Casts the stream URL
- Sets volume (if provided)
- Safe to call repeatedly

**Response**
```json
{
  "ok": true,
  "desired": "on",
  "action": "cast_requested"
}
```

---

### `POST /stop`
Stop playback.

**Request**
```json
{
  "device": "Bedroom Nest Mini"
}
```

**Behavior**
- Sets desired state to `off`
- Sends stop/pause command
- Idempotent

**Response**
```json
{
  "ok": true,
  "desired": "off",
  "action": "stop_requested"
}
```

---

### `GET /status`
Return internal controller state.

**Response**
```json
{
  "desired": "on",
  "observed": "playing",
  "device": "Bedroom Nest Mini",
  "stream_url": "http://192.168.68.84:8081/hls/noise_white/stream.m3u8",
  "volume": 0.25,
  "last_action": "reconcile_cast"
}
```

---

### `GET /health`
Service liveness endpoint.

Returns **200** if:
- API is responsive
- Reconcile loop is running

Device discovery failure should not fail health unless fatal.

---

### `GET /devices` (optional)
List discovered Cast devices.

---

## Reconcile / auto-heal loop

Runs every `RECONCILE_INTERVAL_S` (default 30s).

Logic:
- If desired = `on`
  - If device unavailable → retry discovery later
  - If not playing → re-cast stream URL
- If desired = `off`
  - If playing → stop playback

Safeguards:
- Minimum time between re-casts
- Exponential backoff on repeated failures

---

## Persistence
Desired state should survive restarts.

Persist:
- Desired state
- Device name
- Stream URL
- Volume
- Failure counters
- Timestamps

Recommended options:
- SQLite
- JSON file on a mounted volume

---

## Configuration

Environment variables:

| Variable | Description | Default |
|--------|-------------|---------|
| `DEFAULT_DEVICE_NAME` | Cast device name | none |
| `DEFAULT_DEVICE_HOST` | Optional fixed Cast device IP/host | `192.168.68.13` |
| `DEFAULT_STREAM_URL` | Stream URL | none |
| `NOISE_STREAM_BASE_URL` | Base URL used to build default noise stream URLs | `http://192.168.68.84:8081` |
| `DEFAULT_NOISE_TYPE` | Noise stream type when constructing default stream URL | `white` |
| `DEFAULT_VOLUME` | Playback volume | `0.25` |
| `RECONCILE_INTERVAL_S` | Reconcile interval | `30` |
| `MIN_RECAST_INTERVAL_S` | Re-cast rate limit | `60` |
| `CAST_START_GRACE_S` | Grace before recheck | `5` |
| `PORT` | HTTP port | `8091` |
| `STATE_PATH` | Persistent state file | `/data/state.json` |
| `LOG_LEVEL` | Logging level | `info` |

---

## Implementation guidance

### Language and libraries
Recommended:
- Python
- FastAPI
- pychromecast
- asyncio background task

### Cast control notes
- Cache device IP/UUID after discovery
- Always wait for Cast connection before issuing commands
- Treat UNKNOWN state as recoverable

### Logging
Log:
- Start/stop requests
- Discovery events
- Reconcile actions
- Re-cast attempts
- Errors

Structured JSON logs are recommended.

---

## Home Assistant usage
Home Assistant should call this service, not control the Cast device directly.

Example HA `rest_command`:
```yaml
rest_command:
  sleep_noise_start_white:
    url: "http://192.168.68.84:8091/start"
    method: POST
    content_type: "application/json"
    payload: '{"device":"Bedroom Nest Mini","stream_url":"http://192.168.68.84:8081/hls/noise_white/stream.m3u8","volume":0.25}'
```

Zigbee button mapping:
- Single press → `/start`
- Long press → `/stop`

---

## Security
- Keep LAN-only
- Add shared-secret header if exposed
- No authentication by default

---
