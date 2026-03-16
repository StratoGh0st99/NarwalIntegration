"""Tests for NarwalTakePhotoButton entity."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

# Install HA stubs before any custom_components import
import tests.ha_stubs

tests.ha_stubs.install()

from custom_components.narwal.button import NarwalTakePhotoButton  # noqa: E402


def _make_coordinator() -> MagicMock:
    """Create a mock coordinator with config_entry."""
    coordinator = MagicMock()
    coordinator.config_entry.data = {"device_id": "test123"}
    coordinator.async_take_snapshot = AsyncMock()
    return coordinator


class TestNarwalTakePhotoButton:
    """Tests for NarwalTakePhotoButton entity."""

    def test_unique_id(self) -> None:
        """unique_id is prefixed with device_id."""
        btn = NarwalTakePhotoButton(_make_coordinator())
        assert btn._attr_unique_id == "test123_take_photo"

    def test_icon(self) -> None:
        """Icon is mdi:camera."""
        btn = NarwalTakePhotoButton(_make_coordinator())
        assert btn._attr_icon == "mdi:camera"

    def test_translation_key(self) -> None:
        """Translation key is take_photo."""
        btn = NarwalTakePhotoButton(_make_coordinator())
        assert btn._attr_translation_key == "take_photo"

    @pytest.mark.asyncio
    async def test_async_press_calls_take_snapshot(self) -> None:
        """async_press calls coordinator.async_take_snapshot(count=1)."""
        coordinator = _make_coordinator()
        btn = NarwalTakePhotoButton(coordinator)
        await btn.async_press()
        coordinator.async_take_snapshot.assert_called_once_with(count=1)
