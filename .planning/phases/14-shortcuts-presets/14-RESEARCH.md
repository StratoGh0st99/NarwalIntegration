# Phase 14: Shortcuts & Presets - Research

**Researched:** 2026-04-01
**Status:** ARCHIVED (2026-04-01) — Probe confirmed shortcuts are cloud-only
**Domain:** Narwal WebSocket protocol (shortcut topics), HA SelectEntity platform, NrRobotShortcutModel schema
**Confidence:** HIGH — Probe validated: no local WS shortcut topics exist. All speculative topics timed out. Shortcuts are cloud-managed via Alibaba Alink IoT REST APIs.

## Probe Results (2026-04-01)

| Topic | Result |
|-------|--------|
| `config/get` | Responded — config/timezone/settings, no shortcut data |
| `common/get_feature_list` | Responded — feature flags only |
| `clean/cur_plan/get` | Responded — current cleaning plan (per-room params) |
| `clean/plan/get` | Responded — empty ack |
| `shortcut/get` | Timeout — topic doesn't exist |
| `clean/shortcut/get` | Timeout — topic doesn't exist |
| `robot/shortcut/get` | Timeout — topic doesn't exist |
| Broadcast listener (30s) | No shortcut-related broadcasts |

**Conclusion:** `NrRobotShortcutListGetRequester` uses cloud REST, not local WS. Shortcuts exist in the Narwal app but are routed through Alibaba Alink IoT cloud. Room-specific cleaning via Phase 9 (`vacuum.clean_area`) already covers the functional use case.

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- **D-01:** Execute robot-stored shortcuts, not HA-side presets. The Narwal app stores "Shutcut" entries on the robot — we discover and execute those.
- **D-02:** APK RE is the first dependency. Must find the WebSocket topic(s) for shortcut list retrieval and execution from @northwestsupra's APK decompilation (v2.6.81, includes .proto files). APK classes to find: `NrRobotShortcutListGetRequester`, `NrRobotShortcutListSetRequester`.
- **D-03:** Probe robot with discovered topics to confirm payload format and response schema before building HA entities. APK is from a different model — topic names may not match, so probing is essential (not just nice-to-have).
- **D-04:** Select entity dropdown listing all shortcuts reported by the robot. Entity options update automatically as shortcuts are added/removed in the Narwal app.
- **D-05:** Custom service (`narwal.execute_shortcut`) to trigger the currently selected shortcut (or accept a shortcut ID/name parameter for automation use).
- **D-06:** No button entities per shortcut — the select + service pattern keeps entity count stable.
- **D-07:** Fetch shortcut list on integration setup and refresh periodically via the coordinator poll cycle (60s fallback).
- **D-08:** Shortcut list changes in the Narwal app automatically reflect in HA within one poll cycle — no manual reload needed.

### Claude's Discretion
- Exact select entity naming and icon
- How to handle empty shortcut list (no shortcuts configured in app)
- Whether to cache shortcut list in coordinator data or fetch separately
- Error handling for shortcut execution failures
- Whether shortcut parameters (rooms, fan, mop) are displayed as entity attributes

### Deferred Ideas (OUT OF SCOPE)
- HA-side preset builder (custom cleaning configs without robot shortcuts)
- Editing/creating shortcuts from HA (set requester) — this phase is read+execute only
- Scheduled shortcut execution (timing) — HA automations handle scheduling natively
</user_constraints>

---

## Summary

The Narwal app's "Shutcut" feature stores named cleaning presets. APK reverse engineering reveals a `NrRobotShortcutModel` JSON schema with fields `robot_shortcuts` (list) where each entry has `shortcut_topic`, `shortcut_command_list`, `shortcut_json`, and `shortcut_param`. The `shortcut_topic` field strongly suggests each shortcut stores its own WebSocket topic path — meaning execution is local WS even if the list retrieval may go through cloud.

