"""Button entities for Narwal vacuum."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
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
    """Set up Narwal button entities."""
    coordinator = entry.runtime_data
    async_add_entities([
        NarwalTakePhotoButton(coordinator),
    ])


class NarwalTakePhotoButton(NarwalEntity, ButtonEntity):
    """Button that triggers a camera snapshot on the robot."""

    _attr_translation_key = "take_photo"
    _attr_icon = "mdi:camera"

    def __init__(self, coordinator: NarwalCoordinator) -> None:
        """Initialize the take photo button."""
        super().__init__(coordinator)
        device_id = coordinator.config_entry.data["device_id"]
        self._attr_unique_id = f"{device_id}_take_photo"

    async def async_press(self) -> None:
        """Handle button press — capture a single snapshot."""
        await self.coordinator.async_take_snapshot(count=1)
