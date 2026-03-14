"""Config flow for camera_record_services."""

from homeassistant import config_entries
from homeassistant.core import callback

from .const import DOMAIN


class CameraRecordServicesConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Camera Record Services."""

    VERSION = 1

    async def async_step_user(self, user_input=None):
        """Handle the initial step."""
        if self._async_current_entries():
            return self.async_abort(reason="single_instance_allowed")
        if user_input is not None:
            return self.async_create_entry(title="Camera Record Services", data={})
        return self.async_show_form(step_id="user")

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        """Return the options flow handler."""
        return CameraRecordServicesOptionsFlow()


class CameraRecordServicesOptionsFlow(config_entries.OptionsFlow):
    """Show usage guide via the Configure button on the integration page."""

    def __init__(self) -> None:
        """Initialise the options flow."""

    async def async_step_init(self, user_input=None):
        """Show the usage guide."""
        if user_input is not None:
            return self.async_create_entry(title="", data={})
        return self.async_show_form(step_id="init")
