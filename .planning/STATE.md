# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-03-01)

**Core value:** Users can control and monitor their Narwal Flow vacuum entirely locally — start/stop/pause, see status, view a live floor map — without any cloud dependency.
**Current focus:** Phase 7 — Map validation (room names, trail accuracy) & command hardening

## Current Position

Phase: 7 of 8 (Map Validation & Command Hardening)
Plan: 07-03 — room names decoded, trail transform needs fixing
Status: v0.4.0 + 4 fixes (fe6c18e) — all 22 rooms labeled, trail positions off
Last activity: 2026-03-08 — cloud API disproved, ROOM_TYPE enum decoded, room labels added

Progress: [████████░░] 89% (phases 0-6 complete, phase 7 map validation in progress)

## Accumulated Context

### Decisions

- [07-02]: Topic subscription must be renewed every 8min (expires at 10min)
- [07-02]: Don't clear map_display_data on state transitions — let it go stale naturally
- [S8]: _ensure_awake must check broadcast age, not just robot_awake flag
- [S9]: NEVER remove get_device_base_status from wake burst — forces active CPU wake
- [S9]: wake() must NOT reconnect when _listener_active
- [S9]: Entity stays available when sleeping — return stale data, not UpdateFailed
- [S10]: clean/plan/start requires CleanTask payload — empty payload silently fails
- [S11]: display_map dropout recovery must skip when is_returning — wake bursts cause pause bouncing
- [S11]: Robot stays CLEANING(4) during return — dock fields update before working_status
- [S11]: Resume during paused-return resumes the return, not cleaning
- [S11]: Model selector persists product_key in config entry — survives HA restart
- [S11]: Don't assume robot state from logs — verify physically before code changes
- [S16]: Room data is 100% LOCAL — no cloud API needed for room names
- [S16]: ROOM_TYPE enum (field 2) maps to default names; field 8 = instance index
- [S16]: display_map positions are DECIMETERS (not cm as originally noted)
- [S16]: Obstacles are cloud-only (get_vision_image returns empty)
- [S16]: Narwal app uses Alibaba Alink IoT (aliyuncs.com) — only session refresh, no map fetch

### Pending Todos

- **PRIORITY: Test room name rendering on HA map** — do all 22 labels show correctly?
- **PRIORITY: Fix trail transform** — trails render but positions are WAY OFF actual rooms
- Validate: does start work WITHOUT CleanTask payload? (it was working before session 10)
- Validate: HA frontend buttons map to correct commands in every state
- Fix trail: segment breaks on large jumps (>1m grid distance)
- "Self test paused" unmapped working_status
- CleanTask payload hardcodes max suction / wet mop / single pass

### Blockers/Concerns

- Trail positions don't match actual cleaning locations — transform may have Y-flip, origin, or unit error
- CleanTask payload hardcodes max suction / wet mop / single pass — may not match user preference
- Need systematic test matrix before moving to map/settings features

## Session Continuity

Last session: 2026-03-08 (session 18)
Stopped at: Coordinate transform VALIDATED. Factor 1.0 (pixel=raw-origin) confirmed
via Pantry cleaning run — POSITION DIAG shows correct room traversal (rooms 11→9→8),
dock stable at (272.0, 342.3), 1005 renders. Remaining: trail segment breaks, command
testing matrix, phase 7 completion.

Resume file: .planning/phases/07-map-validation/.continue-here.md
