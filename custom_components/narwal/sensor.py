"""Sensor entities for Narwal vacuum."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import PERCENTAGE, EntityCategory, UnitOfArea, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .narwal_client import NarwalState, WorkingStatus

from . import NarwalConfigEntry
from .coordinator import NarwalCoordinator
from .entity import NarwalEntity


@dataclass(frozen=True, kw_only=True)
class NarwalSensorEntityDescription(SensorEntityDescription):
    """Describes a Narwal sensor entity."""

    value_fn: Callable[[NarwalState], float | str | None]


SENSOR_DESCRIPTIONS: tuple[NarwalSensorEntityDescription, ...] = (
    NarwalSensorEntityDescription(
        key="battery",
        device_class=SensorDeviceClass.BATTERY,
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        # battery_level comes from field 2 (real-time SOC as float32)
        value_fn=lambda state: state.battery_level if state.battery_level > 0 else None,
    ),
    NarwalSensorEntityDescription(
        key="cleaning_area",
        translation_key="cleaning_area",
        native_unit_of_measurement=UnitOfArea.SQUARE_METERS,
        state_class=SensorStateClass.MEASUREMENT,
        # Float32 m² from working_status.2 (Flow 2). Reports the last
        # measured value — sticks at the previous clean's total when
        # idle, resets when a new clean starts. The legacy ws.13 cm²
        # fallback was removed: it's a stuck 18000 constant on Flow 2
        # and produced confusing 1.8 m² values.
        value_fn=lambda state: round(state.cleaning_area_m2, 2),
    ),
    NarwalSensorEntityDescription(
        key="cleaning_progress",
        translation_key="cleaning_progress",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        # Float32 % from working_status.1 (Flow 2). 0 when idle.
        value_fn=lambda state: round(state.cleaning_progress_pct, 1),
    ),
    NarwalSensorEntityDescription(
        key="mop_drying_progress",
        translation_key="mop_drying_progress",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        # ws.8 elapsed / ws.9 target. 0 when no cycle is running.
        value_fn=lambda state: (
            round(state.mop_drying_elapsed * 100 / state.mop_drying_target, 1)
            if state.mop_drying_target > 0 else 0
        ),
    ),
    NarwalSensorEntityDescription(
        key="user_action_seconds_left",
        translation_key="user_action_seconds_left",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.SECONDS,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        # Mirrors `remaining_s` from binary_sensor.user_action_required
        # so it can be graphed / used in automations directly. 0 when
        # no action is required.
        value_fn=lambda state: (
            max(state.user_action_target - state.user_action_elapsed, 0)
            if state.user_action_type != 0 and state.user_action_target > 0
            else 0
        ),
    ),
    NarwalSensorEntityDescription(
        key="cleaning_time",
        translation_key="cleaning_time",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.SECONDS,
        state_class=SensorStateClass.MEASUREMENT,
        # working_status.3 — session elapsed seconds. 0 when idle.
        value_fn=lambda state: state.cleaning_time,
    ),
    NarwalSensorEntityDescription(
        key="firmware_version",
        translation_key="firmware_version",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda state: state.firmware_version or None,
    ),
    NarwalSensorEntityDescription(
        key="dust_bag_health",
        translation_key="dust_bag_health",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        # robot_base_status field 41: 100 = bag healthy/empty, drops as full.
        value_fn=lambda state: state.dust_bag_health or None,
    ),
    NarwalSensorEntityDescription(
        key="error_code",
        translation_key="error_code",
        entity_category=EntityCategory.DIAGNOSTIC,
        # Numeric error code; 0 when no fault is active. Codes are
        # packed as 0xCC SS RR XX (category, sub, reserved, specific).
        value_fn=lambda state: state.error_code,
    ),
    NarwalSensorEntityDescription(
        key="error_message",
        translation_key="error_message",
        entity_category=EntityCategory.DIAGNOSTIC,
        # Localized fault message; "" when no fault is active.
        # Locale follows the robot's firmware setting (Chinese on the
        # Flow 2 we tested) — prefer error_code for automations.
        value_fn=lambda state: state.error_message or "",
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: NarwalConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up Narwal sensor entities."""
    coordinator = entry.runtime_data
    entities: list[SensorEntity] = [
        NarwalSensor(coordinator, description) for description in SENSOR_DESCRIPTIONS
    ]
    entities.append(NarwalChargingStateSensor(coordinator))
    entities.append(NarwalStationActivitySensor(coordinator))
    async_add_entities(entities)


class NarwalSensor(NarwalEntity, SensorEntity):
    """A Narwal sensor entity."""

    entity_description: NarwalSensorEntityDescription

    def __init__(
        self,
        coordinator: NarwalCoordinator,
        description: NarwalSensorEntityDescription,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self.entity_description = description
        device_id = coordinator.config_entry.data["device_id"]
        self._attr_unique_id = f"{device_id}_{description.key}"

    @property
    def native_value(self) -> float | str | None:
        """Return the sensor value."""
        state = self.coordinator.data
        if state is None:
            return None
        return self.entity_description.value_fn(state)


class NarwalChargingStateSensor(NarwalEntity, SensorEntity):
    """Sensor showing charging state: Charging, Fully Charged, or unavailable."""

    _attr_device_class = SensorDeviceClass.ENUM
    _attr_translation_key = "charging_state"
    _attr_options = ["charging", "fully_charged", "not_charging"]

    def __init__(self, coordinator: NarwalCoordinator) -> None:
        """Initialize the charging state sensor."""
        super().__init__(coordinator)
        device_id = coordinator.config_entry.data["device_id"]
        self._attr_unique_id = f"{device_id}_charging_state"

    @property
    def native_value(self) -> str | None:
        """Return charging state.

        Returns None (unavailable) when not docked.
        """
        state = self.coordinator.data
        if state is None:
            return None
        if not state.is_docked:
            return "not_charging"
        if state.battery_level >= 100:
            return "fully_charged"
        return "charging"

    @property
    def icon(self) -> str:
        """Return icon based on charging state."""
        if self.native_value == "fully_charged":
            return "mdi:battery"
        if self.native_value == "charging":
            return "mdi:battery-charging"
        if self.native_value == "not_charging":
            return "mdi:battery-off-outline"
        return "mdi:battery-unknown"


class NarwalStationActivitySensor(NarwalEntity, SensorEntity):
    """Reports what the dock station is currently doing.

    Derived from the robot's working_status. Distinct from the vacuum's
    own activity because the station can run mop wash/dry cycles while
    the robot itself is parked on it.
    """

    _attr_device_class = SensorDeviceClass.ENUM
    _attr_translation_key = "station_activity"
    _attr_options = ["idle", "mop_washing", "mop_drying", "dust_emptying"]
    _attr_icon = "mdi:dishwasher"

    def __init__(self, coordinator: NarwalCoordinator) -> None:
        super().__init__(coordinator)
        device_id = coordinator.config_entry.data["device_id"]
        self._attr_unique_id = f"{device_id}_station_activity"

    @property
    def native_value(self) -> str | None:
        state = self.coordinator.data
        if state is None:
            return None
        # Mop wash takes priority — the robot is physically engaged
        # with the basin so other activities can't really overlap.
        if state.working_status == WorkingStatus.MOP_WASHING:
            return "mop_washing"
        if (
            state.station_mop_drying
            or state.working_status in (
                WorkingStatus.MOP_DRYING, WorkingStatus.MOP_DRYING_ACTIVE,
            )
        ):
            return "mop_drying"
        if state.station_dust_emptying:
            return "dust_emptying"
        return "idle"