The critical open question is **how the shortcut list is retrieved**. The `NrRobotShortcutListGetRequester` class sits in `nr_networking/network/device/requester/` — the same "requester" pattern used for cloud REST API calls (confirmed by `sendGetRequester url =` log lines in libapp strings). There is also a cloud endpoint `/iot-platform/device-shadow-server/v1/get` that the app uses. However, a `_loadLocalShortcutData` log line shows shortcuts are cached in app-local storage, and `shortcutAPPDataSync` syncs `robotShortcuts.length` from robot data. This is ambiguous — the list may come from cloud device shadow, local app cache, or a WS topic not yet found.

**Phase 14 requires a two-plan structure:** Plan 01 = probe robot to discover the shortcut retrieval topic (possibly `config/get` WS or a custom shortcut topic) and validate execution; Plan 02 = implement select entity + service + tests once topics are confirmed.

**Primary recommendation:** Build a targeted probe script (`tools/probe_shortcuts.py`) that tries `config/get` WS topic and any shortcut-specific candidates, captures responses, and identifies how shortcut data flows. Only then implement HA entities.

---

## Standard Stack

### Core (already in use — no new dependencies)
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `websockets` | >=12.0,<14.0 | WebSocket transport | Already used for all robot commands |
| `blackboxprotobuf` | latest (bbpb>=1.4.0) | Protobuf encode/decode | Already used in `_build_room_clean_payload` |

### HA Platform (new for this phase)
| Component | Version | Purpose | Why Standard |
|-----------|---------|---------|--------------|
| `homeassistant.components.select.SelectEntity` | 2026.x | Dropdown entity for shortcut list | The canonical HA entity for "select one of N options" use case |

### No New Python Packages Required
All dependencies already in pyproject.toml. No new `pip install` needed.

---

## Architecture Patterns

### Recommended File Layout
```
custom_components/narwal/
├── select.py          # New — NarwalShortcutSelectEntity + async_setup_entry
├── __init__.py        # Add Platform.SELECT to PLATFORMS list
├── const.py           # Add TOPIC_CMD_GET_SHORTCUTS (discovered via probe)
└── narwal_client/
    ├── client.py      # Add get_shortcuts() + execute_shortcut(topic, payload)
    └── models.py      # Add ShortcutInfo dataclass + shortcuts field to NarwalState
```

Also:
```
tools/
└── probe_shortcuts.py   # Plan 01 deliverable — discovers shortcut topics
tests/
└── test_shortcuts.py    # Plan 02 deliverable — unit tests for select entity + service
```

### Pattern 1: SelectEntity with Coordinator Data
**What:** SelectEntity reads options and current_option from `coordinator.data` (NarwalState), updated via normal coordinator push/poll cycle.
**When to use:** When option list changes rarely (only when user modifies shortcuts in app). The 60s poll fallback is acceptable latency.

```python
# Source: https://developers.home-assistant.io/docs/core/entity/select/
from homeassistant.components.select import SelectEntity
from .entity import NarwalEntity

class NarwalShortcutSelectEntity(NarwalEntity, SelectEntity):
    _attr_icon = "mdi:play-box-multiple"
    _attr_translation_key = "shortcut"

    def __init__(self, coordinator):
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.config_entry.data['device_id']}_shortcut"
        self._attr_name = "Shortcut"

    @property
    def options(self) -> list[str]:
        shortcuts = self.coordinator.data.shortcuts or []
        return [s.name for s in shortcuts]

    @property
    def current_option(self) -> str | None:
        # No persistent selection state — return None or last executed
        return self._current_option

    async def async_select_option(self, option: str) -> None:
        """Select a shortcut (does NOT execute it — use narwal.execute_shortcut)."""
        self._current_option = option
        self.async_write_ha_state()
```

### Pattern 2: ShortcutInfo Dataclass in Models
**What:** A lightweight dataclass stored in NarwalState.shortcuts list.
**When to use:** Follows the existing RoomInfo pattern in models.py.

```python
# In narwal_client/models.py — mirrors RoomInfo pattern
from dataclasses import dataclass, field

@dataclass
class ShortcutInfo:
    """A robot-stored cleaning shortcut (from NrRobotShortcutModel)."""
    name: str = ""          # Display name shown in Narwal app
    shortcut_id: str = ""   # Unique identifier (may be numeric or string)
    topic: str = ""         # WS topic path for execution (from shortcut_topic field)
    payload: bytes = b""    # Protobuf payload (from shortcut_command_list / shortcut_json)
```

