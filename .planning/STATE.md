---
gsd_state_version: 1.0
milestone: v0.5
milestone_name: milestone
status: unknown
last_updated: "2026-03-09T23:33:15.639Z"
progress:
  total_phases: 5
  completed_phases: 3
  total_plans: 8
  completed_plans: 7
---

# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-03-01)

**Core value:** Users can control and monitor their Narwal Flow vacuum entirely locally — start/stop/pause, see status, view a live floor map — without any cloud dependency.
**Current focus:** Phase 10 COMPLETE — Next: Phase 11 (Vision Obstacles) or Phase 12 (Camera & Patrol)

## Current Position

Phase: 10 of 12 — COMPLETE (Obstacle Mapping)
Next phase: 11 (Vision Obstacles — needs probing during clean) or 12 (Camera & Patrol)
Last activity: 2026-03-09 — Obstacle type names corrected to APK furniture enum

Progress: [██████░░░░] 60% (3/5 post-v0.5 phases complete)

## Accumulated Context

### Key Decisions (Phase 8)

- Entity availability uses coordinator.last_update_success, not client.connected
- 5 consecutive poll failures before marking unavailable (~5 min grace period)
- Removed client.connect() from poll loop to avoid racing with listener
- Mock HA framework via sys.modules stubs (ha_stubs.py) instead of pytest-homeassistant-custom-component
- Test config flow with __new__ + mocked base methods for isolated async_step_user testing

### Key Decisions (Phase 7)

- Coordinate transform: factor 1.0, pixel = raw - origin (no scaling)
- is_returning requires BOTH field 3.7 AND 3.10 (prevents false positives)
- Room data is 100% local — ROOM_TYPE enum + instance_index for names
- Furniture obstacles are LOCAL (field 2.32, typeId = APK furniture enum). Vision obstacles likely also local — needs probing during active clean.
- Trail segment breaks are obstacle avoidance, not a rendering bug (deferred)
- Label overlap matches Narwal app behavior (not an issue to fix)

### Key Decisions (Phase 9)

- Room IDs encoded as repeated varint in field 1.2 of CleanTask protobuf
- Segment.group uses Rooms/Utility based on RoomInfo.category
- Empty room_ids in start_rooms() falls back to whole-house clean
- Bare roomId in field 1.2 is IGNORED by robot; each room entry needs full MapCleanParamInfo fields (cleanMode=2, cleanTimes=1, sweepMode=3, mopMode=2)
- Room-clean response returns code=0 with config data (not usual code=1 ack)

### Pending Todos

- "Self test paused" unmapped working_status
- CleanTask payload hardcodes max suction / wet mop / single pass
- Validate: does start work WITHOUT CleanTask payload?

### Key Decisions (Phase 10)

- Obstacle positions are LOCAL (field 2.32), not cloud-only — corrects Phase 7 assumption
- typeId IS the specific furniture enum from APK map_furniture.json (NOT category codes — corrected after user validation)
- Pass obstacles + origin to render_base_map (not pre-computed grid coords)
- Obstacles render on base map (static, cached) not overlay
- Skip rotation for v1 — axis-aligned rectangles sufficient

### Blockers/Concerns

None

## Session Continuity

Last session: 2026-03-11
Stopped at: Phase 11 plan 11-01 task 2 — vision obstacle data source investigation. get_vision_image returns NOT_APPLICABLE. App shows obstacles but we can't find the WebSocket source. Deep APK reverse-engineering done (3d-map.js, MapVisionInfo schema, StaticMapPayload). See .continue-here.md for full context.
Resume file: .planning/phases/11-vision-obstacles/.continue-here.md
