# Camera Record Services

A Home Assistant custom integration that provides an alternative camera recording service alongside the built-in `camera.record`. This is not a replacement - both can coexist and be used together in the same HA instance.

## Why does this exist?

Home Assistant's built-in `camera.record` is a clean, well-integrated service, but it is intentionally limited in what it exposes to automations. This integration is a more direct, "hacked" wrapper around the same underlying HA stream component that `camera.record` uses - accessing it at a lower level to expose additional control that the official service deliberately does not offer.

## Features

- `camera_start_recording` - a more configurable alternative to `camera.record`
- `camera_stop_recording` - stop a recording in progress, whether started by this integration or by the built-in `camera.record`

## Requirements

- Home Assistant 2024.1.1 onwards
- Camera entity that supports streaming

## Installation

### HACS (recommended)

1. Open HACS in your Home Assistant instance
2. Click the three-dot menu → **Custom repositories**
3. Add `https://github.com/vahagit/camera_record_services` (_Type_: **Integration**)
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
| `entity_id` | yes | - | Camera entity to record, e.g. `camera.front_door` |
| `filename` | yes | - | Full path for the output file, e.g. `/media/clips/front.mp4` |
| `duration` | no | `30` | Recording time in seconds |
| `lookback` | no | `0` | Seconds of stream buffer to prepend - only available if the camera stream is already running before the recording starts. _(See Notes)_ |
| `stop_state_id` | no | - | Entity to watch - recording stops early if this entity reaches `stop_state_value`. Must be used together with `stop_state_value`.  _(See Notes)_ |
| `stop_state_value` | no | - | The state value that triggers early stop, e.g. `"off"`. Must be used together with `stop_state_id`.  _(See Notes)_ |
| `extend_running_task` | no | `true` | If the camera is already recording, extend the running recording rather than ignoring the new request. The new request's parameters are ignored - only the timer is reset.  _(See Notes)_ |

**Example:**
```yaml
service: camera_record_services.camera_start_recording
data:
  entity_id: camera.front_door
  filename: /media/clips/front_door.mp4
  duration: 60
  lookback: 5
  stop_state_id: binary_sensor.front_door_motion
  stop_state_value: "off"
  extend_running_task: true
```

In this example, HA will start recording `camera.front_door` to `/media/clips/front_door.mp4` for up to 60 seconds, prepending the last 5 seconds of the existing stream buffer at the start of the clip. At the same time, it will also watch `binary_sensor.front_door_motion` - if that sensor's state changes to `"off"` before the 60 seconds are up, the recording will stop immediately at that point. Whichever happens first - the `duration` expiring or the sensor reaching `"off"` - will end the recording. If this service is called again for the same camera while it is already recording, the currently running recording will be extended (its timer reset) rather than the new request being dropped, because `extend_running_task` is `true`.

_Note: Even if the recording is extended (by another another service call), `stop_state_id` changing to `stop_state_value` will still finish the recording before the extended `duration` period expires._

---

### `camera_record_services.camera_stop_recording`

Stop an in-progress recording immediately. This works whether the recording was started by this integration or by the built-in `camera.record` service - both use the same underlying HA stream component.

| Parameter | Required | Description |
|---|---|---|
| `entity_id` | yes | Camera entity whose recording should be stopped |

Best-effort - silently does nothing if no stream exists or no recording is in progress.

**Example:**
```yaml
service: camera_record_services.camera_stop_recording
data:
  entity_id: camera.front_door
```

## Notes

### `lookback`

This option only functions if the stream is already active. Typically, this means the camera must be configured with `preload_stream: true` (or equivalent settings for your camera integration) to keep the stream alive. Please refer to the official Home Assistant camera documentation for details on how to enable pre-buffering. If the stream is not already running, `lookback` will not work.

### `stop_state_id` and `stop_state_value`

These two parameters work together to stop a recording early based on the state of a specific entity. Both must be provided, otherwise they are ignored.

When provided, the service races two things against each other: the recording `duration` timer, and a watcher that monitors the specified entity. Whichever finishes first stops the recording. For example, if you set `duration: 120` and `stop_state_id: binary_sensor.front_door_motion` with `stop_state_value: "off"`, the recording will run for up to 2 minutes - but if the motion sensor goes to the `off` state before that, the recording stops at that moment instead.

Only a single entity and a single state value are supported. If your use case requires stopping based on multiple conditions - for example, only stopping when two sensors are both inactive - you will need to create a Helper (template sensor or input boolean) that combines those conditions into a single entity, and point `stop_state_id` at that helper instead.

### `extend_running_task`

This parameter controls what happens when `camera_start_recording` is called for a camera that is already recording.

**Comparison with `camera.record`:** Home Assistant's built-in `camera.record` service does not allow multiple simultaneous recordings for the same camera. If you call `camera.record` while a recording is already in progress, the new request is rejected.

**By default (`extend_running_task: true`)**: This integration behaves differently. Instead of rejecting the new request, it extends the running recording. What that means in practice:
- The internal countdown timer is reset back to its _original_ `duration` value (_from the call that actually started the recording_)
- The new request's parameters are completely ignored
- The recording continues uninterrupted into the same file
- Only the timer is affected

**_Example:_**
*   **Start:** A recording is triggered with a `duration` of **60 seconds** at 12:00:00.
*   **Event:** At 12:00:45 (45 seconds later), the automation triggers again (e.g., motion is detected once more) and calls the service a second time.
*   **Result:** Instead of failing the second call, the already running recording is instructed to keep going. The recording's countdown timer is reset, so it will continue record for a **further 60 seconds** from that moment, up until 12:01:45.
*   **Outcome:** The resulting video contains **105 seconds** of recording. You get one continuous video covering the entire period of activity, rather than multiple chopped-up clips, or worse, a failed recording.

Note: 
- _All settings from the second call will be ignored. The extended `duration` will be taken from the call that initiated the recording (which could even be a `camera.record` call in a totally different automation/script)._
- _The actual recorded time is controlled by the camera's stream, and not this integration. The resulting video may be slightly longer/shorter than anticipated!_

With `extend_running_task: false`, the call works the same as the built-in `camera.record` service: it ignores the new request if the camera is already recording.

### IMPORTANT NOTE:
> The `extend_running_task` relies on internal HA stream component details that are not part of the official public API. It has been tested against all HA Core versions from v2024.1.1 onwards. Although unlikely, a future HA update **could** change the underlying stream internals in a way that breaks this specific feature. If that happens, the integration will log a clear error message explaining that the internal API has changed and that an update is needed.

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

---

_Built using GitHub Copilot + Claude + Perplexity + ChatGPT + Z.ai + Qwen - because they all hallucinate as much as each other - even in 2026!_

If you find this integration useful, please consider giving it a ⭐ on GitHub!
