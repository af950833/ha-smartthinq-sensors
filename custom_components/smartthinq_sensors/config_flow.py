"""Config flow for LG SmartThinQ."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import (
    CONN_CLASS_CLOUD_POLL,
    SOURCE_REAUTH,
    ConfigEntryState,
    ConfigFlow,
    ConfigFlowResult,
)
from homeassistant.const import (
    CONF_BASE,
    CONF_CLIENT_ID,
    CONF_PASSWORD,
    CONF_REGION,
    CONF_TOKEN,
    CONF_USERNAME,
    __version__,
)
from homeassistant.core import callback

from . import LGEAuthentication, is_valid_ha_version
from .const import (
    CONF_CLIENT_ID_CREATED_ON,
    CONF_LANGUAGE,
    CONF_USE_API_V2,
    DOMAIN,
    __min_ha_version__,
)
from .wideq.core_exceptions import AuthenticationError, InvalidCredentialError, TokenError
from .wideq.const import DEFAULT_COUNTRY, DEFAULT_LANGUAGE

CONF_REAUTH_CRED = "reauth_cred"

RESULT_SUCCESS = 0
RESULT_FAIL = 1
RESULT_NO_DEV = 2
RESULT_CRED_FAIL = 3

_LOGGER = logging.getLogger(__name__)


class SmartThinQFlowHandler(ConfigFlow, domain=DOMAIN):
    """Handle SmartThinQ config flow."""

    VERSION = 1
    CONNECTION_CLASS = CONN_CLASS_CLOUD_POLL

    def __init__(self) -> None:
        """Initialize flow."""
        self._region: str = DEFAULT_COUNTRY
        self._language: str = DEFAULT_LANGUAGE
        self._token: str | None = None
        self._client_id: str | None = None
        self._client_id_created_on: datetime | None = None

        self._error: str | None = None
        self._is_import = False

    async def async_step_import(
        self, import_config: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Import a config entry."""
        self._is_import = True
        return await self.async_step_user()

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle a flow initialized by the user interface"""

        if not is_valid_ha_version():
            return self.async_abort(
                reason="unsupported_version",
                description_placeholders={
                    "req_ver": __min_ha_version__,
                    "run_ver": __version__,
                },
            )

        if self._is_import:
            self._error = "invalid_config"
        elif entries := self._async_current_entries():
            entry = entries[0]
            if entry.state == ConfigEntryState.LOADED:
                return self.async_abort(reason="single_instance_allowed")

        if not user_input:
            return self._show_form()

        username = user_input.get(CONF_USERNAME)
        password = user_input.get(CONF_PASSWORD)

        if not (username and password):
            if self.source == SOURCE_REAUTH and not (username or password):
                return await self.async_step_reauth_confirm()
            return self._show_form(errors="no_user_info")

        lge_auth = LGEAuthentication(self._region, self._language)
        auth_info = await lge_auth.get_auth_info_from_login(username, password)
        if not auth_info:
            return await self._manage_error(RESULT_CRED_FAIL, True)

        self._token = auth_info["refresh_token"]
        result = await self._check_connection(lge_auth)
        if result != RESULT_SUCCESS:
            return await self._manage_error(result, True)
        return self._save_config_entry()

    async def _check_connection(self, lge_auth: LGEAuthentication) -> int:
        """Test the connection to ThinQ."""

        try:
            client = await lge_auth.create_client_from_token(
                self._token
            )
        except (AuthenticationError, InvalidCredentialError, TokenError) as exc:
            msg = (
                "Invalid ThinQ credential error. Please use the LG App on your"
                " mobile device to verify if there are Term of Service to accept."
                " Account based on social network are not supported and in most"
                " case do not work with this integration."
            )
            _LOGGER.exception(msg, exc_info=exc)
            return RESULT_CRED_FAIL
        except Exception as exc:  # pylint: disable=broad-except
            _LOGGER.exception("Error connecting to ThinQ", exc_info=exc)
            return RESULT_FAIL

        if not client:
            return RESULT_NO_DEV

        await client.close()
        if not client.has_devices:
            return RESULT_NO_DEV

        self._client_id = client.client_id
        self._client_id_created_on = client.client_id_created_on
        return RESULT_SUCCESS

    async def _manage_error(
        self, error_code: int, is_user_step=False
    ) -> ConfigFlowResult:
        """Manage the error result."""
        if error_code == RESULT_NO_DEV:
            return self.async_abort(reason="no_smartthinq_devices")

        self._error = "unknown"
        if error_code == RESULT_FAIL:
            self._error = "error_connect"
        elif error_code == RESULT_CRED_FAIL:
            self._error = "invalid_credentials"

        if is_user_step:
            return self._show_form()
        return await self.async_step_user()

    @callback
    def _save_config_entry(self) -> ConfigFlowResult:
        """Save the entry."""

        data = {
            CONF_REGION: self._region,
            CONF_LANGUAGE: self._language,
            CONF_TOKEN: self._token,
            CONF_USE_API_V2: True,
        }
        if self._client_id:
            data[CONF_CLIENT_ID] = self._client_id
        if self._client_id_created_on:
            data[CONF_CLIENT_ID_CREATED_ON] = self._client_id_created_on.isoformat()

        # if an entry exists, we are reconfiguring
        if entries := self._async_current_entries():
            entry = entries[0]
            return self.async_update_reload_and_abort(
                entry=entry,
                data=data,
            )

        return self.async_create_entry(title="LGE Devices", data=data)

    @callback
    def _prepare_form_schema(self, step_id="user") -> vol.Schema:
        """Prepare the user forms schema."""
        schema = vol.Schema(
            {
                vol.Required(CONF_USERNAME, default=""): str,
                vol.Required(CONF_PASSWORD, default=""): str,
            }
        )
        return schema

    @callback
    def _show_form(
        self,
        errors: str | None = None,
        step_id="user",
        description_placeholders: dict[str, str] | None = None,
    ) -> ConfigFlowResult:
        """Show the form to the user."""
        base_err = errors or self._error
        self._error = None
        schema = self._prepare_form_schema(step_id)

        return self.async_show_form(
            step_id=step_id,
            data_schema=schema,
            errors={CONF_BASE: base_err} if base_err else None,
            description_placeholders=description_placeholders,
        )

    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> ConfigFlowResult:
        """Perform reauth upon an API authentication error."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Dialog that informs the user that reauth is required."""
        if user_input is None:
            return self.async_show_form(
                step_id="reauth_confirm",
                data_schema=vol.Schema(
                    {vol.Required(CONF_REAUTH_CRED, default=False): bool}
                ),
            )

        if user_input[CONF_REAUTH_CRED] is True:
            return await self.async_step_user()
        return self.async_update_reload_and_abort(self._get_reauth_entry())
