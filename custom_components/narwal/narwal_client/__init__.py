"""Narwal robot vacuum client library — local WebSocket API."""

from .client import NarwalClient, NarwalCommandError, NarwalConnectionError
from .const import (
    ERROR_CODES,
    ERROR_MESSAGE_SNIPPETS_EN,
    ERROR_MESSAGES_EN,
    CommandResult,
    FanLevel,
    MopHumidity,
    WorkingStatus,
)
from .models import CommandResponse, DeviceInfo, MapData, MapDisplayData, NarwalState, RoomInfo
from .protocol import build_frame, parse_frame

__all__ = [
    "NarwalClient",
    "NarwalCommandError",
    "NarwalConnectionError",
    "NarwalState",
    "CommandResponse",
    "CommandResult",
    "DeviceInfo",
    "ERROR_CODES",
    "ERROR_MESSAGES_EN",
    "ERROR_MESSAGE_SNIPPETS_EN",
    "FanLevel",
    "MapData",
    "MapDisplayData",
    "MopHumidity",
    "RoomInfo",
    "WorkingStatus",
    "build_frame",
    "parse_frame",
]
