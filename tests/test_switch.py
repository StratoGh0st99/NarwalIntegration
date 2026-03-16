"""Tests for NarwalCameraLightSwitch entity."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

# Install HA stubs before any custom_components import
import tests.ha_stubs

tests.ha_stubs.install()

from custom_components.narwal.switch import NarwalCameraLightSwitch  # noqa: E402


def _make_coordinator() -> MagicMock:
    """Create a mock coordinator with config_entry and client."""
    coordinator = MagicMock()
    coordinator.config_entry.data = {"device_id": "test123"}
    coordinator.client.set_led = AsyncMock()
    return coordinator


class TestNarwalCameraLightSwitch:
    """Tests for NarwalCameraLightSwitch entity."""

    def test_unique_id(self) -> None:
        """unique_id is prefixed with device_id."""
        sw = NarwalCameraLightSwitch(_make_coordinator())
        assert sw._attr_unique_id == "test123_camera_light"

    def test_icon(self) -> None:
        """Icon is mdi:led-on."""
        sw = NarwalCameraLightSwitch(_make_coordinator())
        assert sw._attr_icon == "mdi:led-on"

    def test_translation_key(self) -> None:
        """Translation key is camera_light."""
        sw = NarwalCameraLightSwitch(_make_coordinator())
        assert sw._attr_translation_key == "camera_light"

    def test_is_on_starts_false(self) -> None:
        """Switch starts in the OFF state."""
        sw = NarwalCameraLightSwitch(_make_coordinator())
        assert sw.is_on is False

    @pytest.mark.asyncio
    async def test_async_turn_on(self) -> None:
        """async_turn_on calls set_led(on=True) and sets is_on=True."""
        coordinator = _make_coordinator()
        sw = NarwalCameraLightSwitch(coordinator)
        await sw.async_turn_on()
        coordinator.client.set_led.assert_called_once_with(on=True)
        assert sw.is_on is True

    @pytest.mark.asyncio
    async def test_async_turn_off(self) -> None:
        """async_turn_off calls set_led(on=False) and sets is_on=False."""
        coordinator = _make_coordinator()
        sw = NarwalCameraLightSwitch(coordinator)
        # Turn on first, then off
        await sw.async_turn_on()
        coordinator.client.set_led.reset_mock()
        await sw.async_turn_off()
        coordinator.client.set_led.assert_called_once_with(on=False)
        assert sw.is_on is False
