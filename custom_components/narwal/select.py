"""Select entities for Narwal vacuum."""

from __future__ import annotations

import logging

from homeassistant.components.select import SelectEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import NarwalConfigEntry
from .coordinator import NarwalCoordinator
from .entity import NarwalEntity
from .narwal_client import MopHumidity

_LOGGER = logging.getLogger(__name__)

# Flow 2 broadcasts the live mop humidity in robot_base_status field 29
# using a 1-indexed scale (1=Slightly dry, 2=Standard, 3=Slightly wet).
_MOP_HUMIDITY_BROADCAST_TO_NAME: dict[int, str] = {
    1: "slightly_dry",
    2: "standard",
    3: "slightly_wet",
}

# Maps the HA select option name to the MopHumidity enum value sent over
# the wire by client.set_mop_humidity().
_MOP_HUMIDITY_NAME_TO_ENUM: dict[str, MopHumidity] = {
    "slightly_dry": MopHumidity.DRY,
    "standard": MopHumidity.NORMAL,
    "slightly_wet": MopHumidity.WET,
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: NarwalConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up Narwal select entities."""
    coordinator = entry.runtime_data
    async_add_entities([NarwalMopHumiditySelect(coordinator)])


class NarwalMopHumiditySelect(NarwalEntity, SelectEntity):
    """Select entity for the vacuum's mop humidity setting."""

    _attr_translation_key = "mop_humidity"
    _attr_options = list(_MOP_HUMIDITY_NAME_TO_ENUM.keys())
    _attr_icon = "mdi:water-percent"

    def __init__(self, coordinator: NarwalCoordinator) -> None:
        super().__init__(coordinator)
        device_id = coordinator.config_entry.data["device_id"]
        self._attr_unique_id = f"{device_id}_mop_humidity"
        self._last_set: str | None = None

    @property
    def current_option(self) -> str | None:
        """Return the current mop humidity setting.

        Like fan_speed, the broadcasted value (field 29) only reflects
        the *active* clean and reverts to a default while docked. We
        prefer the live broadcast during cleaning, otherwise show the
        last user-set value.
        """
        state = self.coordinator.data
        if state is not None:
            from .narwal_client import WorkingStatus  # local import to avoid cycle
            cleaning = state.working_status in (
                WorkingStatus.CLEANING, WorkingStatus.CLEANING_ALT,
            )
            if cleaning and state.mop_humidity_raw in _MOP_HUMIDITY_BROADCAST_TO_NAME:
                return _MOP_HUMIDITY_BROADCAST_TO_NAME[state.mop_humidity_raw]
        return self._last_set

    async def async_select_option(self, option: str) -> None:
        """Set the mop humidity on the robot."""
        level = _MOP_HUMIDITY_NAME_TO_ENUM.get(option)
        if level is None:
            _LOGGER.warning("Unknown mop humidity option: %s", option)
            return
        resp = await self.coordinator.client.set_mop_humidity(level)
        _LOGGER.info(
            "Set mop humidity %s (enum=%d): code=%s, success=%s",
            option, int(level), resp.result_code, resp.success,
        )
        if resp.success:
            self._last_set = option
            self.async_write_ha_state()