### Pattern 3: Service Registration (follows Phase 12 precedent)
```python
# In __init__.py or select.py async_setup_entry
async def _execute_shortcut(call: ServiceCall) -> None:
    shortcut_name = call.data.get("shortcut_name")
    # Lookup by name → topic + payload → client.execute_shortcut(topic, payload)

if not hass.services.has_service(DOMAIN, "execute_shortcut"):
    hass.services.async_register(
        DOMAIN, "execute_shortcut", _execute_shortcut,
        schema=vol.Schema({vol.Optional("shortcut_name"): str}),
    )
```

### Pattern 4: Client Methods
**What:** Two new async methods on NarwalClient following the existing send_command pattern.

```python
# In narwal_client/client.py

async def get_shortcuts(self) -> CommandResponse:
    """Fetch shortcut list from robot. Topic TBD — requires probe."""
    return await self.send_command(TOPIC_CMD_GET_SHORTCUTS)

async def execute_shortcut(self, topic: str, payload: bytes = b"") -> CommandResponse:
    """Execute a shortcut by its robot-stored topic path."""
    return await self.send_command(topic, payload=payload, timeout=10.0)
```

### Anti-Patterns to Avoid
- **Polling for shortcut data in coordinator `_async_update_data`:** Only fetch shortcuts on setup + explicit refresh. Shortcuts change infrequently; don't add WS noise to every 60s poll cycle.
- **One button entity per shortcut:** D-06 prohibits this. Keep entity count stable via select + service.
- **Assuming cloud requester = WS command:** The `NrRobotShortcutListGetRequester` may be cloud REST. Probe first; don't hard-code a WS topic based on class name alone.
- **Executing shortcut in `async_select_option`:** Select is for choosing, not triggering. Separate the execute action into the service.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Option dropdown in HA | Custom input_text + template | `SelectEntity` | Native HA integration, dashboard cards, automations all support select entities directly |
| Protobuf shortcut payload | Manual byte encoding | `blackboxprotobuf` (already used) | Same tool as `_build_room_clean_payload` — proven pattern |
| Service schema validation | Manual dict parsing | `voluptuous.Schema` via HA service registration | HA validates call data before dispatch; matches Phase 12 pattern |

---

## Common Pitfalls

### Pitfall 1: Shortcut List May Be Cloud-Only
**What goes wrong:** Probe finds no local WS topic for shortcut retrieval. Shortcuts are stored in Alibaba device shadow (cloud), not on the robot's local WebSocket API.
**Why it happens:** The `NrRobotShortcutListGetRequester` follows the cloud REST requester pattern (`sendGetRequester url = ...` log). Cloud device shadow (`/iot-platform/device-shadow-server/v1/get`) is confirmed present.
**How to avoid:** Probe `config/get` WS first — it returns device configuration that may include robot_shortcuts JSON field. If not found, fall back to probing `developer/*` topics or scanning all broadcasts during a shortcut execution.
**Warning signs:** `config/get` response has no `robot_shortcut` or `robot_shortcuts` field; the topic returns NOT_APPLICABLE.
**Fallback strategy:** If shortcuts are cloud-only for retrieval, the feature is still viable: store shortcut list in HA config (user enters shortcut name + topic manually), use robot's own `shortcut_topic` stored in cloud shadow as the execution WS topic.

### Pitfall 2: shortcut_topic Field May Be a WS Topic or a Siri Shortcut ID
**What goes wrong:** The `shortcut_topic` field in `NrRobotShortcutModel` is assumed to be a WebSocket topic, but it may be a Siri Shortcut identifier (iOS feature). The APK has extensive Siri shortcut UI code (`siri_shortcut_command`, `addiOSSiriShortcut`, `shortcutIdentifier`).
**Why it happens:** The APK has both robot shortcuts AND iOS Siri shortcuts — they share the same naming convention but serve different purposes. `NrRobotShortcutModel` is in `nr_networking/model/robot/` (robot-side), so `shortcut_topic` likely IS the WS execution topic, but confirmation is needed.
**How to avoid:** In the probe, capture ALL broadcasts while triggering a shortcut manually in the Narwal app. Identify which WS topic fires — that IS the execution topic for that shortcut type.
**Warning signs:** `shortcut_topic` field contains strings like `com.apple.siri.*` or UUID format.

