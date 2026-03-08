"""Tests for narwal_client.map_renderer — render_base_map and render_overlay.

Covers MAP-01 (map rendering pipeline) validation gaps:
  - render_base_map returns valid PIL Image with rooms and dock
  - render_base_map handles empty/missing grid data gracefully
  - render_overlay returns valid PNG bytes with trail and robot
"""

from __future__ import annotations

import io
import zlib

from narwal_client.map_renderer import (
    render_base_map,
    render_overlay,
    decompress_map,
    _decode_packed_varints,
)


def _make_compressed_grid(width: int, height: int, fill_value: int = 0) -> bytes:
    """Create a compressed map grid with all pixels set to fill_value.

    Builds a protobuf-style packed varint field (field 1, wire type 2)
    containing width*height varint-encoded pixel values.
    """
    # Encode each pixel as a varint
    raw_varints = bytearray()
    for _ in range(width * height):
        val = fill_value
        while val > 0x7F:
            raw_varints.append((val & 0x7F) | 0x80)
            val >>= 7
        raw_varints.append(val & 0x7F)

    # Wrap in protobuf field 1 length-delimited header
    length = len(raw_varints)
    length_varint = bytearray()
    v = length
    while v > 0x7F:
        length_varint.append((v & 0x7F) | 0x80)
        v >>= 7
    length_varint.append(v & 0x7F)

    data = bytes([0x0A]) + bytes(length_varint) + bytes(raw_varints)
    return zlib.compress(data)


def _make_room_grid(width: int, height: int, room_id: int = 1) -> bytes:
    """Create a compressed grid where all pixels belong to a specific room.

    Pixel value encoding: room_id << 8 | pixel_type.
    pixel_type 0x00 = floor (no wall flag).
    """
    pixel_value = (room_id << 8) | 0x00
    return _make_compressed_grid(width, height, fill_value=pixel_value)


class TestRenderBaseMap:
    """Tests for render_base_map() — static floor plan rendering."""

    def test_returns_pil_image_with_rooms(self) -> None:
        """Given valid MapData with rooms and grid data, returns a PIL Image."""
        from PIL import Image

        width, height = 20, 20
        compressed = _make_room_grid(width, height, room_id=1)

        result = render_base_map(
            compressed, width, height,
            room_names={1: "Kitchen"},
        )

        assert result is not None
        assert isinstance(result, Image.Image)
        assert result.size == (width, height)

    def test_with_dock_position(self) -> None:
        """Given MapData with dock_x/dock_y, render_base_map includes dock."""
        from PIL import Image

        width, height = 30, 30
        compressed = _make_room_grid(width, height, room_id=2)

        result = render_base_map(
            compressed, width, height,
            dock_x=15.0, dock_y=15.0,
        )

        assert result is not None
        assert isinstance(result, Image.Image)
        # The dock is drawn as a white circle — check that the center pixel
        # at the dock position (Y-flipped) is white or near-white
        dock_px_y = height - 1 - 15  # Y-flip
        r, g, b = result.getpixel((15, dock_px_y))
        assert r > 200 and g > 200 and b > 200, (
            f"Expected white-ish dock pixel, got ({r}, {g}, {b})"
        )

    def test_empty_compressed_data(self) -> None:
        """Given empty compressed data, returns None gracefully."""
        result = render_base_map(b"", 100, 100)
        assert result is None

    def test_zero_dimensions(self) -> None:
        """Given zero width/height, returns None."""
        compressed = _make_room_grid(10, 10)
        assert render_base_map(compressed, 0, 100) is None
        assert render_base_map(compressed, 100, 0) is None

    def test_no_room_names(self) -> None:
        """render_base_map works without room_names (no labels drawn)."""
        from PIL import Image

        width, height = 15, 15
        compressed = _make_room_grid(width, height, room_id=3)

        result = render_base_map(compressed, width, height)
        assert result is not None
        assert isinstance(result, Image.Image)


class TestRenderOverlay:
    """Tests for render_overlay() — robot + trail on cached base map."""

    def _make_base_image(self, width: int = 30, height: int = 30):
        """Create a simple base PIL Image for overlay tests."""
        from PIL import Image
        return Image.new("RGB", (width, height), (100, 100, 100))

    def test_returns_png_bytes(self) -> None:
        """render_overlay returns valid PNG bytes."""
        base = self._make_base_image()
        result = render_overlay(
            base, height=30,
            robot_x=15.0, robot_y=15.0,
            robot_heading=90.0,
        )

        assert isinstance(result, bytes)
        assert len(result) > 0
        # Verify it's a valid PNG (starts with PNG signature)
        assert result[:8] == b"\x89PNG\r\n\x1a\n"

    def test_with_trail(self) -> None:
        """render_overlay draws trail positions as line segments."""
        base = self._make_base_image(width=50, height=50)
        trail = [(10.0, 10.0), (20.0, 20.0), (30.0, 30.0)]

        result = render_overlay(
            base, height=50,
            robot_x=30.0, robot_y=30.0,
            trail=trail,
        )

        assert isinstance(result, bytes)
        assert result[:8] == b"\x89PNG\r\n\x1a\n"

    def test_no_robot_position(self) -> None:
        """render_overlay works with no robot position (trail only or empty)."""
        base = self._make_base_image()
        result = render_overlay(base, height=30)

        assert isinstance(result, bytes)
        assert result[:8] == b"\x89PNG\r\n\x1a\n"

    def test_does_not_modify_base(self) -> None:
        """render_overlay does not mutate the base image."""
        from PIL import Image
        base = self._make_base_image()
        # Save original pixel for comparison
        original_pixel = base.getpixel((15, 15))

        render_overlay(
            base, height=30,
            robot_x=15.0, robot_y=15.0,
        )

        assert base.getpixel((15, 15)) == original_pixel

    def test_full_pipeline_base_then_overlay(self) -> None:
        """End-to-end: render_base_map then render_overlay produces valid PNG."""
        width, height = 40, 40
        compressed = _make_room_grid(width, height, room_id=1)

        base = render_base_map(
            compressed, width, height,
            dock_x=20.0, dock_y=20.0,
            room_names={1: "Living Room"},
        )
        assert base is not None

        trail = [(18.0, 18.0), (22.0, 22.0), (25.0, 20.0)]
        png = render_overlay(
            base, height=height,
            robot_x=25.0, robot_y=20.0,
            robot_heading=45.0,
            trail=trail,
        )

        assert isinstance(png, bytes)
        assert png[:8] == b"\x89PNG\r\n\x1a\n"
        # Verify we can open the PNG
        from PIL import Image
        img = Image.open(io.BytesIO(png))
        assert img.size == (width, height)
