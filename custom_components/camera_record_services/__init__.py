"""
Custom integration: camera_record_services (fork-v1-rev11)

Converted from pyscript script fork-v1-rev11. Provides two services
callable from automations:

  camera_record_services.camera_start_recording
    entity_id:       camera.my_camera          # required
    filename:        /media/clip.mp4           # required — plain string, template on the HA side
    duration:        30                        # optional, seconds, default 30
    lookback:        0                         # optional, seconds, default 0
    stop_state_id:   binary_sensor.motion      # optional — entity to watch for early stop
    stop_state_value: "off"                    # optional — value that triggers early stop
                                               # stop_state_id and stop_state_value must be
                                               # provided together or not at all

  camera_record_services.camera_stop_recording
    entity_id: camera.my_camera       # required

Both services are best-effort. camera_stop_recording will silently no-op if
no recording is in progress or if the stream does not exist yet.

No custom state entities are created or maintained by this integration.

Installation
------------
Place this directory at:
  <config>/custom_components/camera_record_services/

Then restart HA and add the integration via Settings → Integrations → Add Integration.
"""

import asyncio
import logging
import os

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers.typing import ConfigType

_LOGGER = logging.getLogger(__name__)

from .const import DOMAIN

# The string value of stream.const.RECORDER_PROVIDER.
# We import it at runtime so that if the constant is ever renamed we get a
# clean ImportError rather than a silent wrong-key miss.  The fallback keeps
# things working on older HA versions that already had the string as "recorder".
try:
    from homeassistant.components.stream.const import RECORDER_PROVIDER as _RECORDER_PROVIDER
except ImportError:
    _RECORDER_PROVIDER = "recorder"


# Minimum valid recording file size in bytes. Files smaller than this contain
# only the MP4 container header with no actual video data — indicating the
# stream failed to capture anything meaningful.
_MIN_RECORDING_SIZE = 1024


def _get_camera(hass, entity_id):
    """Return the Camera entity object, or None if not found."""
    component = hass.data.get("camera")
    if component is None:
        _LOGGER.error("camera_record_services: camera component not loaded")
        return None
    camera = component.get_entity(entity_id)
    if camera is None:
        _LOGGER.error(
            "camera_record_services: entity '%s' not found in camera component",
            entity_id,
        )
    return camera


async def _check_recording_file(filename):
    """Validate that a recording file exists and contains real video data.

    Waits up to 5 seconds (1 second at a time) for the final file to appear
    and reach a valid size — covering cameras that are slow to finalise the
    MP4 after async_record returns.

    If the final file is still not found after 5 attempts, checks for a .tmp
    version left behind by a failed stream rename and renames it if present
    (6.7 safety fix — only renames if the final file does NOT already exist).

    In all cases, checks the file size is above _MIN_RECORDING_SIZE to
    confirm actual video data was written.

    Returns True if a valid recording file is confirmed, False otherwise.
    """
    for attempt in range(5):
        await asyncio.sleep(1)
        if os.path.isfile(filename):
            size = os.path.getsize(filename)
            if size > _MIN_RECORDING_SIZE:
                return True

    # Final file not found after 5 attempts — try .tmp fallback.
    tmp_path = filename + ".tmp"
    if not os.path.isfile(filename) and os.path.isfile(tmp_path):
        try:
            os.rename(tmp_path, filename)
        except OSError as err:
            _LOGGER.error(
                "camera_record_services: failed to rename .tmp file '%s': %s",
                tmp_path,
                err,
            )
            return False
        if os.path.isfile(filename):
            size = os.path.getsize(filename)
            if size > _MIN_RECORDING_SIZE:
                return True
            _LOGGER.warning(
                "camera_record_services: renamed .tmp file '%s' is too small (%d bytes) "
                "— no real video data was captured",
                filename,
                size,
            )
            return False

    if not os.path.isfile(filename) and not os.path.isfile(tmp_path):
        _LOGGER.warning(
            "camera_record_services: neither '%s' nor '%s' found after 5 seconds "
            "— stream object may have failed silently",
            filename,
            tmp_path,
        )

    return False