### Pitfall 3: shortcut_command_list May Contain Multiple Commands
**What goes wrong:** Executing only the first command in `shortcut_command_list`, missing a multi-step sequence (e.g., set fan level, then start clean).
**Why it happens:** "list" in the field name suggests it may be a sequence. Some shortcuts (Freo Mind, Vacuum+Mop) may require setting parameters then triggering clean.
**How to avoid:** Parse all entries in `shortcut_command_list`. Execute sequentially with brief delay. Cross-reference with the 11 built-in shortcut types from i18n strings.
**Warning signs:** Shortcut executes but robot ignores it (no state change).

### Pitfall 4: APK Model (Freo series) vs. AX12 (Flow) Protocol Differences
**What goes wrong:** Topics/payloads from APK RE work on Freo models but not on the Flow (AX12).
**Why it happens:** The APK is from v2.6.81 for newer Freo models. The Flow uses an older Pita protocol generation. Some topics may not exist on AX12 firmware.
**How to avoid:** Always probe on the actual AX12 robot (10.0.0.112) before implementing. This is D-03.
**Warning signs:** Robot responds NOT_APPLICABLE (code=2) or times out to shortcut topics.

### Pitfall 5: Empty Shortcut List
**What goes wrong:** SelectEntity crashes or shows unusable state when robot has no shortcuts configured.
**Why it happens:** New users or users who haven't created shortcuts in the Narwal app.
**How to avoid:** Check `if not options: return` in select entity. When `options` is empty, set `current_option = None` and entity state to `unknown`. Add a `_attr_available = False` when no shortcuts exist, or show a placeholder option.
**Warning signs:** SelectEntity shows blank dropdown; HA logs attribute error on `options[0]`.

---

## Code Examples

### Probe Script Structure (Plan 01 deliverable)
```python
# tools/probe_shortcuts.py — pattern from probe_map_data.py
# Source: existing tools/probe_map_data.py pattern

PROBE_TOPICS = [
    # Most likely candidates for shortcut list retrieval
    ("config_get",        "config/get",               "", "May contain robot_shortcut JSON"),
    ("get_feature_list",  "common/get_feature_list",  "", "Check for shortcut feature flag"),
    # Add more if config/get returns nothing useful
]

# After getting config/get response, look for:
#   blackboxprotobuf.decode_message(payload) → check for field containing "robot_shortcuts"
```

### 11 Built-in Shortcut Types (from robot_commands_i18n.txt)
```
shortcut1  = Freo Mind (AI smart clean)
shortcut2  = Vacuum and mop
shortcut3  = Vacuum then mop (two-pass)
shortcut4  = Vacuum only
shortcut5  = Mop only
shortcut6  = Pause cleaning
shortcut7  = Resume cleaning
shortcut8  = End cleaning
shortcut9  = Back to dock
shortcut10 = Mop cleaning
shortcut11 = Locate robot

Also: Freo Mind Vacuum+Mop, Freo Mind Vacuum-then-Mop, Freo Advice variants,
      Dry/disinfect (dust bag), Wash mop
```
Total: ~15-18 distinct shortcut action types including smart clean variants.

### SelectEntity async_setup_entry
```python
# Source: sensor.py pattern (this project)
async def async_setup_entry(
    hass: HomeAssistant,
    entry: NarwalConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    async_add_entities([NarwalShortcutSelectEntity(coordinator)])
```

---

## APK Schema Summary

### NrRobotShortcutModel JSON Structure (MEDIUM confidence)
Inferred from Dart JSON serialization function names in libapp_strings.txt:

