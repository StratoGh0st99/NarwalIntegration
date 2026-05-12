"""Config flow for Narwal vacuum integration."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.helpers.service_info.dhcp import DhcpServiceInfo
from homeassistant.helpers.service_info.zeroconf import ZeroconfServiceInfo

from .narwal_client import NarwalClient, NarwalCommandError, NarwalConnectionError

from .const import CONF_MODEL, CONF_PRODUCT_KEY, DEFAULT_PORT, DOMAIN, NARWAL_MODELS

_LOGGER = logging.getLogger(__name__)

MODEL_OPTIONS = list(NARWAL_MODELS.keys())

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required("host"): str,
        vol.Optional("port", default=DEFAULT_PORT): int,
        vol.Required(CONF_MODEL, default=MODEL_OPTIONS[0]): vol.In(MODEL_OPTIONS),
    }
)


class NarwalConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Narwal vacuum."""

    VERSION = 2

    def __init__(self) -> None:
        super().__init__()
        # Pre-filled host when discovery (zeroconf / DHCP) finds the
        # robot before the user starts the flow.
        self._discovered_host: str | None = None

    async def _check_already_configured(
        self, host: str, fallback_uid: str,
    ) -> ConfigFlowResult | None:
        """Return an abort result when this host is already a config
        entry, otherwise None and seed the discovery unique_id.

        The user step assigns unique_id from the robot's device_id
        (queried over the WebSocket), which mDNS / DHCP can't see.
        Without a host-based check the same robot would re-appear as
        a "Discovered" card forever after a manual add.
        """
        for entry in self._async_current_entries(include_ignore=False):
            if entry.data.get("host") == host:
                # Update host on the matching entry in case the IP
                # drifted (DHCP renewal, robot moved subnets) and
                # abort the discovery flow.
                self.hass.config_entries.async_update_entry(
                    entry, data={**entry.data, "host": host},
                )
                return self.async_abort(reason="already_configured")
        await self.async_set_unique_id(fallback_uid)
        self._abort_if_unique_id_configured(updates={"host": host})
        return None

    async def async_step_zeroconf(
        self, discovery_info: ZeroconfServiceInfo
    ) -> ConfigFlowResult:
        """Pick up Narwal robots advertising `_narwal_sweeper._tcp.local.`.

        Robots broadcast an instance name like
        ``_app_wss_server_<6hex>._narwal_sweeper._tcp.local.`` with a
        hostname ``NARWAL_<6hex>.local.`` on port 9002. We only use
        the IP for now — the user still picks the model on the next
        step, the model name isn't in the mDNS payload.
        """
        host = str(discovery_info.host)
        already = await self._check_already_configured(
            host, discovery_info.hostname.rstrip("."),
        )
        if already is not None:
            return already
        self._discovered_host = host
        self.context["title_placeholders"] = {"host": host}
        return await self.async_step_user()

    async def async_step_dhcp(
        self, discovery_info: DhcpServiceInfo
    ) -> ConfigFlowResult:
        """Pick up Narwal robots from DHCP hostname matches.

        Backup for when zeroconf is filtered (some routers / VLANs).
        Hostname pattern ``NARWAL_*`` / ``narwal_*`` is declared in
        manifest.json.
        """
        host = str(discovery_info.ip)
        already = await self._check_already_configured(
            host, discovery_info.hostname or host,
        )
        if already is not None:
            return already
        self._discovered_host = host
        self.context["title_placeholders"] = {"host": host}
        return await self.async_step_user()

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial step — user enters IP, port, and model."""
        errors: dict[str, str] = {}

        if user_input is not None:
            host = user_input["host"]
            port = user_input.get("port", DEFAULT_PORT)
            model_label = user_input[CONF_MODEL]
            product_key = NARWAL_MODELS[model_label]

            # If user selected a specific model, set topic prefix directly
            topic_prefix = None if product_key == "auto" else f"/{product_key}"

            client = NarwalClient(
                host=host, port=port, topic_prefix=topic_prefix,
            )
            try:
                await client.connect()
                # Discover device_id from broadcast, then query info
                await client.discover_device_id(timeout=15.0)
                # Drain any stale field5 responses left in the WebSocket
                # buffer from discover's wake probes before sending a
                # real command
                await client.drain_ws_buffer()
                device_info = await client.get_device_info()
            except Exception as ex:
                _LOGGER.warning(
                    "Setup failed: %s: %s", type(ex).__name__, ex,
                )
                errors["base"] = "cannot_connect"
            else:
                device_id = device_info.device_id
                await self.async_set_unique_id(device_id)
                self._abort_if_unique_id_configured()

                # Use the product key that actually worked (may have been
                # auto-detected during discovery even if user picked "auto")
                resolved_key = client.topic_prefix.lstrip("/")

                return self.async_create_entry(
                    title=model_label if product_key != "auto" else f"Narwal {resolved_key}",
                    data={
                        "host": host,
                        "port": port,
                        "device_id": device_id,
                        CONF_PRODUCT_KEY: resolved_key,
                        CONF_MODEL: model_label,
                    },
                )
            finally:
                await client.disconnect()

        # If we got here from a discovery step, pre-fill the host so
        # the user only has to confirm the model.
        schema = STEP_USER_DATA_SCHEMA
        if self._discovered_host and user_input is None:
            schema = vol.Schema({
                vol.Required("host", default=self._discovered_host): str,
                vol.Optional("port", default=DEFAULT_PORT): int,
                vol.Required(CONF_MODEL, default=MODEL_OPTIONS[0]): vol.In(MODEL_OPTIONS),
            })

        return self.async_show_form(
            step_id="user",
            data_schema=schema,
            errors=errors,
        )
