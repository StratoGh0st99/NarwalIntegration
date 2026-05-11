"""Data models for Narwal vacuum state."""

from __future__ import annotations

import struct
from dataclasses import dataclass, field
from typing import Any, ClassVar

from .const import CommandResult, FanLevel, MopHumidity, WorkingStatus


@dataclass
class DeviceInfo:
    """Device identity from get_device_info response."""

    product_key: str = ""
    device_id: str = ""
    firmware_version: str = ""


# ROOM_TYPE enum → display name (Flow 1 / AX12, from APK libapp.so strings).
_FLOW1_ROOM_TYPE_NAMES: dict[int, str] = {
    0: "Room",
    1: "Primary Bedroom",
    2: "Secondary Bedroom",
    3: "Living Room",
    4: "Kitchen",
    5: "Study",
    6: "Bathroom",
    7: "Dining Room",
    8: "Corridor",
    9: "Balcony",
    10: "Utility Room",
    11: "Cloak Room",
    12: "Nursery",
    13: "Recreation Room",
    14: "Shower Room",
    15: "Other",
}

# Flow 2 reorders the ROOM_TYPE enum vs Flow 1. Confirmed via live capture
# (firmware v01.07.19.00, product_key QxMSPG6VSO) by walking every type in
# the Narwal app's room-type picker. Only deltas are listed; sub_types not
# present here use the Flow 1 name.
_FLOW2_ROOM_TYPE_OVERRIDES: dict[int, str] = {
    1: "Master Bedroom",
    5: "Bathroom",
    6: "Toilet",
    7: "Balcony",
    8: "Dining Room",
    9: "Cloakroom",
    10: "Corridor",
    11: "Study",
    14: "Storage Room",
}

# product_keys that use the Flow 2 mapping. Add more as community confirms.
_FLOW2_PRODUCT_KEYS: frozenset[str] = frozenset({"QxMSPG6VSO"})


def get_room_type_names(product_key: str | None) -> dict[int, str]:
    """Return the ROOM_TYPE → display-name mapping for a given device.

    Flow 2 (and possibly other newer models) renamed/reordered the ROOM_TYPE
    enum. We pick the right base mapping from product_key and fall back to
    Flow 1 for unknown devices.
    """
    base = dict(_FLOW1_ROOM_TYPE_NAMES)
    if product_key and product_key in _FLOW2_PRODUCT_KEYS:
        base.update(_FLOW2_ROOM_TYPE_OVERRIDES)
    return base


@dataclass
class RoomInfo:
    """A room on the map.

    Fields from get_map / get_editable_map field 2.12:
      field 1: room_id (matches pixel value >> 8 in map grid)
      field 2: room_sub_type — ROOM_TYPE enum from APK. The string mapping
               differs between Flow 1 and Flow 2 (see get_room_type_names).
      field 3: user-assigned name (UTF-8, empty if not named by user)
      field 4: category (1=room, 2=utility/small space)
      field 8: instance_index (1-based, for numbering duplicates: Bathroom 1, 2, 3...)
    """

    room_id: int = 0
    name: str = ""  # user-assigned name from field 3
    room_sub_type: int = 0  # ROOM_TYPE enum from field 2
    category: int = 0  # 1=room, 2=utility (field 4)
    instance_index: int = 0  # numbering for duplicates (field 8)

    # ROOM_TYPE enum → default display name. Set by MapData.from_response
    # based on the connected device's product_key; defaults to Flow 1 names.
    ROOM_TYPE_NAMES: dict[int, str] = field(default=None, repr=False)

    def __post_init__(self):
        if self.ROOM_TYPE_NAMES is None:
            object.__setattr__(self, "ROOM_TYPE_NAMES", dict(_FLOW1_ROOM_TYPE_NAMES))

    @property
    def display_name(self) -> str:
        """Return user name if set, otherwise generate default from ROOM_TYPE enum.

        Matches Narwal app behavior: unnamed rooms show their type name
        with an instance number suffix for duplicates (e.g. "Bathroom 2").
        """
        if self.name:
            return self.name
        base = self.ROOM_TYPE_NAMES.get(self.room_sub_type, "Room")
        if self.instance_index > 1:
            return f"{base} {self.instance_index}"
        return base


@dataclass
class ObstacleInfo:
    """An obstacle/furniture annotation on the map.

    Parsed from get_map field 2.32 (MapFurnitureInfoList).
    The typeId maps to the furniture enum from APK map_furniture.json.

    bbp field mapping (confirmed from probe data + APK schema):
      bbp field 1 -> id (int32)
      bbp field 2 -> typeId (uint32, furniture enum)
      bbp field 3.1.1 -> centerX (float32)
      bbp field 3.1.2 -> centerY (float32)
      bbp field 3.2 -> width (float32)
      bbp field 3.3 -> height (float32)
      bbp field 4 -> angle (float32, degrees)
    """

    id: int = 0
    type_id: int = 0       # Furniture enum from APK map_furniture.json
    center_x: float = 0.0  # World X coordinate
    center_y: float = 0.0  # World Y coordinate
    width: float = 0.0     # Object width in grid units
    height: float = 0.0    # Object height in grid units
    angle: float = 0.0     # Rotation in degrees

    # Full furniture type enum from APK map_furniture.json
    TYPE_NAMES: ClassVar[dict[int, str]] = {
        0: "Placeholder",
        1: "Single Bed",
        2: "Double Bed",
        3: "Baby Bed",
        4: "Dining Table",
        5: "Round Table",
        6: "Tea Table",
        7: "Round Tea Table",
        8: "TV Stand",
        9: "Bedside Table",
        10: "Locker",
        11: "Wardrobe",
        12: "Shoe Cabinet",
        13: "Armchair",
        14: "Sofa",
        15: "L-Shaped Sofa",
        16: "Lazy Chair",
        17: "Chair",
        18: "Bar Chair",
        19: "Cat Toilet",
        20: "Pet Feeder",
        21: "Pet House",
        22: "Washing Machine",
        23: "Refrigerator",
        24: "Air Conditioner",
        25: "Fan",
        26: "Potted Plant",
        27: "Floor Mirror",
        28: "Toilet",
        29: "Piano",
        30: "U-Shaped Sofa",
        31: "Desk",
        32: "Grand Piano",
        33: "Washbasin",
        34: "Stove",
        75: "Cat House",
        76: "Dog House",
        77: "Round Placeholder",
        78: "Weighing Scale",
    }

    @property
    def display_name(self) -> str:
        """Return human-readable name for the obstacle type."""
        return self.TYPE_NAMES.get(self.type_id, f"Object {self.type_id}")

    def to_grid_coords(self, origin_x: int, origin_y: int) -> tuple[float, float]:
        """Convert world coordinates to grid pixel coordinates.

        Same transform as dock/robot: pixel = raw - origin.
        """
        return (self.center_x - origin_x, self.center_y - origin_y)