```
NrRobotShortcutModel {
  robot_shortcuts: Robot_shortcuts[]
}

Robot_shortcuts {
  shortcut_topic: string       // WS topic for execution (e.g. "clean/plan/start")
  shortcut_command_list: ...   // Protobuf payload(s) for the command
  shortcut_json: string        // JSON representation of shortcut params
  shortcut_param: Shortcut_param
}

Shortcut_param {
  // Likely contains: roomIds, fanLevel, mopMode, cleanMode, cleanTimes
  // Fields TBD — requires probe or APK .proto file inspection
}
```

**Known fan level shortcut i18n keys:** `shortcut_fan_level_deep`, `shortcut_fan_level_normal`, `shortcut_fan_level_super` — confirms fan level IS a shortcut parameter.

### How the Narwal App Manages Shortcuts

Based on APK analysis:
1. `NrRobotShortcutListGetRequester` — likely cloud REST call (`nr_networking/network/device/requester/`) to get stored shortcut list
2. `_loadLocalShortcutData` — loads cached shortcut list from app-local storage
3. `shortcutAPPDataSync` — syncs shortcut list between app cache and robot (bidirectional or robot→app)
4. Execution: app sends the `shortcut_topic` WS command with `shortcut_command_list` payload directly to robot

**The critical inference:** Even if retrieval is cloud-assisted, EXECUTION is local WS (because shortcuts work offline once the robot is configured). The `shortcut_topic` in the model IS a local WebSocket topic path.

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Manual room + mode selection | Robot-stored shortcuts via app | Always existed in Narwal app | Our phase exposes this feature |
| Cloud-only shortcut management | Robot caches shortcuts locally | Architecture assumption | Means shortcuts survive offline use |
| Per-button-entity approach | Select + service (D-06) | This phase decision | Stable entity count |

---

## Open Questions

1. **How is the shortcut list retrieved locally?**
   - What we know: `NrRobotShortcutListGetRequester` exists but appears to be a cloud REST requester. `config/get` (WS) may include a `robot_shortcut` or `robot_shortcuts` JSON field.
   - What's unclear: Whether `config/get` response contains shortcut data; whether there is a dedicated WS topic like `shortcut/get` or `clean/shortcut/get` not captured in the original APK analysis.
   - Recommendation: Probe `config/get` first. Also probe any topic with "shortcut" in name. Capture broadcasts during a shortcut execution from the app.

2. **What does `shortcut_topic` contain?**
   - What we know: It's a string field in `Robot_shortcuts`. The APK has both iOS Siri shortcuts AND robot shortcuts. This field is in the robot model (not the Siri model).
   - What's unclear: Whether it's a full WS topic path (`clean/plan/start`) or a shortcut-specific topic (`shortcut/execute/1`).
   - Recommendation: During probe, trigger a shortcut in the Narwal app and capture which WS topic fires. That IS the shortcut_topic value.

3. **Do shortcuts work on AX12 (Flow) at all?**
   - What we know: The feature exists in the app. Issue #13 is from a Flow user (@ShifuSonny) requesting HA automation support — implying they DO use shortcuts on their Flow.
   - What's unclear: Whether the AX12 robot supports storing and retrieving shortcut definitions, or if it only executes the underlying clean commands directly.
   - Recommendation: Ask @ShifuSonny to confirm they see "Shutcut" UI in the Narwal app with their Flow.

4. **Is the shortcut name stored on the robot or only in the app/cloud?**
   - What we know: `shortcut_json` field exists in the model — may contain user-defined name. `shortcut_command_list` likely has the execution data.
   - What's unclear: The naming source (robot vs. app local cache vs. cloud).
   - Recommendation: The probe response will reveal this. If names are missing from WS response, use built-in shortcut type names from i18n strings.

---

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 8.x + pytest-asyncio |
| Config file | pyproject.toml `[tool.pytest.ini_options]` |
| Quick run command | `py -m pytest tests/test_shortcuts.py -x` |
| Full suite command | `py -m pytest tests/ -x` |

