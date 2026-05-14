"""Tests for fan speed mapping."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

from narwal_client.client import NarwalClient
from narwal_client.const import FanLevel


def test_fan_level_enum_is_one_indexed() -> None:
    assert int(FanLevel.QUIET) == 1
    assert int(FanLevel.NORMAL) == 2
    assert int(FanLevel.STRONG) == 3
    assert int(FanLevel.MAX) == 4


def test_set_fan_speed_encodes_one_indexed_level() -> None:
    client = NarwalClient("127.0.0.1")
    client._ws = AsyncMock()
    client._connected = True

    with patch.object(client, "send_command", new_callable=AsyncMock) as mock_send:
        mock_send.return_value = AsyncMock()
        asyncio.get_event_loop().run_until_complete(client.set_fan_speed(FanLevel.MAX))

        mock_send.assert_awaited_once()
        args, kwargs = mock_send.call_args
        assert kwargs.get("payload") == b"\x08\x04"

