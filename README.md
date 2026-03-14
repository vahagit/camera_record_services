# Camera Record Services

A Home Assistant custom integration that provides an alternative camera recording service alongside the built-in `camera.record`. This is not a replacement — both can coexist and be used together in the same HA instance.

## Why does this exist?

Home Assistant's built-in `camera.record` is a clean, well-integrated service, but it is intentionally limited in what it exposes to automations. This integration is a more direct, "hacked" wrapper around the same underlying HA stream component that `camera.record` uses — accessing it at a lower level to expose additional control that the official service deliberately does not offer.

## Features

- `camera_start_recording` — a more configurable alternative to `camera.record`
- `camera_stop_recording` — stop a recording in progress, whether started by this integration or by the built-in `camera.record`

## Requirements

- Home Assistant 2024.1.1 or newer
- Camera entity that supports streaming

## Installation

### HACS (recommended)

1. Open HACS in your Home Assistant instance
2. Click the three-dot menu → **Custom repositories**
3. Add `https://github.com/vahagit/camera_record_services` as an **Integration**
4. Click **Camera Record Services** in the HACS integration list and install
5. Restart Home Assistant
6. Go to **Settings → Integrations → Add Integration** and search for **Camera Record Services**

### Manual

1. Download the latest release from [GitHub](https://github.com/vahagit/camera_record_services/releases)
2. Copy the `camera_record_services` folder into your `<config>/custom_components/` directory
3. Restart Home Assistant
4. Go to **Settings → Integrations → Add Integration** and search for **Camera Record Services**

## Services

### `camera_record_services.camera_start_recording`

A more configurable version of the built-in `camera.record`. Records a camera stream to a file, with additional options to stop the recording based on an entity state change, and to extend a recording that is already in progress rather than dropping the new request.

| Parameter | Required | Default | Description |
|---|---|---|---|
| `entity_id` | yes | — | Camera entity to record, e.g. `camera.front_door` |
| `filename` | yes | — | Full path for the output file, e.g. `/media/clips/front.mp4` |
| `duration` | no | `30` | Maximum recording length in seconds |
| `lookback` | no | `0` | Seconds of stream buffer to prepend — only available if the camera stream is already running before the recording starts |
| `stop_state_id` | no | — | Entity to watch — recording stops early if this entity reaches `stop_state_value`. Must be used together with `stop_state_value`. See Notes. |
| `stop_state_value` | no | — | The state value that triggers early stop, e.g. `"off"`. Must be used together with `stop_state_id`. See Notes. |
| `extend_running_task` | no | `true` | If the camera is already recording, extend the running recording rather than ignoring the new request. The new request's parameters are ignored — only the timer is reset. See Notes. |

`stop_state_id` and `stop_state_value` must always be provided together or not at all.

**Example:**
```yaml
service: camera_record_services.camera_start_recording
data:
  entity_id: camera.front_door
  filename: /media/clips/front_door.mp4
  duration: 60
  lookback: 2
  stop_state_id: binary_sensor.motion_front
  stop_state_value: "off"
  extend_running_task: true
```

In this example, HA will start recording `camera.front_door` to `/media/clips/front_door.mp4` for up to 60 seconds, prepending the last 2 seconds of the existing stream buffer at the start of the clip. At the same time, it will watch `binary_sensor.motion_front` — if that sensor reaches the state `"off"` before the 60 seconds are up, the recording will stop immediately at that point. Whichever happens first — the duration expiring or the sensor reaching `"off"` — ends the recording. If this service is called again for the same camera while it is already recording, the running recording will be extended (its timer reset) rather than the new request being dropped, because `extend_running_task` is `true`.

---

### `camera_record_services.camera_stop_recording`

Stop an in-progress recording immediately. This works whether the recording was started by this integration or by the built-in `camera.record` service — both use the same underlying stream component.

| Parameter | Required | Description |
|---|---|---|
| `entity_id` | yes | Camera entity whose recording should be stopped |

Best-effort — silently does nothing if no stream exists or no recording is in progress.

**Example:**
```yaml
service: camera_record_services.camera_stop_recording
data:
  entity_id: camera.front_door
```

## Notes

### `filename`

A plain string — not a template. If you need a dynamic filename (e.g. with a timestamp), generate the filename using a Home Assistant template in your automation and pass the result as a string to this service.

### `lookback`

Lookback only works if the camera's stream is already running before the recording starts — for example because the camera's stream is kept alive (`preload_stream: true`) or because something else (e.g. an HLS viewer or another automation) has already started it. If the stream is not already running, lookback will silently record 0 seconds of pre-buffer even if you request more.

### `stop_state_id` and `stop_state_value`

These two parameters work together to give you a way to stop a recording early based on what is happening in your home, rather than always waiting for the full duration to expire.

When provided, the integration races two things against each other: the recording duration timer, and a watcher that monitors the specified entity. Whichever finishes first stops the recording. For example, if you set `duration: 120` and `stop_state_id: binary_sensor.motion_front` with `stop_state_value: "off"`, the recording will run for up to 2 minutes — but if the motion sensor goes `off` before that, the recording stops at that moment instead.

Only a single entity and a single state value are supported. If your use case requires stopping based on multiple conditions — for example, only stopping when two sensors are both inactive — you will need to create a Helper (template sensor or input boolean) in Home Assistant that combines those conditions into a single entity, and point `stop_state_id` at that helper instead.

### `extend_running_task`

This parameter controls what happens when `camera_start_recording` is called for a camera that is already recording.

By default (`extend_running_task: true`), the running recording is extended — its internal countdown timer is reset back to its original duration from the point of the new call. The recording continues uninterrupted into the same file. The new request's parameters — `filename`, `duration`, `lookback`, `stop_state_id`, `stop_state_value` — are all completely ignored. Only the timer is affected.

If set to `false`, the new request is silently ignored and the running recording continues unchanged.

This is important to understand clearly: **the new request does not start a new recording and does not change the output file**. It only prevents the current recording from timing out. This is useful in scenarios where multiple automations may trigger recording for the same camera in quick succession — for example, a motion sensor that fires repeatedly — and you want the recording to keep going for as long as activity continues, rather than stopping and restarting.

Because the default is `true`, if you call this service multiple times for the same camera without thinking about it, you will be silently extending the running recording each time. If you want a second call to be truly ignored without any effect, set `extend_running_task: false`.

> **Note:** This feature relies on internal HA stream component details that are not part of the official public API. It has been tested against HA 2024.1.1 and later. A future HA update could change the underlying stream internals in a way that breaks this specific feature. If that happens, the integration will log a clear error message explaining that the internal API has changed and that an update is needed.

## License

MIT — see [LICENSE](LICENSE)