### Phase Requirements → Test Map
| ID | Behavior | Test Type | Automated Command | File Exists? |
|----|----------|-----------|-------------------|-------------|
| SHORT-01a | ShortcutInfo dataclass parses from protobuf/JSON | unit | `py -m pytest tests/test_shortcuts.py::test_shortcut_info_parse -x` | Wave 0 |
| SHORT-01b | NarwalState.shortcuts populated from get_shortcuts response | unit | `py -m pytest tests/test_shortcuts.py::test_state_shortcuts -x` | Wave 0 |
| SHORT-01c | SelectEntity.options returns shortcut names from coordinator data | unit | `py -m pytest tests/test_shortcuts.py::test_select_options -x` | Wave 0 |
| SHORT-01d | SelectEntity.options returns empty list gracefully | unit | `py -m pytest tests/test_shortcuts.py::test_select_empty -x` | Wave 0 |
| SHORT-01e | execute_shortcut service dispatches correct WS command | unit | `py -m pytest tests/test_shortcuts.py::test_execute_shortcut_service -x` | Wave 0 |
| SHORT-01f | PLATFORMS list includes Platform.SELECT | unit | `py -m pytest tests/test_integration_structure.py -x` | Exists (extend) |

### Sampling Rate
- **Per task commit:** `py -m pytest tests/test_shortcuts.py -x`
- **Per wave merge:** `py -m pytest tests/ -x`
- **Phase gate:** Full suite green (currently 138 tests) before `/gsd:verify-work`

### Wave 0 Gaps
- [ ] `tests/test_shortcuts.py` — covers SHORT-01a through SHORT-01e (all new)
- [ ] `tests/ha_stubs.py` — needs `SelectEntity` stub added (homeassistant.components.select)

*(tests/test_integration_structure.py exists and will need extending for Platform.SELECT)*

---

## Sources

### Primary (HIGH confidence)
- `apk/libapp_strings.txt` — All Dart string literals from libapp.so (v2.6.77 APK). Field names `shortcut_topic`, `shortcut_command_list`, `shortcut_json`, `Shortcut_param`, `Robot_shortcuts`, `NrRobotShortcutModel` confirmed present.
- `apk/robot_commands_i18n.txt` — All 80 shortcut i18n keys with English translations. 11+ built-in shortcut types confirmed.
- `apk/APK_ANALYSIS_FINDINGS.md` — Complete topic list (sections 4.1-4.15) confirms NO shortcut-specific WS topics in the known set.
- `narwal_client/client.py` — `_build_room_clean_payload()` and `start_rooms()` as the implementation template for shortcut execution.
- `custom_components/narwal/entity.py`, `sensor.py` — Entity platform pattern confirmed.
- `tests/ha_stubs.py` — Test stub architecture confirmed; SelectEntity not yet stubbed.
- `pyproject.toml` — pytest 8.x + pytest-asyncio confirmed, no new packages needed.

### Secondary (MEDIUM confidence)
- HA SelectEntity developer docs (https://developers.home-assistant.io/docs/core/entity/select/): `_attr_options`, `_attr_current_option`, `async_select_option` API confirmed.
- `apk/libapp_strings.txt` line 42805: `/iot-platform/device-shadow-server/v1/get` — cloud device shadow endpoint confirmed present (MEDIUM: context insufficient to confirm it stores shortcuts).

### Tertiary (LOW confidence — needs probe validation)
- Inference that `shortcut_topic` = a local WebSocket topic path. Based on: (1) field is in `Robot_shortcuts` not Siri model, (2) execution must work offline, (3) shortcuts include clean commands which have known WS topics. Needs probe confirmation.
- Inference that `config/get` WS topic may return shortcut data. Based on: `robot_shortcut` (singular) appearing as a JSON field name in libapp strings near device/robot model data. Needs probe confirmation.

---

## Metadata

**Confidence breakdown:**
- APK Schema (NrRobotShortcutModel fields): MEDIUM — field names confirmed, field types inferred from naming convention
- Execution mechanism (shortcut_topic = WS): MEDIUM — logical inference, not directly observed
- Retrieval mechanism (config/get or cloud): LOW — critical unknown, probe required
- SelectEntity API: HIGH — official HA developer docs confirmed
- Test framework: HIGH — pyproject.toml and existing tests confirmed
- Built-in shortcut types (11+): HIGH — robot_commands_i18n.txt direct read

**Research date:** 2026-04-01
**Valid until:** 2026-05-01 (APK schema stable; HA SelectEntity API stable)