def _to_float32(val: Any) -> float | None:
    """Convert a protobuf value to float32.

    blackboxprotobuf may return fixed32 fields as either:
      - Python float (if it detects wire type 5 as float)
      - Python int (raw uint32 bit pattern)
    Handle both cases.
    """
    if isinstance(val, float):
        return val
    if isinstance(val, int):
        try:
            return struct.unpack("f", struct.pack("I", val & 0xFFFFFFFF))[0]
        except struct.error:
            return None
    return None


def _parse_obstacles(field32: dict) -> list[ObstacleInfo]:
    """Parse obstacle/furniture annotations from bbp-decoded field 2.32.

    Args:
        field32: The decoded dict from map payload field "32".

    Returns:
        List of ObstacleInfo objects. Skips items that fail to parse.
    """
    items = field32.get("1", [])
    if isinstance(items, dict):
        items = [items]

    obstacles: list[ObstacleInfo] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        try:
            pos = item.get("3", {})
            center = pos.get("1", {}) if isinstance(pos, dict) else {}

            cx = _to_float32(center.get("1")) if isinstance(center, dict) else None
            cy = _to_float32(center.get("2")) if isinstance(center, dict) else None
            w = _to_float32(pos.get("2")) if isinstance(pos, dict) else None
            h = _to_float32(pos.get("3")) if isinstance(pos, dict) else None
            angle = _to_float32(item.get("4"))

            obstacles.append(ObstacleInfo(
                id=int(item.get("1", 0)),
                type_id=int(item.get("2", 0)),
                center_x=cx or 0.0,
                center_y=cy or 0.0,
                width=w or 0.0,
                height=h or 0.0,
                angle=angle or 0.0,
            ))
        except (ValueError, TypeError, AttributeError):
            continue
    return obstacles


@dataclass
class MapData:
    """Map data from get_map response."""

    width: int = 0
    height: int = 0
    resolution: int = 0
    rooms: list[RoomInfo] = field(default_factory=list)
    compressed_map: bytes = b""
    area: int = 0
    created_at: int = 0
    dock_x: float | None = None  # dock position in grid coordinates
    dock_y: float | None = None
    origin_x: int = 0  # x pixel offset from field 2.6.3
    origin_y: int = 0  # y pixel offset from field 2.6.1
    obstacles: list[ObstacleInfo] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_response(
        cls, decoded: dict[str, Any], product_key: str | None = None,
    ) -> MapData:
        """Parse map data from a get_map field5 response.

        Args:
            decoded: bbp-decoded map response payload.
            product_key: Connected device's product_key. Selects the
                ROOM_TYPE → display-name mapping (Flow 1 vs Flow 2).
        """
        payload = decoded.get("2", {})
        if not payload:
            return cls()

        type_names = get_room_type_names(product_key)

        rooms = []
        room_list = payload.get("12", [])
        if isinstance(room_list, dict):
            room_list = [room_list]
        for room in room_list:
            if isinstance(room, dict):
                name_raw = room.get("3", b"")
                if isinstance(name_raw, bytes):
                    name = name_raw.decode("utf-8", errors="replace")
                elif isinstance(name_raw, str):
                    # blackboxprotobuf sometimes returns "b'...'" strings
                    name = name_raw
                    if name.startswith("b'") and name.endswith("'"):
                        name = name[2:-1]
                else:
                    name = str(name_raw)
                rooms.append(RoomInfo(
                    room_id=int(room.get("1", 0)),
                    name=name,
                    room_sub_type=int(room.get("2", 0)),
                    category=int(room.get("4", 0)),
                    instance_index=int(room.get("8", 0)),
                    ROOM_TYPE_NAMES=type_names,
                ))

        compressed = payload.get("17", b"")
        if isinstance(compressed, str):
            compressed = compressed.encode("latin-1")

        resolution = int(payload.get("3", 0))

        # Extract origin offsets from field 6 (coordinate transform).
        # Field 6: {1: origin_y, 2: ?, 3: origin_x, 4: resolution}
        # Positions are in grid-offset units: pixel = raw - origin
        origin_x = 0
        origin_y = 0
        field6 = payload.get("6")
        if isinstance(field6, dict):
            try:
                origin_x = int(field6.get("3", 0))
            except (ValueError, TypeError):
                pass
            try:
                origin_y = int(field6.get("1", 0))
            except (ValueError, TypeError):
                pass

        # Parse dock position from field 8 (dock/charging station location).
        # Field 8 structure: {1: {1: x_dm, 2: y_dm}, 2: heading_rad}
        # Coordinates are in decimeters (same as display_map field 5).
        # Matches display_map field 5 (confirmed via live capture cross-reference).
        # Pixel transform: px = (x_dm * 10) / cm_per_pixel - origin
        dock_x = None
        dock_y = None
        field8 = payload.get("8")
        if isinstance(field8, dict) and resolution > 0:
            pos = field8.get("1")
            if isinstance(pos, dict) and "1" in pos and "2" in pos:
                try:
                    x_dm = _to_float32(pos["1"])
                    y_dm = _to_float32(pos["2"])
                    if x_dm is not None and y_dm is not None:
                        dock_x = x_dm - origin_x
                        dock_y = y_dm - origin_y
                except (struct.error, OverflowError, ValueError, TypeError):
                    pass

        # Parse obstacle/furniture annotations from field 32 (MapFurnitureInfoList)
        obstacles: list[ObstacleInfo] = []
        field32 = payload.get("32")
        if isinstance(field32, dict):
            obstacles = _parse_obstacles(field32)

        return cls(
            width=int(payload.get("4", 0)),
            height=int(payload.get("5", 0)),
            resolution=resolution,
            rooms=rooms,
            compressed_map=compressed if isinstance(compressed, bytes) else b"",
            area=int(payload.get("33", 0)),
            created_at=int(payload.get("34", 0)),
            dock_x=dock_x,
            dock_y=dock_y,
            origin_x=origin_x,
            origin_y=origin_y,
            obstacles=obstacles,
            raw=payload,
        )