async def camera_start_recording(hass, entity_id=None, filename=None, duration=30, lookback=0, stop_state_id=None, stop_state_value=None, extend_running_task=True):
    """Start recording a camera stream to a file.

    Replicates camera.record but registers under camera_record_services so it
    can be extended alongside camera_stop_recording without touching HA core.
    """
    _LOGGER.info("camera_start_recording: called with entity_id='%s' filename='%s' duration=%s lookback=%s stop_state_id='%s' stop_state_value='%s' extend_running_task=%s", entity_id, filename, duration, lookback, stop_state_id, stop_state_value, extend_running_task)
    if entity_id is None or filename is None:
        _LOGGER.error("camera_start_recording: 'entity_id' and 'filename' are both required")
        return

    if (stop_state_id is None) != (stop_state_value is None):
        _LOGGER.error(
            "camera_start_recording: 'stop_state_id' and 'stop_state_value' must both be "
            "provided together or not at all"
        )
        return

    camera = _get_camera(hass, entity_id)
    if camera is None:
        return

    # async_create_stream returns the existing Stream if already alive,
    # or creates a new one. It mirrors what camera.__init__ does in
    # async_handle_record_service.
    stream = await camera.async_create_stream()
    if stream is None:
        _LOGGER.error(
            "camera_start_recording: could not create stream for '%s' — "
            "does the camera support streaming?",
            entity_id,
        )
        return

    # If a recording is already in progress, optionally extend it and return early.
    recorder_output = stream.outputs().get(_RECORDER_PROVIDER)
    if recorder_output is not None:
        if extend_running_task:
            try:
                # --- OPTIMISTIC CALL ---
                # Optimistically try to extend the timer.
                recorder_output.idle_timer.awake()
                _LOGGER.info(
                    "camera_start_recording: '%s' is already recording to '%s' - this task has been extended. "
                    "New request ignored: filename='%s' duration=%s lookback=%s stop_state_id='%s' stop_state_value='%s'",
                    entity_id, recorder_output.video_path, filename, duration, lookback, stop_state_id, stop_state_value,
                )
            except Exception as err:
                # --- ERROR DIAGNOSIS ---
                # An error occurred. Let's figure out if it's because the API changed
                # or if something else went wrong.

                # 1. Check for the 'idle_timer' attribute
                timer_exists = hasattr(recorder_output, 'idle_timer')

                # 2. Check for the 'awake' method
                # (Use nested getattr with defaults to ensure this check never crashes)
                method_exists = callable(
                    getattr(getattr(recorder_output, 'idle_timer', None), 'awake', None)
                )
                if not timer_exists or not method_exists:
                    # The internal API has changed/removed.
                    # We include the diagnostic details in the error message.
                    raise HomeAssistantError(
                        f"Cannot extend recording: Internal API mismatch. "
                        f"idle_timer found: {timer_exists}, awake method found: {method_exists}. "
                        f"The Stream component structure has likely changed and this integration needs an update."
                    ) from err

                # The API exists, so the error was a genuine runtime error (e.g. inside awake()).
                # Log the technical details and re-raise the original exception.
                _LOGGER.error(
                    "camera_start_recording: Failed to extend recording for '%s' due to an internal error: %s",
                    entity_id,
                    err
                )
                raise
        return

    try:
        _LOGGER.info(
            "camera_start_recording: starting recording '%s' → %s (duration=%ss, lookback=%ss)",
            entity_id,
            filename,
            duration,
            lookback,
        )
        if stop_state_id is not None:
            # Run recording as a background task so we can race it against
            # the stop-state condition.
            record_task = asyncio.create_task(
                stream.async_record(
                    video_path=str(filename),
                    duration=int(duration),
                    lookback=int(lookback),
                )
            )
            # Use async_track_state_change_event and an asyncio.Event to watch
            # for the stop-state condition.
            async def _stop_state_watcher():
                event = asyncio.Event()

                @callback
                def _state_changed(event_obj):
                    new_state = event_obj.data.get("new_state")
                    if new_state and new_state.state == str(stop_state_value):
                        event.set()

                unsub = async_track_state_change_event(hass, [stop_state_id], _state_changed)
                try:
                    await event.wait()
                finally:
                    unsub()

            watcher_task = asyncio.create_task(_stop_state_watcher())
            # Wait for whichever completes first.
            done, _ = await asyncio.wait(
                [record_task, watcher_task],
                return_when=asyncio.FIRST_COMPLETED,
            )
            if record_task not in done:
                # Stop-state fired before duration expired — stop the recording.
                _LOGGER.info("camera_start_recording: stop-state fired — cancelling watcher and stopping recording")
                watcher_task.cancel()
                recorder_output = stream.outputs().get(_RECORDER_PROVIDER)
                if recorder_output is not None:
                    await stream.remove_provider(recorder_output)
                # Wait for record_task to finish cleanly after the stop signal.
                await record_task
            else:
                # Duration expired naturally — cancel the watcher.
                watcher_task.cancel()
        else:
            # No stop condition — await directly.
            await stream.async_record(
                video_path=str(filename),
                duration=int(duration),
                lookback=int(lookback),
            )
        await _check_recording_file(str(filename))
        _LOGGER.info(
            "camera_start_recording: recording completed for '%s' → %s",
            entity_id,
            filename,
        )
    except Exception as err:  # HomeAssistantError, OSError, etc.
        _LOGGER.error(
            "camera_start_recording: failed to start recording for '%s': %s",
            entity_id,
            err,
        )


