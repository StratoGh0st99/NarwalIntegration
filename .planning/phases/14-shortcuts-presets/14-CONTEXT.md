# Phase 14: Shortcuts & Presets - Context

**Gathered:** 2026-04-01
**Status:** ARCHIVED (2026-04-01) — Shortcuts are cloud-managed, not accessible via local WS API

<domain>
## Phase Boundary

Allow users to trigger Narwal app "Shutcut" presets via HA automations and dashboard. Discover robot-stored shortcuts via WebSocket API (topics from APK RE), expose them as a select entity, and provide a service to execute them. Custom/HA-side preset building is out of scope — this phase mirrors what the robot already has.

</domain>

<decisions>
## Implementation Decisions

### Data source
- **D-01:** Execute robot-stored shortcuts, not HA-side presets. The Narwal app stores "Shutcut" entries on the robot — we discover and execute those.
- **D-02:** APK RE is the first dependency. Must find the WebSocket topic(s) for shortcut list retrieval and execution from @northwestsupra's APK decompilation (v2.6.81, includes .proto files). APK classes to find: `NrRobotShortcutListGetRequester`, `NrRobotShortcutListSetRequester`.
- **D-03:** Probe robot with discovered topics to confirm payload format and response schema before building HA entities. APK is from a different model — topic names may not match, so probing is essential (not just nice-to-have).

### HA entity exposure
- **D-04:** Select entity dropdown listing all shortcuts reported by the robot. Entity options update automatically as shortcuts are added/removed in the Narwal app.
- **D-05:** Custom service (`narwal.execute_shortcut`) to trigger the currently selected shortcut (or accept a shortcut ID/name parameter for automation use).
- **D-06:** No button entities per shortcut — the select + service pattern keeps entity count stable.

### Sync & refresh
- **D-07:** Fetch shortcut list on integration setup and refresh periodically via the coordinator poll cycle (60s fallback).
- **D-08:** Shortcut list changes in the Narwal app automatically reflect in HA within one poll cycle — no manual reload needed.

### Claude's Discretion
- Exact select entity naming and icon
- How to handle empty shortcut list (no shortcuts configured in app)
- Whether to cache shortcut list in coordinator data or fetch separately
- Error handling for shortcut execution failures
- Whether shortcut parameters (rooms, fan, mop) are displayed as entity attributes

</decisions>

<specifics>
## Specific Ideas

- Issue #13 from @ShifuSonny (Flow user): "I don't always run a full house cleaning — it would be very useful to trigger the robot using these specific modes through automations"
- Narwal app labels the feature "Shutcut" (typo in their UI)
- APK shows 11+ built-in shortcut types: Freo Mind, Vacuum+Mop, Vacuum only, Mop only, plus fan-level and dock-action shortcuts
- `NrRobotShortcutModel` with `shortcut_topic`, `shortcut_command_list`, `shortcut_json`, `Shortcut_param` fields found in APK strings

</specifics>

<canonical_refs>
## Canonical References

### APK reverse engineering
- `apk/libapp_strings.txt` — APK class/method names including shortcut requesters and model classes
- `robot_commands_i18n.txt` — Shortcut UI labels, built-in shortcut type names, descriptions
- **CAVEAT:** APK decompilation from @northwestsupra is for a different model than the dev's Flow (AX12). Use APK findings as directional guidance only — topic names and payload formats may differ. Always validate against the local robot via probing.

### Existing patterns (room cleaning as reference)
- `narwal_client/client.py` — `start_rooms()` and `_build_room_clean_payload()` show CleanTask protobuf construction pattern
- `narwal_client/const.py` — Topic constants, known product keys
- `custom_components/narwal/vacuum.py` — HA vacuum entity with `async_clean_segments()` as select+execute pattern reference

### Phase 9 context (closest precedent)
- `.planning/phases/09-room-cleaning/09-CONTEXT.md` — Room cleaning decisions (if exists), payload format discoveries

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `NarwalClient.send_command(topic, payload)` — Generic command sender, works for any topic
- `_build_room_clean_payload()` — Pattern for constructing protobuf payloads with per-room params
- `DataUpdateCoordinator` — Already polls robot state on 60s cycle, can include shortcut list refresh
- `NarwalVacuumEntity` — Select entity can follow same coordinator data pattern

### Established Patterns
- Topic constants in `narwal_client/const.py` — new shortcut topics go here
- Command+response pattern: `send_command()` returns response, check `result_code`
- Entity platform registration in `__init__.py` `PLATFORMS` list
- Config flow model selector — pattern for adding new entity types

### Integration Points
- New `select.py` platform for shortcut select entity
- New service registration in `__init__.py` or `vacuum.py` for `narwal.execute_shortcut`
- Coordinator data extended with shortcut list (fetched alongside other state)
- Probe script needed in `tools/` for initial topic discovery

</code_context>

<deferred>
## Deferred Ideas

- HA-side preset builder (custom cleaning configs without robot shortcuts) — could be a future phase if robot shortcuts prove limited
- Editing/creating shortcuts from HA (set requester) — this phase is read+execute only
- Scheduled shortcut execution (timing) — HA automations handle scheduling natively

</deferred>

---

*Phase: 14-shortcuts-presets*
*Context gathered: 2026-04-01*
