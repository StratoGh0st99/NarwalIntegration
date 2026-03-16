"""Switch entities for Narwal vacuum."""

from __future__ import annotations

from homeassistant.components.switch import SwitchEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import NarwalConfigEntry
from .coordinator import NarwalCoordinator
from .entity import NarwalEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: NarwalConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up Narwal switch entities."""
    coordinator = entry.runtime_data
    async_add_entities([
        NarwalCameraLightSwitch(coordinator),
    ])


class NarwalCameraLightSwitch(NarwalEntity, SwitchEntity):
    """Switch that controls the robot's camera LED fill light."""

    _attr_translation_key = "camera_light"
    _attr_icon = "mdi:led-on"

    def __init__(self, coordinator: NarwalCoordinator) -> None:
        """Initialize the camera light switch."""
        super().__init__(coordinator)
        device_id = coordinator.config_entry.data["device_id"]
        self._attr_unique_id = f"{device_id}_camera_light"
        self._is_on: bool = False

    @property
    def is_on(self) -> bool:
        """Return True if the camera LED is on."""
        return self._is_on

    async def async_turn_on(self, **kwargs) -> None:
        """Turn on the camera LED."""
        await self.coordinator.client.set_led(on=True)
        self._is_on = True
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs) -> None:
        """Turn off the camera LED."""
        await self.coordinator.client.set_led(on=False)
        self._is_on = False
        self.async_write_ha_state()
