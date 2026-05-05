"""Binary sensor entities for Narwal vacuum."""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import NarwalConfigEntry
from .coordinator import NarwalCoordinator
from .entity import NarwalEntity
from .narwal_client import ERROR_CODES


async def async_setup_entry(
    hass: HomeAssistant,
    entry: NarwalConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up Narwal binary sensor entities."""
    coordinator = entry.runtime_data
    async_add_entities([
        NarwalDockedSensor(coordinator),
        NarwalActiveErrorSensor(coordinator),
    ])


class NarwalDockedSensor(NarwalEntity, BinarySensorEntity):
    """Binary sensor that reports whether the vacuum is on the dock."""

    _attr_translation_key = "docked"

    def __init__(self, coordinator: NarwalCoordinator) -> None:
        """Initialize the docked sensor."""
        super().__init__(coordinator)
        device_id = coordinator.config_entry.data["device_id"]
        self._attr_unique_id = f"{device_id}_docked"

    @property
    def is_on(self) -> bool | None:
        """Return True if the vacuum is on the dock."""
        state = self.coordinator.data
        if state is None:
            return None
        return state.is_docked


class NarwalActiveErrorSensor(NarwalEntity, BinarySensorEntity):
    """Binary sensor that turns on when the robot reports an active fault.

    Driven by robot_base_status field 48.1.2: empty {} = no error, populated
    {1, 2, 3} = active fault (e.g. clean water tank empty, mop washer
    blocked, dock disconnected). Code + message are exposed as separate
    sensors so users can build automations that react to the specific
    fault.
    """

    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    _attr_translation_key = "active_error"

    def __init__(self, coordinator: NarwalCoordinator) -> None:
        super().__init__(coordinator)
        device_id = coordinator.config_entry.data["device_id"]
        self._attr_unique_id = f"{device_id}_active_error"

    @property
    def is_on(self) -> bool | None:
        state = self.coordinator.data
        if state is None:
            return None
        return state.error_code != 0

    @property
    def extra_state_attributes(self) -> dict[str, str | int]:
        state = self.coordinator.data
        if state is None or state.error_code == 0:
            return {}
        return {
            "code": state.error_code,
            "code_hex": f"0x{state.error_code:08x}",
            "identifier": ERROR_CODES.get(state.error_code, "unknown"),
            "severity": state.error_severity,
            "message": state.error_message,
        }


