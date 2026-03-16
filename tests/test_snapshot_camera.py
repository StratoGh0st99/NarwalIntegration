"""Tests for NarwalSnapshotCamera entity."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

# Install HA stubs before any custom_components import
import tests.ha_stubs

tests.ha_stubs.install()

from custom_components.narwal.camera import NarwalSnapshotCamera  # noqa: E402


def _make_coordinator() -> MagicMock:
    """Create a mock coordinator with config_entry."""
    coordinator = MagicMock()
    coordinator.config_entry.data = {"device_id": "test123"}
    return coordinator


class TestNarwalSnapshotCamera:
    """Tests for NarwalSnapshotCamera entity."""

    def test_unique_id(self) -> None:
        """unique_id is prefixed with device_id."""
        cam = NarwalSnapshotCamera(_make_coordinator())
        assert cam._attr_unique_id == "test123_snapshot"

    def test_is_not_streaming(self) -> None:
        """Snapshot camera does not stream — it is updated on demand."""
        cam = NarwalSnapshotCamera(_make_coordinator())
        assert cam._attr_is_streaming is False

    @pytest.mark.asyncio
    async def test_camera_image_none_before_snapshot(self) -> None:
        """async_camera_image returns None before any snapshot is taken."""
        cam = NarwalSnapshotCamera(_make_coordinator())
        result = await cam.async_camera_image()
        assert result is None

    @pytest.mark.asyncio
    async def test_camera_image_after_update(self) -> None:
        """async_camera_image returns the bytes set by update_snapshot."""
        cam = NarwalSnapshotCamera(_make_coordinator())
        fake_bytes = b"fake_image_data"
        cam.update_snapshot(fake_bytes)
        result = await cam.async_camera_image()
        assert result == fake_bytes

    @pytest.mark.asyncio
    async def test_update_snapshot_replaces_previous(self) -> None:
        """update_snapshot replaces existing snapshot bytes."""
        cam = NarwalSnapshotCamera(_make_coordinator())
        cam.update_snapshot(b"first")
        cam.update_snapshot(b"second")
        result = await cam.async_camera_image()
        assert result == b"second"