async def camera_stop_recording(hass, entity_id=None):
    """Stop an in-progress camera recording.

    This is best-effort:
    - If no stream exists, silently returns.
    - If no recording is in progress, silently returns.
    - The actual file will be finalised at the next segment boundary,
      identical to normal end-of-duration behaviour.
    - There is no guarantee that anything was recorded.
    """
    _LOGGER.info("camera_stop_recording: called with entity_id='%s'", entity_id)
    if entity_id is None:
        _LOGGER.error("camera_stop_recording: 'entity_id' is required")
        return

    camera = _get_camera(hass, entity_id)
    if camera is None:
        return

    # camera.stream is None until the first stream is created.
    stream = getattr(camera, "stream", None)
    if stream is None:
        _LOGGER.debug(
            "camera_stop_recording: '%s' has no active stream, nothing to stop",
            entity_id,
        )
        return

    # Use the public outputs() method (returns a MappingProxyType copy of
    # the internal outputs dict) rather than accessing _outputs directly.
    recorder_output = stream.outputs().get(_RECORDER_PROVIDER)

    if recorder_output is None:
        _LOGGER.debug(
            "camera_stop_recording: no recording in progress for '%s'",
            entity_id,
        )
        return

    try:
        # remove_provider signals the recorder_save_worker thread, drains
        # its queue, finalises the MP4 container and flushes to disk —
        # exactly the same teardown path as normal end-of-duration.
        await stream.remove_provider(recorder_output)
        await _check_recording_file(recorder_output.video_path)
        _LOGGER.info(
            "camera_stop_recording: recording stopped for '%s'", entity_id
        )
    except Exception as err:
        _LOGGER.error(
            "camera_stop_recording: error while stopping recording for '%s': %s",
            entity_id,
            err,
        )


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up the camera_record_services integration."""
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up camera_record_services from a config entry."""

    async def handle_camera_start_recording(call: ServiceCall) -> None:
        await camera_start_recording(
            hass,
            entity_id=call.data.get("entity_id"),
            filename=call.data.get("filename"),
            duration=call.data.get("duration", 30),
            lookback=call.data.get("lookback", 0),
            stop_state_id=call.data.get("stop_state_id"),
            stop_state_value=call.data.get("stop_state_value"),
            extend_running_task=call.data.get("extend_running_task", True),
        )

    async def handle_camera_stop_recording(call: ServiceCall) -> None:
        await camera_stop_recording(
            hass,
            entity_id=call.data.get("entity_id"),
        )

    hass.services.async_register(DOMAIN, "camera_start_recording", handle_camera_start_recording)
    hass.services.async_register(DOMAIN, "camera_stop_recording", handle_camera_stop_recording)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    hass.services.async_remove(DOMAIN, "camera_start_recording")
    hass.services.async_remove(DOMAIN, "camera_stop_recording")
    return True