@dataclass
class MapDisplayData:
    """Real-time robot position from map/display_map broadcasts.

    Sent every ~1.5s during active cleaning. Contains robot position in cm,
    heading in radians, and a small cleaned-area grid overlay (NOT the full
    house map — that comes from get_map).

    Validated field layout (live capture 2026-02-28, 13 broadcasts):
      field 1.1: {1: x_cm, 2: y_cm} — robot position as float32 centimeters
      field 1.2: heading as float32 radians
      field 5: dock/reference position (constant, same format)
      field 7: cleaned-area grid {1: width, 2: height, 3: compressed_bytes}
      field 10: timestamp in milliseconds since epoch
      field 12: active room list
    """

    robot_x: float = 0.0  # decimeters, world coordinates
    robot_y: float = 0.0  # decimeters, world coordinates
    robot_heading: float = 0.0  # degrees (converted from radians for renderer)
    timestamp: int = 0  # milliseconds since epoch (field 10)
    # Dock/reference position from field 5 (same coordinate system as robot)
    dock_ref_x: float = 0.0
    dock_ref_y: float = 0.0

    def to_grid_coords(
        self, resolution: int, origin_x: int, origin_y: int,
    ) -> tuple[float, float] | None:
        """Convert world-coordinate position (dm) to grid pixel coordinates.

        display_map positions are in decimeters (validated via live capture).
        Same coordinate system as get_map field 8 (dock position).
          pixel = (x_dm * 10) / cm_per_pixel - origin_offset

        Args:
            resolution: Map resolution in mm/pixel (e.g. 60).
            origin_x: X pixel offset (MapData.origin_x, from field 2.6.3).
            origin_y: Y pixel offset (MapData.origin_y, from field 2.6.1).

        Returns:
            (pixel_x, pixel_y) tuple, or None if no valid position.
        """
        if self.robot_x == 0.0 and self.robot_y == 0.0:
            return None
        if resolution <= 0:
            return None
        # Positions are in grid-offset units: pixel = raw - origin
        px = self.robot_x - origin_x
        py = self.robot_y - origin_y
        return (px, py)

    @classmethod
    def from_broadcast(cls, decoded: dict[str, Any]) -> MapDisplayData:
        """Parse display_map broadcast payload."""
        import math

        result = cls()

        # Robot position — field 1.1 = {1: x_cm, 2: y_cm}, field 1.2 = heading_rad
        field1 = decoded.get("1", {})
        if isinstance(field1, dict):
            pos = field1.get("1", {})
            if isinstance(pos, dict):
                x_f = _to_float32(pos.get("1"))
                if x_f is not None and math.isfinite(x_f):
                    result.robot_x = x_f
                y_f = _to_float32(pos.get("2"))
                if y_f is not None and math.isfinite(y_f):
                    result.robot_y = y_f

            heading_raw = field1.get("2")
            if heading_raw is not None:
                h_f = _to_float32(heading_raw)
                if h_f is not None and math.isfinite(h_f):
                    result.robot_heading = math.degrees(h_f)

        # Dock/reference position — field 5 (same format as field 1)
        field5 = decoded.get("5", {})
        if isinstance(field5, dict):
            pos5 = field5.get("1", {})
            if isinstance(pos5, dict):
                dx = _to_float32(pos5.get("1"))
                if dx is not None and math.isfinite(dx):
                    result.dock_ref_x = dx
                dy = _to_float32(pos5.get("2"))
                if dy is not None and math.isfinite(dy):
                    result.dock_ref_y = dy

        # Timestamp — field 10 (milliseconds since epoch)
        if "10" in decoded:
            try:
                result.timestamp = int(decoded["10"])
            except (ValueError, TypeError):
                pass

        return result


@dataclass
class Position:
    """Robot position from map/display_map."""

    x: float = 0.0
    y: float = 0.0
    heading: float = 0.0


@dataclass
class CommandResponse:
    """Response from a command sent to the robot."""

    result_code: int = 0
    data: dict[str, Any] = field(default_factory=dict)
    raw_payload: bytes = b""

    @property
    def success(self) -> bool:
        return self.result_code == CommandResult.SUCCESS

    @property
    def not_applicable(self) -> bool:
        return self.result_code == CommandResult.NOT_APPLICABLE


