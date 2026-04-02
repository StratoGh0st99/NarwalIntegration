---
phase: 14
slug: shortcuts-presets
status: archived
nyquist_compliant: false
wave_0_complete: false
created: 2026-04-01
archived: 2026-04-01
archive_reason: Shortcuts are cloud-managed (Alibaba Alink IoT REST), not accessible via local WebSocket API
---

# Phase 14 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 8.x + pytest-asyncio |
| **Config file** | pyproject.toml `[tool.pytest.ini_options]` |
| **Quick run command** | `py -m pytest tests/test_shortcuts.py -x` |
| **Full suite command** | `py -m pytest tests/ -x` |
| **Estimated runtime** | ~5 seconds |

---

## Sampling Rate

- **After every task commit:** Run `py -m pytest tests/test_shortcuts.py -x`
- **After every plan wave:** Run `py -m pytest tests/ -x`
- **Before `/gsd:verify-work`:** Full suite must be green
- **Max feedback latency:** 5 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------|-------------------|-------------|--------|
| 14-01-01 | 01 | 1 | SHORT-01a | probe | `py tools/probe_shortcuts.py` | ❌ W0 | ⬜ pending |
| 14-02-01 | 02 | 2 | SHORT-01a | unit | `py -m pytest tests/test_shortcuts.py::test_shortcut_info_parse -x` | ❌ W0 | ⬜ pending |
| 14-02-02 | 02 | 2 | SHORT-01b | unit | `py -m pytest tests/test_shortcuts.py::test_state_shortcuts -x` | ❌ W0 | ⬜ pending |
| 14-02-03 | 02 | 2 | SHORT-01c | unit | `py -m pytest tests/test_shortcuts.py::test_select_options -x` | ❌ W0 | ⬜ pending |
| 14-02-04 | 02 | 2 | SHORT-01d | unit | `py -m pytest tests/test_shortcuts.py::test_select_empty -x` | ❌ W0 | ⬜ pending |
| 14-02-05 | 02 | 2 | SHORT-01e | unit | `py -m pytest tests/test_shortcuts.py::test_execute_shortcut_service -x` | ❌ W0 | ⬜ pending |
| 14-02-06 | 02 | 2 | SHORT-01f | unit | `py -m pytest tests/test_integration_structure.py -x` | ✅ extend | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/test_shortcuts.py` — stubs for SHORT-01a through SHORT-01e
- [ ] `tests/ha_stubs.py` — needs `SelectEntity` stub added (homeassistant.components.select)

*tests/test_integration_structure.py exists and will need extending for Platform.SELECT*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Shortcut list fetched from robot | SHORT-01a | Requires live robot | Run probe_shortcuts.py against 10.0.0.112 |
| Shortcut execution triggers clean | SHORT-01e | Requires physical robot | Execute shortcut via HA service, observe robot |
| Select entity updates on app change | SHORT-01c | Requires Narwal app | Add/remove shortcut in app, check HA entity options |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 5s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