@dataclass
class NarwalState:
    """Complete state of a Narwal vacuum.

    Updated incrementally as different topic messages arrive.
    """

    # Core status
    working_status: WorkingStatus = WorkingStatus.UNKNOWN
    battery_level: int = 0  # real-time SOC from field 2 (float32)
    battery_health: int = 0  # static design capacity from field 38 (always 100)
    firmware_version: str = ""
    firmware_target: str = ""

    # Current clean settings (Flow 2 — live-broadcast in robot_base_status).
    # 0 means "not yet observed" (the robot uses 1-indexed values).
    #   field 26 = suction (1=Quiet, 2=Standard, 3=Strong, 4=Super powerful)
    #   field 29 = mop humidity (1=Slightly dry, 2=Standard, 3=Slightly wet)
    fan_level_raw: int = 0
    mop_humidity_raw: int = 0

    # Station / consumables. Field 35 is dust-bag remaining capacity as
    # an IEEE 754 float32 percentage (e.g. 1117188891 -> 75.47%). Field
    # 41 is broadcast as 100 on Flow 2 even when the app shows the dust
    # bag below 100%, so it is not the dust-bag health value.
    # Other tank/solution levels (clean water, dirty water, cleaning
    # solution, mop pad wear) are not yet mapped — most appear constant
    # at 1 (=OK) until a fault occurs.
    dust_bag_health: float = 0.0

    # Active fault / error. The robot reports a structured error in
    # robot_base_status field 48.1.2 — empty `{}` when there is no
    # active error, or `{1: severity, 2: code, 3: localized_message}`
    # when a fault halts the current task. The message is broadcast in
    # whatever locale the robot's firmware was set to (Chinese on the
    # Flow 2 hardware we tested), so consumers should prefer the
    # numeric code for logic and use the message for display.
    error_code: int = 0
    error_severity: int = 0
    error_message: str = ""

    # Station activity flags. Field 48.1 is a (possibly-repeated) list
    # of currently-active dock tasks. Each entry uses an empty marker
    # sub-field to identify the task type. Sub-keys verified by capture:
    #   .10 = dust-bag drying (NOT dust emptying — earlier guess)
    #   .13 = mop drying
    #   .14 = dust-cabinet disinfection
    # Entries without a `1` field are running; `1: 1` marks paused.
    # WorkingStatus 17 / 19 also indicate mop-drying phases when the
    # robot itself is the actor — see NarwalStationActivitySensor.
    station_dust_bag_drying: bool = False
    station_mop_drying: bool = False
    station_dust_disinfecting: bool = False
    # Kept for backwards compatibility while sensors transition. Always
    # False under the corrected mapping — real "dust emptying" sub-key
    # has not yet been observed in capture.
    station_dust_emptying: bool = False

    # Dust-bag drying timer. During manual bag drying the station marker
    # f48.10 is present, and ws.12/ws.13 carry elapsed/target seconds
    # (observed target 18000 = 5 h). ws.12 is also cleaning elapsed time,
    # so only treat it as bag-drying progress while f48.10 is active.
    dust_bag_drying_elapsed: int = 0
    dust_bag_drying_target: int = 0

    # Disinfection timer. ws.10 = elapsed seconds, ws.11 = target
    # seconds (constant 2700 = 45 min in observed firmware). Both 0
    # when disinfection is not running. Earlier we considered these
    # generic dock-activity fields — they're disinfection-specific:
    # ws.10/ws.11 vanish from the working_status broadcast as soon as
    # the disinfection cycle ends, even while dust-bag drying is still
    # active.
    dust_disinfection_elapsed: int = 0
    dust_disinfection_target: int = 0

    # Device identity
    device_info: DeviceInfo | None = None

    # Session
    session_id: str = ""
    timestamp: int = 0

    # Position (from map data)
    position: Position | None = None

    # Cleaning stats. Two separate sources:
    #   * Flow 1: working_status field 13 in cm² (legacy upstream code).
    #   * Flow 2: working_status fields 1 and 2 carry float32 progress % and
    #     cleaned-area m² (live captures). Prefer the Flow 2 fields when
    #     populated; fall back to the legacy cm² value otherwise. Field 13
    #     is a constant (18000) on Flow 2 and never the actual area.
    cleaning_area: int = 0  # legacy: working_status.13 in cm² (Flow 1)
    cleaning_area_m2: float = 0.0  # live: working_status.2 as float32 m² (Flow 2)
    cleaning_progress_pct: float = 0.0  # live: working_status.1 as float32 % (Flow 2)
    cleaning_time: int = 0  # seconds

    # Rooms reported as completed within the active clean.
    # Derived from working_status.5 — each entry that gains sub-field
    # 4 = 1 has been finished. Empty list when not cleaning or all
    # rooms still pending.
    rooms_completed: list[int] = field(default_factory=list)

    # Mop-drying timer (Flow 2). Live-confirmed by toggling between
    # drying modes:
    #   ws.8 = elapsed seconds since the cycle started
    #   ws.9 = target total seconds for the selected mode
    #     - 12600 (3.5 h) for default / smart / strong
    #     - 18000 (5 h)   for silent
    # Switching modes mid-cycle rescales ws.8 so the percent-complete
    # stays consistent. Both fields drop to 0 once drying stops.
    mop_drying_elapsed: int = 0
    mop_drying_target: int = 0

    # User-action prompt (Flow 2). When the robot needs the user to
    # do something physical (carry me to dock, refill the tank, etc.)
    # it broadcasts a structured prompt and starts a countdown. Empty
    # / 0 when nothing is required:
    #   user_action_type    = base.3.16 (2=fill tank, 3=return after
    #                         clean, 4=return before clean — observed)
    #   user_action_elapsed = ws.22.1 — seconds the user has been
    #                         asked already
    #   user_action_target  = ws.22.2 — timeout in seconds (600 / 3600
    #                         observed)
    user_action_type: int = 0
    user_action_elapsed: int = 0
    user_action_target: int = 0

    # Map-identity signature (Flow 2). Multi-map houses switch
    # base.30 / base.44 between maps; treat the pair as an opaque
    # key — when it changes the active map has changed.
    map_signature: tuple[int | None, int | None] = (None, None)

    # Map
    map_data: MapData | None = None
    map_display_data: MapDisplayData | None = None

    # Vision obstacles (camera-detected transient objects during cleaning)
    # Download/upgrade status
    download_status: int = 0
    upgrade_status_code: int = 0

    # Pause overlay (field 3 sub-field 2 = 1 means paused)
    is_paused: bool = False

    # Dock sub-state (field 3 sub-field 10: 1=docked, 2=docking in progress)
    dock_sub_state: int = 0

    # Returning flag (field 3 sub-field 7: 1=returning to dock)
    # Confirmed via live test: appears when robot is navigating back to dock
    is_returning_to_dock: bool = False

    # Dock activity (field 3 sub-field 12: 2/6 observed when docked)
    dock_activity: int = 0

    # Dock presence (field 3 sub-field 3)
    # Values observed: 1=on dock, 2=off dock, 6=on dock (charged idle)
    dock_presence: int = 0

    # Dock indicator from field 11 (top-level base_status field)
    # Validated via dock_research.py guided test (5 captures):
    #   2 = on dock (all 3 on-dock captures)
    #   1 = off dock (both off-dock captures)
    # Perfect dock correlation — primary STANDBY dock signal.
    dock_field11: int = 0

    # Dock indicator from field 47 (top-level base_status field)
    # Validated via dock_research.py guided test (5 captures):
    #   3 = on dock (all 3 on-dock captures)
    #   2 = off dock (both off-dock captures)
    # Secondary confirmation signal.
    dock_field47: int = 0

    # Raw data for fields we haven't fully decoded yet
    raw_base_status: dict[str, Any] = field(default_factory=dict)
    raw_working_status: dict[str, Any] = field(default_factory=dict)

    # Forward path the robot is about to drive — list of (x, y) world
    # coordinates decoded from status/point_navi_plan_traj. Empty list
    # when the robot is idle or no path is currently planned.
    plan_trajectory: list[tuple[float, float]] = field(default_factory=list)
    # Wall-clock timestamp of the most recent report/clean_report event
    # (empty-payload broadcast that fires once at end of a clean cycle).
    last_clean_report_ts: float = 0.0

    @property
    def is_cleaning(self) -> bool:
        """True when actively cleaning (not paused, not returning to dock).

        Flow 2 firmware variants do not all report the same
        robot_base_status.3.1 value while vacuuming. If the base status is
        unmapped but the robot is off the dock and working_status carries
        clean-session fields, infer cleaning instead of showing idle.
        """
        explicit_cleaning = self.working_status in (
            WorkingStatus.CLEANING, WorkingStatus.CLEANING_ALT,
        )
        inferred_cleaning = self._looks_like_active_cleaning_session()
        return (
            (explicit_cleaning or inferred_cleaning)
            and not self.is_paused
            and not self.is_returning_to_dock
        )

    def _looks_like_active_cleaning_session(self) -> bool:
        """Infer an active clean from session fields when status is unmapped."""
        if self.working_status in (
            WorkingStatus.CLEANING, WorkingStatus.CLEANING_ALT,
            WorkingStatus.DOCKED, WorkingStatus.CHARGED,
            WorkingStatus.MOP_WASHING, WorkingStatus.MOP_DRYING,
            WorkingStatus.MOP_DRYING_ACTIVE,
        ):
            return False
        if self.dock_sub_state == 1 or self.dock_activity > 0:
            return False
        if self.dock_field11 == 2 or self.dock_field47 == 3:
            return False
        ws = self.raw_working_status
        if not isinstance(ws, dict) or not ws:
            return False
        # Cleaning broadcasts normally include a room queue/current room,
        # and may include progress/area/elapsed. Drying broadcasts have
        # ws.12/ws.13 too, so don't infer from timer fields alone.
        room_queue = ws.get("5")
        has_rooms = bool(room_queue) if isinstance(room_queue, (list, dict)) else False
        return has_rooms or "6" in ws or "1" in ws or "2" in ws

    @property
    def is_docked(self) -> bool:
        """True when on dock: DOCKED(10), CHARGED(14), or dock field signals.

        Dock signals (checked for STANDBY, UNKNOWN, and any unmapped status):
          - dock_sub_state == 1 (field 3.10, confirmed live)
          - dock_activity > 0 (field 3.12, values 2/6 when docked)
          - dock_field11 == 2 (field 11: 2=docked, 1=undocked)
          - dock_field47 == 3 (field 47: 3=docked, 2=undocked)

        Fields 11 and 47 validated via dock_research.py guided test with
        5 captures across on-dock and off-dock states — perfect correlation.

        Dock fields are checked for STANDBY/UNKNOWN and any status where
        cleaning is not active, since the robot can report unmapped states
        (e.g. self-test) while physically docked.
        """
        if self.working_status in (WorkingStatus.DOCKED, WorkingStatus.CHARGED):
            return True
        if self.working_status in (WorkingStatus.CLEANING, WorkingStatus.CLEANING_ALT):
            return False
        # For STANDBY, UNKNOWN, or any other status: check dock field signals
        if self.dock_sub_state == 1:
            return True
        if self.dock_activity > 0:
            return True
        if self.dock_field11 == 2:
            return True
        if self.dock_field47 == 3:
            return True
        return False

    @property
    def is_returning(self) -> bool:
        """True when the robot is actively returning to the dock.

        Live-validated: during return-to-dock, field 3 shows:
          {1=4, 7=1, 10=2} — working_status stays CLEANING(4),
          field 7=1 (returning flag), field 10=2 (docking in progress).

        Requires BOTH field 3.7=1 AND field 3.10=2 to avoid false
        positives — either field alone can be stale during normal
        cleaning (confirmed 2026-03-08: robot cleaning in Pantry
        showed returning=True from a single stale field).

        Only valid while working_status is CLEANING — once the robot
        transitions to STANDBY/DOCKED/CHARGED, it has already docked
        even if field 3.7 is momentarily still set.
        """
        if self.working_status not in (
            WorkingStatus.CLEANING, WorkingStatus.CLEANING_ALT,
        ):
            return False
        return self.is_returning_to_dock and self.dock_sub_state == 2

    def update_from_working_status(self, decoded: dict[str, Any]) -> None:
        """Update state from a decoded working_status message.

        Field semantics (re-verified 2026-05 with full Wohnzimmer-Clean
        capture — earlier mapping had cleaning_time on field 3, which is
        actually the WorkingStatus enum):

        Field 1   = float32 cleaning progress percent
        Field 2   = float32 cleaned area in m²
        Field 3   = WorkingStatus enum (status code, not seconds)
        Field 5   = list of {1: roomId, 2: completed_flag}; flag == 2
                    means the room is done. Earlier code used sub-field
                    4 which never appears in current firmware.
        Field 6   = index of the room currently being cleaned
        Field 12  = elapsed seconds for the current session
        Field 13  = legacy area in cm² (Flow 1 only — constant 18000
                    on Flow 2, ignored)
        Field 15  = 600 during cleaning, purpose uncertain
        """
        self.raw_working_status = decoded
        is_cleaning = self.working_status in (
            WorkingStatus.CLEANING, WorkingStatus.CLEANING_ALT,
        ) or self._looks_like_active_cleaning_session()
        # cleaning_time: field 12 is real elapsed seconds during a clean,
        # but the firmware reuses it as a station-cycle timer during
        # dust-bag drying. Keep Cleaning time at 0 unless actively cleaning.
        if is_cleaning and "12" in decoded:
            try:
                self.cleaning_time = int(decoded["12"])
            except (ValueError, TypeError):
                pass
        elif not is_cleaning:
            self.cleaning_time = 0
        # Flow 2: float32 progress and area encoded as fixed32 ints.
        progress = _to_float32(decoded.get("1"))
        if progress is not None and 0 <= progress <= 200:
            self.cleaning_progress_pct = progress
        area = _to_float32(decoded.get("2"))
        if area is not None and 0 <= area <= 10000:
            self.cleaning_area_m2 = area
        # Track which rooms in the queue have been completed.
        rooms = decoded.get("5")
        completed: list[int] = []
        # Each entry is {1: roomId, 2: completion_flag}. Observed values
        # for flag: missing (queued), 1 (in progress), 2 (done). Earlier
        # code looked at sub-field 4 which was never populated in any
        # capture we have.
        if isinstance(rooms, list):
            for entry in rooms:
                if isinstance(entry, dict) and entry.get("2") == 2:
                    try:
                        completed.append(int(entry.get("1", 0)))
                    except (ValueError, TypeError):
                        pass
        elif isinstance(rooms, dict) and rooms.get("2") == 2:
            try:
                completed.append(int(rooms.get("1", 0)))
            except (ValueError, TypeError):
                pass
        self.rooms_completed = completed
        # Mop-drying timer (Flow 2 hypothesis from live capture).
        try:
            self.mop_drying_elapsed = int(decoded.get("8", 0) or 0)
        except (ValueError, TypeError):
            self.mop_drying_elapsed = 0
        try:
            self.mop_drying_target = int(decoded.get("9", 0) or 0)
        except (ValueError, TypeError):
            self.mop_drying_target = 0
        # Dust-bag drying timer. Uses ws.12/ws.13, but only while the
        # f48.10 marker is active; otherwise those fields have other
        # meanings (notably Cleaning time).
        if self.station_dust_bag_drying and self.is_docked and not is_cleaning:
            try:
                self.dust_bag_drying_elapsed = int(decoded.get("12", 0) or 0)
            except (ValueError, TypeError):
                self.dust_bag_drying_elapsed = 0
            try:
                self.dust_bag_drying_target = int(decoded.get("13", 0) or 0)
            except (ValueError, TypeError):
                self.dust_bag_drying_target = 0
        else:
            self.dust_bag_drying_elapsed = 0
            self.dust_bag_drying_target = 0
        # Disinfection timer (ws.10 elapsed / ws.11 target). The fields
        # are absent from the broadcast when no disinfection cycle is
        # running — `.get("10", 0)` resolves to 0 in that case.
        try:
            self.dust_disinfection_elapsed = int(decoded.get("10", 0) or 0)
        except (ValueError, TypeError):
            self.dust_disinfection_elapsed = 0
        try:
            self.dust_disinfection_target = int(decoded.get("11", 0) or 0)
        except (ValueError, TypeError):
            self.dust_disinfection_target = 0
        # ws.22 = user-action countdown ({1: elapsed, 2: target}). Empty
        # dict when no action is required.
        f22 = decoded.get("22")
        if isinstance(f22, dict) and f22:
            try:
                self.user_action_elapsed = int(f22.get("1", 0) or 0)
            except (ValueError, TypeError):
                self.user_action_elapsed = 0
            try:
                self.user_action_target = int(f22.get("2", 0) or 0)
            except (ValueError, TypeError):
                self.user_action_target = 0
        else:
            self.user_action_elapsed = 0
            self.user_action_target = 0
        if "15" in decoded:
            # Field 15 may be cumulative time; prefer field 3 for current session
            pass

    def update_from_base_status(self, decoded: dict[str, Any]) -> None:
        """Update state from a decoded robot_base_status message.

        Battery (confirmed via 35-min monitor capture):
          Field 2  = real-time battery as IEEE 754 float32
                     (1118175232 → 83.0%, matching app ~84%)
          Field 38 = static battery health (always 100; design capacity)

        Field 3 sub-fields (confirmed via live test):
          3.1  = WorkingStatus enum
          3.2  = 1 means PAUSED
          3.7  = 1 means RETURNING to dock (live-validated)
          3.10 = dock sub-state (1=docked, 2=docking in progress)
          3.12 = dock activity (values 2, 6 observed)

        Dock indicators (validated via dock_research.py, 5 captures):
          Field 11 = 2 when docked, 1 when undocked
          Field 47 = 3 when docked, 2 when undocked

        Note: field 32 mirrors field 3 exactly (redundant).
        """
        self.raw_base_status = decoded
        # Field 11 = dock indicator (2=docked, 1=undocked)
        if "11" in decoded:
            try:
                self.dock_field11 = int(decoded["11"])
            except (ValueError, TypeError):
                self.dock_field11 = 0
        # Field 26 = current suction level (Flow 2 only; live captures from
        # firmware v01.07.19.00 confirm the 1-indexed scale 1=Quiet,
        # 2=Standard, 3=Strong, 4=Super powerful). Not observed on Flow 1
        # — leaves fan_level_raw at 0 there.
        if "26" in decoded:
            try:
                self.fan_level_raw = int(decoded["26"])
            except (ValueError, TypeError):
                self.fan_level_raw = 0
        # Field 29 = current mop humidity (Flow 2). 1=Slightly dry,
        # 2=Standard, 3=Slightly wet (live-confirmed).
        if "29" in decoded:
            try:
                self.mop_humidity_raw = int(decoded["29"])
            except (ValueError, TypeError):
                self.mop_humidity_raw = 0
        # Field 35 = dust bag remaining capacity, 0–100, encoded as float32.
        # Field 41 stays at 100 on Flow 2 even when the app does not.
        if "35" in decoded:
            dust_bag = _to_float32(decoded["35"])
            if dust_bag is not None:
                self.dust_bag_health = round(dust_bag, 1)
        # Field 48.1 carries one or more dock activities. It's a single
        # message during a normal clean, but switches to a repeated list
        # when multiple activities overlap (e.g. mop drying while a
        # dust-bag emptying is queued). Normalize to a list so the
        # parsers below don't need to care.
        f48_1 = decoded.get("48", {}).get("1")
        f48_entries: list[dict[str, Any]] = []
        if isinstance(f48_1, list):
            f48_entries = [e for e in f48_1 if isinstance(e, dict)]
        elif isinstance(f48_1, dict):
            f48_entries = [f48_1]

        # Active error. The robot reports one through two channels:
        #   * 48.1.*.2 = {1: severity, 2: code, 3: localized_message}
        #   * field 1 = {1: code, 2: severity, 3: formatted_message}
        # Field 1 also carries the formatted "错误码:0xCCSSRRXX\n等级:..."
        # banner string. Either or both can be populated; whichever
        # appears first wins. Empty/absent on both = no active error.
        err = next(
            (e["2"] for e in f48_entries
             if isinstance(e.get("2"), dict) and e["2"]),
            None,
        )
        f1 = decoded.get("1")
        if isinstance(err, dict) and err:
            try:
                self.error_severity = int(err.get("1", 0))
            except (ValueError, TypeError):
                self.error_severity = 0
            try:
                self.error_code = int(err.get("2", 0))
            except (ValueError, TypeError):
                self.error_code = 0
            raw_msg = err.get("3", "")
            if isinstance(raw_msg, bytes):
                self.error_message = raw_msg.decode("utf-8", errors="replace")
            else:
                self.error_message = str(raw_msg)
        elif isinstance(f1, dict) and f1:
            # Secondary channel — note the swapped fields: 1 is the code.
            try:
                self.error_code = int(f1.get("1", 0))
            except (ValueError, TypeError):
                self.error_code = 0
            try:
                self.error_severity = int(f1.get("2", 0))
            except (ValueError, TypeError):
                self.error_severity = 0
            raw_msg = f1.get("3", "")
            if isinstance(raw_msg, bytes):
                self.error_message = raw_msg.decode("utf-8", errors="replace")
            else:
                self.error_message = str(raw_msg)
        else:
            self.error_code = 0
            self.error_severity = 0
            self.error_message = ""

        # Station-activity markers within 48.1.*. Each entry carries an
        # empty `{}` sub-field whose key identifies the task type. See
        # the field declarations above for the verified key map.
        self.station_dust_bag_drying = any("10" in e for e in f48_entries)
        self.station_mop_drying = any("13" in e for e in f48_entries)
        self.station_dust_disinfecting = any("14" in e for e in f48_entries)
        # No sub-key for actual dust-bin emptying observed yet — leave
        # the legacy flag wired off.
        self.station_dust_emptying = False
        # Field 47 = dock indicator (3=docked, 2=undocked)
        if "47" in decoded:
            try:
                self.dock_field47 = int(decoded["47"])
            except (ValueError, TypeError):
                self.dock_field47 = 0
        # Field 3 is a nested message: {1: state_int, ...}
        field3 = decoded.get("3")
        if isinstance(field3, dict) and "1" in field3:
            try:
                self.working_status = WorkingStatus(int(field3["1"]))
            except (ValueError, TypeError):
                self.working_status = WorkingStatus.UNKNOWN
            # Sub-field 2 = 1 means paused (overlay on cleaning state)
            self.is_paused = bool(field3.get("2"))
            # Sub-field 7 = 1 means returning to dock (confirmed via live test)
            self.is_returning_to_dock = bool(field3.get("7"))
            # Sub-field 10 = dock sub-state (1=docked, 2=docking in progress)
            try:
                self.dock_sub_state = int(field3.get("10", 0))
            except (ValueError, TypeError):
                self.dock_sub_state = 0
            # Sub-field 12 = dock activity (values 2, 6 observed when docked)
            try:
                self.dock_activity = int(field3.get("12", 0))
            except (ValueError, TypeError):
                self.dock_activity = 0
            # Sub-field 3 = dock presence (1/6=on dock, 2=off dock)
            try:
                self.dock_presence = int(field3.get("3", 0))
            except (ValueError, TypeError):
                self.dock_presence = 0
            # Sub-field 16 = user-action prompt type (Flow 2):
            #   2 = fill water tank / problem solved
            #   3 = bring robot to dock after clean done
            #   4 = bring robot to dock to start clean
            try:
                self.user_action_type = int(field3.get("16", 0) or 0)
            except (ValueError, TypeError):
                self.user_action_type = 0
        else:
            self.user_action_type = 0

        # Map identity (Flow 2). base.30 + base.44 form an opaque
        # signature that flips between saved maps; track them so the
        # coordinator can refresh get_map() when the user switches.
        try:
            sig30 = int(decoded["30"]) if "30" in decoded else None
        except (ValueError, TypeError):
            sig30 = None
        try:
            sig44 = int(decoded["44"]) if "44" in decoded else None
        except (ValueError, TypeError):
            sig44 = None
        self.map_signature = (sig30, sig44)
        if "2" in decoded:
            # Field 2 = real-time battery SOC as float32
            # (e.g. 1118175232 → 83.0%; bbp may return int or float)
            bat = _to_float32(decoded["2"])
            if bat is not None:
                self.battery_level = round(bat)
        if "35" in decoded:
            # Field 35 = dust bag remaining capacity as float32 percentage.
            dust_bag = _to_float32(decoded["35"])
            if dust_bag is not None:
                self.dust_bag_health = round(dust_bag, 1)
        if "38" in decoded:
            # Field 38 = static battery health (always 100, design capacity)
            self.battery_health = int(decoded["38"])
        if "36" in decoded:
            self.timestamp = int(decoded["36"])
        if "13" in decoded:
            raw = decoded["13"]
            if isinstance(raw, bytes):
                self.session_id = raw.decode("utf-8", errors="replace")
            else:
                self.session_id = str(raw)
                if self.session_id.startswith("b'"):
                    self.session_id = self.session_id[2:-1]

    def update_battery_from_base_status(self, decoded: dict[str, Any]) -> None:
        """Update ONLY hardware-sampled fields from a base_status response.

        Used when the robot is not broadcasting (deep sleep on dock).
        In this mode, get_status() returns current battery (hardware counter)
        but stale working_status (firmware cache from last active session).
        We update only the fields we can trust.
        """
        self.raw_base_status = decoded
        if "2" in decoded:
            bat = _to_float32(decoded["2"])
            if bat is not None:
                self.battery_level = round(bat)
        if "35" in decoded:
            dust_bag = _to_float32(decoded["35"])
            if dust_bag is not None:
                self.dust_bag_health = round(dust_bag, 1)
        if "38" in decoded:
            self.battery_health = int(decoded["38"])
        if "36" in decoded:
            self.timestamp = int(decoded["36"])

    def update_from_plan_traj(self, decoded: dict[str, Any]) -> None:
        """Update state from a status/point_navi_plan_traj broadcast.

        Field 1 is a repeated list of {1: x, 2: y} where each coordinate
        is a float32 packed into a fixed32 int (same encoding as the
        battery and area fields elsewhere in the protocol).

        Empty / missing field 1 → robot has no planned path → clear the
        cached trajectory. Bad encodings are dropped silently rather
        than poisoning the whole list.
        """
        points: list[tuple[float, float]] = []
        raw = decoded.get("1")
        if isinstance(raw, list):
            for entry in raw:
                if not isinstance(entry, dict):
                    continue
                x = _to_float32(entry.get("1"))
                y = _to_float32(entry.get("2"))
                if x is not None and y is not None:
                    points.append((x, y))
        self.plan_trajectory = points

    def update_from_upgrade_status(self, decoded: dict[str, Any]) -> None:
        """Update state from a decoded upgrade_status message."""
        if "7" in decoded:
            raw = decoded["7"]
            if isinstance(raw, bytes):
                self.firmware_version = raw.decode("utf-8", errors="replace")
            else:
                self.firmware_version = str(raw)
                if self.firmware_version.startswith("b'"):
                    self.firmware_version = self.firmware_version[2:-1]
        if "8" in decoded:
            raw = decoded["8"]
            if isinstance(raw, bytes):
                self.firmware_target = raw.decode("utf-8", errors="replace")
            else:
                self.firmware_target = str(raw)
                if self.firmware_target.startswith("b'"):
                    self.firmware_target = self.firmware_target[2:-1]
        if "4" in decoded:
            self.upgrade_status_code = int(decoded["4"])

    def update_from_download_status(self, decoded: dict[str, Any]) -> None:
        """Update state from a decoded download_status message."""
        if "1" in decoded:
            self.download_status = int(decoded["1"])
