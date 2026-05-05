#!/usr/bin/env python3
"""Record annotated Narwal broadcasts for protocol reverse-engineering.

Streams `ha core logs --follow` from a Home Assistant host over SSH,
filters for `DUMP <topic>: <decoded>` lines emitted by the integration
when run with debug logging, and interleaves user-typed annotations
into the output. Captures land in JSONL so they're trivially diffable
and replayable.

Usage:
    # Stream + annotate (Ctrl+C to stop)
    python3 narwal_capture.py record --host root@192.168.178.3 \
        --out captures/baseline.jsonl

    # Diff two captures, listing fields that changed in
    # robot_base_status / working_status broadcasts
    python3 narwal_capture.py diff captures/baseline.jsonl \
        captures/after-toggle.jsonl

    # Pretty-print a recorded timeline
    python3 narwal_capture.py replay captures/baseline.jsonl

The integration must already be running with debug logging:
    service: logger.set_level
    data:
      custom_components.narwal: debug
      custom_components.narwal.narwal_client: debug

This works because the (debug-branch / shipped) client logs every
decoded broadcast as `DUMP <topic>: <repr>` at DEBUG level, which
ha core logs --follow streams over the supervisor API.
"""

from __future__ import annotations

import argparse
import ast
import datetime as dt
import json
import re
import shlex
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any, Iterator, TextIO

# Strips the ANSI colour codes that `ha core logs` wraps each line in.
ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")

# Matches lines like:
#   2026-05-04 23:55:38.917 DEBUG (MainThread) [custom_components.narwal.narwal_client.client] DUMP status/working_status: {...}
DUMP_RE = re.compile(
    r"^(?P<ts>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3}) "
    r"DEBUG .*?\[custom_components\.narwal\.[\w.]+\] "
    r"DUMP (?P<topic>\S+): (?P<payload>.+)$"
)


def _now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="milliseconds")


def _parse_payload(raw: str) -> Any:
    """Best-effort parse of the broadcast repr.

    blackboxprotobuf decodes broadcasts to dicts of int/str/bytes; the
    integration logs them with `%r`, which is a Python literal we can
    round-trip via ast.literal_eval. Falls back to the raw string if
    something more exotic shows up.
    """
    try:
        return ast.literal_eval(raw)
    except (SyntaxError, ValueError):
        return raw


def _iter_log_stream(host: str) -> Iterator[str]:
    """Yield decoded log lines from `ha core logs --follow` over SSH."""
    cmd = ["ssh", host, "ha core logs --follow"]
    proc = subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        bufsize=1, text=True,
    )
    assert proc.stdout is not None
    try:
        for line in proc.stdout:
            yield ANSI_RE.sub("", line.rstrip("\n"))
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            proc.kill()


# Topics whose changes we never report — they're either pure noise
# (display_map fires every ~1.5s during cleaning, download_status is
# usually a constant `2`) or reach the change-detector via a different
# topic (working_status duplicates many robot_base_status sub-fields).
_NOISY_TOPICS: frozenset[str] = frozenset({
    "map/display_map",
    "status/download_status",
    "upgrade/upgrade_status",
})

# Top-level robot_base_status keys whose values change every broadcast
# without anything semantic happening (battery jitter, monotonic
# timestamps, session ids). Filtering them keeps the change-hint
# signal-to-noise ratio high.
_NOISE_BASE_KEYS: frozenset[str] = frozenset({
    "2",   # battery float32 — jitters slightly each tick
    "13",  # session id (string)
    "35",  # secondary battery / charging value
    "36",  # last-update timestamp (ms epoch)
})

# Working-status fields that tick every broadcast during a clean
# (elapsed time, area, the always-600 cumulative-time-ish field).
_NOISE_WS_KEYS: frozenset[str] = frozenset({"3", "13", "15"})


def _diff_dict(
    a: dict[str, Any] | None,
    b: dict[str, Any] | None,
    skip: frozenset[str],
) -> list[str]:
    """Return short 'k: x → y' strings for non-noise key changes."""
    if not isinstance(a, dict) or not isinstance(b, dict):
        return []
    keys = (set(a) | set(b)) - skip
    out = []
    for k in sorted(keys, key=lambda x: int(x) if x.isdigit() else 999):
        va, vb = a.get(k), b.get(k)
        if va == vb:
            continue
        # Truncate long values so the hint fits one line.
        sa = repr(va)
        sb = repr(vb)
        if len(sa) > 40:
            sa = sa[:37] + "…"
        if len(sb) > 40:
            sb = sb[:37] + "…"
        out.append(f"{k}: {sa}→{sb}")
    return out


def _writer_thread(
    host: str, out_fp: TextIO, lock: threading.Lock,
    stop: threading.Event, verbose: bool, counter: list[int],
    notable_only: bool,
) -> None:
    """Read SSH log stream, write parsed DUMP lines to the JSONL output."""
    last_payload: dict[str, dict[str, Any]] = {}
    for line in _iter_log_stream(host):
        if stop.is_set():
            break
        m = DUMP_RE.match(line)
        if not m:
            continue
        topic = m.group("topic")
        payload = _parse_payload(m.group("payload"))
        record = {
            "kind": "broadcast",
            "ts": _now_iso(),
            "log_ts": m.group("ts"),
            "topic": topic,
            "payload": payload,
        }

        # Detect notable change vs last seen payload on the same topic.
        notable_diff: list[str] = []
        if topic == "status/robot_base_status":
            notable_diff = _diff_dict(
                last_payload.get(topic), payload if isinstance(payload, dict) else None,
                _NOISE_BASE_KEYS,
            )
        elif topic == "status/working_status":
            notable_diff = _diff_dict(
                last_payload.get(topic), payload if isinstance(payload, dict) else None,
                _NOISE_WS_KEYS,
            )
        if isinstance(payload, dict):
            last_payload[topic] = payload

        with lock:
            out_fp.write(json.dumps(record, default=str) + "\n")
            out_fp.flush()
            counter[0] += 1
            if verbose:
                # Verbose mode shares the terminal with the input prompt,
                # so the cursor jumps as broadcasts arrive. Default is
                # silent — `tail -f <out>.jsonl` in another window if
                # you want to watch the stream.
                print(f"  [{record['log_ts']}] {topic}",
                      file=sys.stderr)
            elif notable_diff and topic not in _NOISY_TOPICS:
                # Bell + one-line hint so the user notices an
                # interesting change but can keep typing. Doesn't
                # interrupt the input line — readline redraws on the
                # next keystroke.
                short_topic = topic.rsplit("/", 1)[-1]
                hint = ", ".join(notable_diff[:4])
                if len(notable_diff) > 4:
                    hint += f" (+{len(notable_diff) - 4} more)"
                print(f"\a\n[*] {short_topic}: {hint}",
                      file=sys.stderr, flush=True)
                # Persist the diff alongside the broadcast for replay.
                out_fp.write(json.dumps({
                    "kind": "change",
                    "ts": record["ts"],
                    "log_ts": record["log_ts"],
                    "topic": topic,
                    "diff": notable_diff,
                }) + "\n")
                out_fp.flush()
        # notable_only currently doesn't drop broadcasts from the
        # JSONL; it's reserved for a future flag if the captures get
        # too big to keep raw. Plumbed through now so callers don't
        # break.
        _ = notable_only


# --- Decoder for known protocol fields ---------------------------------
#
# What we already understand about Flow 2 broadcasts (validated live).
# Everything else we surface as raw key→value so the user can spot new
# patterns. Keep these dicts in sync with narwal_client.

_WORKING_STATUS = {
    0: "UNKNOWN", 1: "STANDBY", 3: "MOP_WASHING", 4: "CLEANING",
    5: "CLEANING_ALT", 10: "DOCKED", 14: "CHARGED",
    17: "MOP_DRYING", 19: "MOP_DRYING_ACTIVE", 99: "ERROR",
}
_SUCTION = {1: "Quiet", 2: "Standard", 3: "Strong", 4: "Super powerful"}
_MOP_HUMIDITY = {1: "Slightly dry", 2: "Standard", 3: "Slightly wet"}
_CLEAN_MODE = {
    1: "Vacuum", 2: "Mop", 3: "Vacuum then mop",
    4: "Vacuum and mop", 5: "Adaptive (Raumanpassung)",
}

# Top-level robot_base_status fields we know enough about to label.
_KNOWN_BASE_KEYS: frozenset[str] = frozenset({
    "1", "2", "3", "5", "11", "12", "13", "14", "15", "16", "18",
    "20", "23", "24", "25", "26", "28", "29", "30", "32", "34", "35",
    "36", "38", "39", "40", "41", "44", "47", "48", "49", "50",
})
_KNOWN_WS_KEYS: frozenset[str] = frozenset({
    "3", "5", "6", "13", "15", "18", "19", "22",
})


def _f32(val: Any) -> float | None:
    """Decode a float32 stored as int bits (or already a float)."""
    if isinstance(val, float):
        return val
    if isinstance(val, int):
        try:
            import struct
            return struct.unpack("f", struct.pack("I", val & 0xFFFFFFFF))[0]
        except Exception:
            return None
    return None


def _f48_entries(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Normalize robot_base_status field 48.1 to a list of dicts."""
    f1 = payload.get("48", {}).get("1") if isinstance(payload.get("48"), dict) else None
    if isinstance(f1, list):
        return [e for e in f1 if isinstance(e, dict)]
    if isinstance(f1, dict):
        return [f1]
    return []


def _decode_state(latest: dict[str, dict[str, Any]]) -> list[tuple[str, str, str]]:
    """Build (label, value, raw_field) rows from the latest broadcasts.

    Only includes fields we understand. Unknown stuff goes through
    _unknown_keys() so the operator can spot new patterns.
    """
    bs = latest.get("status/robot_base_status") or {}
    ws = latest.get("status/working_status") or {}
    rows: list[tuple[str, str, str]] = []

    # Working status
    f3 = bs.get("3") if isinstance(bs.get("3"), dict) else {}
    ws_id = f3.get("1") if isinstance(f3, dict) else None
    rows.append((
        "Status",
        f"{_WORKING_STATUS.get(ws_id, '?')} ({ws_id})" if ws_id is not None else "-",
        f"3.1={ws_id}",
    ))

    # Battery (% from float32 in field 2)
    bat = _f32(bs.get("2"))
    rows.append(("Battery", f"{bat:.1f}%" if bat is not None else "-", "2 (float32)"))

    # Suction
    s = bs.get("26")
    rows.append(("Suction", f"{_SUCTION.get(s, '?')} ({s})" if s else "-", "26"))

    # Mop humidity
    h = bs.get("29")
    rows.append((
        "Mop humidity",
        f"{_MOP_HUMIDITY.get(h, '?')} ({h})" if h else "-",
        "29",
    ))

    # Dust bag
    db = bs.get("41")
    rows.append(("Dust bag", f"{db}%" if db is not None else "-", "41"))

    # Coverage precision (1 = Standard, absent = Meticulous; tentative)
    cp = bs.get("34")
    if cp == 1:
        rows.append(("Coverage", "Standard (tentative)", "34=1"))
    elif cp is None:
        rows.append(("Coverage", "Meticulous? (34 absent)", "34=∅"))
    else:
        rows.append(("Coverage", f"unknown (34={cp})", "34"))

    # Pause / cleaning sub-state
    paused = isinstance(f3, dict) and f3.get("2") == 1
    returning = isinstance(f3, dict) and f3.get("7") == 1
    sub = []
    if paused:
        sub.append("paused")
    if returning:
        sub.append("returning")
    rows.append(("Sub-state", ", ".join(sub) or "-",
                 f"3.2={f3.get('2') if isinstance(f3, dict) else '-'} 3.7={f3.get('7') if isinstance(f3, dict) else '-'}"))

    # Field 48: parse markers + clean-task config + error
    entries = _f48_entries(bs)
    markers: list[str] = []
    err_info: dict[str, Any] | None = None
    clean_cfg: dict[str, Any] | None = None
    for e in entries:
        if "10" in e:
            markers.append("dust_emptying")
        if "13" in e:
            markers.append("?13")
        if "15" in e:
            markers.append("mop_drying")
        if "5" in e and isinstance(e.get("5"), dict):
            clean_cfg = e["5"].get("1") if isinstance(e["5"].get("1"), dict) else None
        if "2" in e and isinstance(e.get("2"), dict) and e["2"]:
            err_info = e["2"]

    rows.append(("Station markers", ", ".join(markers) or "-", "48.1.*"))

    # Active clean task config (when running)
    if clean_cfg:
        mode = clean_cfg.get("1")
        mh = clean_cfg.get("2")
        passes = clean_cfg.get("3")
        cfg_str = (
            f"{_CLEAN_MODE.get(mode, '?')} ({mode}), mop={_MOP_HUMIDITY.get(mh, mh)}"
            + (f", passes={passes}" if passes else "")
        )
        rows.append(("Active task", cfg_str, "48.1.*.5.1"))
    else:
        rows.append(("Active task", "-", "48.1.*.5.1"))

    # Error
    if err_info:
        code = err_info.get("2")
        msg = err_info.get("3", "")
        sev = err_info.get("1", "?")
        rows.append((
            "ERROR",
            f"sev={sev} code={code} ({code:#010x})  «{msg}»"
            if isinstance(code, int) else f"sev={sev} {err_info!r}",
            "48.1.*.2",
        ))
    else:
        rows.append(("Error", "none", "48.1.*.2"))

    # working_status: room queue + current room
    wf5 = ws.get("5") if isinstance(ws, dict) else None
    if isinstance(wf5, list):
        rooms = [str(e.get("1")) for e in wf5 if isinstance(e, dict)]
        rows.append(("Room queue", ", ".join(rooms) or "-", "ws.5"))
    elif isinstance(wf5, dict):
        rows.append(("Room queue", str(wf5.get("1")), "ws.5"))
    else:
        rows.append(("Room queue", "-", "ws.5"))
    cur = ws.get("6")
    rows.append(("Current room", str(cur) if cur is not None else "-", "ws.6"))

    return rows


def _unknown_keys(latest: dict[str, dict[str, Any]]) -> list[tuple[str, str, str]]:
    """Return (topic, key, raw repr) for fields we don't decode yet."""
    out: list[tuple[str, str, str]] = []
    bs = latest.get("status/robot_base_status") or {}
    for k in sorted(bs.keys(), key=lambda x: int(x) if x.isdigit() else 999):
        if k in _KNOWN_BASE_KEYS:
            continue
        out.append(("base", k, repr(bs[k])[:60]))
    ws = latest.get("status/working_status") or {}
    for k in sorted(ws.keys(), key=lambda x: int(x) if x.isdigit() else 999):
        if k in _KNOWN_WS_KEYS:
            continue
        out.append(("working", k, repr(ws[k])[:60]))
    return out


# --- TUI ---------------------------------------------------------------


def _tui_record(args: argparse.Namespace) -> int:
    """Curses TUI: live decoded state table + annotation prompt."""
    import curses
    import locale
    import queue as _q

    locale.setlocale(locale.LC_ALL, "")

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    stop = threading.Event()
    counter = [0]
    msg_q: _q.Queue = _q.Queue()
    latest: dict[str, dict[str, Any]] = {}
    last_change_label = "—"
    last_payloads: dict[str, dict[str, Any]] = {}

    def worker(out_fp: TextIO) -> None:
        for line in _iter_log_stream(args.host):
            if stop.is_set():
                break
            m = DUMP_RE.match(line)
            if not m:
                continue
            topic = m.group("topic")
            log_ts = m.group("ts")
            payload = _parse_payload(m.group("payload"))
            # persist every broadcast
            out_fp.write(json.dumps({
                "kind": "broadcast",
                "ts": _now_iso(),
                "log_ts": log_ts,
                "topic": topic,
                "payload": payload,
            }, default=str) + "\n")
            out_fp.flush()
            counter[0] += 1
            msg_q.put((topic, log_ts, payload))

    def tui_main(stdscr: "curses.window") -> None:
        nonlocal last_change_label
        curses.curs_set(1)
        stdscr.nodelay(True)
        stdscr.timeout(50)  # ms — also drives the redraw cadence

        # Header noting the session start.
        with out_path.open("a") as out_fp:
            out_fp.write(json.dumps({
                "kind": "session_start",
                "ts": _now_iso(),
                "host": args.host,
                "mode": "tui",
            }) + "\n")
            out_fp.flush()

            t = threading.Thread(target=worker, args=(out_fp,), daemon=True)
            t.start()

            input_buf = ""
            while not stop.is_set():
                # Drain any queued broadcasts.
                drained = 0
                while True:
                    try:
                        topic, log_ts, payload = msg_q.get_nowait()
                    except _q.Empty:
                        break
                    if isinstance(payload, dict):
                        # Compute notable diff for the change label.
                        if topic == "status/robot_base_status":
                            d = _diff_dict(last_payloads.get(topic), payload, _NOISE_BASE_KEYS)
                            if d:
                                last_change_label = f"[{log_ts}] base: " + ", ".join(d[:3])
                        elif topic == "status/working_status":
                            d = _diff_dict(last_payloads.get(topic), payload, _NOISE_WS_KEYS)
                            if d:
                                last_change_label = f"[{log_ts}] ws: " + ", ".join(d[:3])
                        last_payloads[topic] = payload
                        latest[topic] = payload
                    drained += 1

                # Redraw (cheap, only when input received or every tick).
                stdscr.erase()
                h, w = stdscr.getmaxyx()
                title = f"narwal-capture · host={args.host} · broadcasts={counter[0]} · {out_path.name}"
                stdscr.addstr(0, 0, title[:w-1], curses.A_BOLD)
                stdscr.addstr(1, 0, "─" * (w - 1))

                row = 2
                rows = _decode_state(latest)
                for label, value, raw in rows:
                    if row >= h - 4:
                        break
                    line_str = f"  {label:<16} {value:<48} {raw}"
                    stdscr.addstr(row, 0, line_str[:w-1])
                    row += 1

                # Unknown / raw section
                row += 1
                if row < h - 4:
                    stdscr.addstr(row, 0, "  Unknown fields:", curses.A_DIM)
                    row += 1
                    for topic, key, repr_val in _unknown_keys(latest):
                        if row >= h - 4:
                            break
                        s = f"    {topic}.{key:<6} = {repr_val}"
                        stdscr.addstr(row, 0, s[:w-1], curses.A_DIM)
                        row += 1

                # Last notable change line + prompt
                stdscr.addstr(h - 3, 0, ("Δ " + last_change_label)[:w-1], curses.A_DIM)
                stdscr.addstr(h - 2, 0, "─" * (w - 1))
                prompt = f"> {input_buf}"
                stdscr.addstr(h - 1, 0, prompt[:w-1])
                stdscr.move(h - 1, min(len(prompt), w - 1))
                stdscr.refresh()

                # Poll keypress.
                ch = stdscr.getch()
                if ch == -1:
                    continue
                if ch in (3, 4, 27):  # Ctrl-C / Ctrl-D / ESC
                    break
                if ch in (10, 13):  # Enter
                    text = input_buf.strip()
                    input_buf = ""
                    if not text:
                        continue
                    out_fp.write(json.dumps({
                        "kind": "annotation",
                        "ts": _now_iso(),
                        "text": text,
                    }) + "\n")
                    out_fp.flush()
                elif ch in (curses.KEY_BACKSPACE, 127, 8):
                    input_buf = input_buf[:-1]
                elif 32 <= ch < 127:
                    input_buf += chr(ch)

        stop.set()

    try:
        curses.wrapper(tui_main)
    finally:
        stop.set()
        print(f"\nStopped after {counter[0]} broadcasts. Capture: {out_path}",
              file=sys.stderr)
    return 0


def cmd_record(args: argparse.Namespace) -> int:
    """Stream + annotate.

    Default mode is the curses TUI dashboard (decoded state table +
    annotation prompt). --simple falls back to the line-oriented mode
    (annotations on stdin, broadcasts written to JSONL only).
    """
    if not args.simple:
        return _tui_record(args)

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    lock = threading.Lock()
    stop = threading.Event()
    counter = [0]

    print(
        f"Recording to {out_path}.\n"
        f"Type any text + Enter to mark an annotation. "
        f"Empty line / Ctrl+D / Ctrl+C to stop.\n",
        file=sys.stderr,
    )

    with out_path.open("a") as out_fp:
        # Header line so each capture starts identifiable.
        out_fp.write(json.dumps({
            "kind": "session_start",
            "ts": _now_iso(),
            "host": args.host,
        }) + "\n")
        out_fp.flush()

        worker = threading.Thread(
            target=_writer_thread,
            args=(args.host, out_fp, lock, stop, args.verbose, counter, False),
            daemon=True,
        )
        worker.start()

        try:
            while True:
                try:
                    text = input("> ")
                except (EOFError, KeyboardInterrupt):
                    break
                text = text.strip()
                if not text:
                    break
                with lock:
                    out_fp.write(json.dumps({
                        "kind": "annotation",
                        "ts": _now_iso(),
                        "text": text,
                    }) + "\n")
                    out_fp.flush()
                    print(f"    [annotated; {counter[0]} broadcasts so far]",
                          file=sys.stderr)
        finally:
            stop.set()
            print(f"\nStopped after {counter[0]} broadcasts.", file=sys.stderr)
    return 0


def _flatten(prefix: str, value: Any, out: dict[str, Any]) -> None:
    """Flatten a nested dict to dotted-key form for diffing."""
    if isinstance(value, dict):
        if not value:
            out[prefix] = "{}"
            return
        for k, v in value.items():
            _flatten(f"{prefix}.{k}" if prefix else str(k), v, out)
    elif isinstance(value, list):
        for i, v in enumerate(value):
            _flatten(f"{prefix}[{i}]", v, out)
    else:
        out[prefix] = value


def _last_broadcasts(path: Path) -> dict[str, dict[str, Any]]:
    """Return {topic: latest payload dict} from a JSONL capture."""
    latest: dict[str, dict[str, Any]] = {}
    with path.open() as fp:
        for line in fp:
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if rec.get("kind") != "broadcast":
                continue
            topic = rec.get("topic")
            payload = rec.get("payload")
            if isinstance(payload, dict):
                latest[topic] = payload
    return latest


def cmd_diff(args: argparse.Namespace) -> int:
    """Show flat-key diffs between the latest broadcast per topic."""
    a = _last_broadcasts(Path(args.left))
    b = _last_broadcasts(Path(args.right))
    topics = sorted(set(a) | set(b))
    any_diff = False
    for topic in topics:
        if topic not in a:
            print(f"+ {topic}: only in {args.right}")
            any_diff = True
            continue
        if topic not in b:
            print(f"- {topic}: only in {args.left}")
            any_diff = True
            continue
        flat_a: dict[str, Any] = {}
        flat_b: dict[str, Any] = {}
        _flatten("", a[topic], flat_a)
        _flatten("", b[topic], flat_b)
        keys = sorted(set(flat_a) | set(flat_b))
        topic_diffs = [
            (k, flat_a.get(k, "<missing>"), flat_b.get(k, "<missing>"))
            for k in keys
            if flat_a.get(k) != flat_b.get(k)
        ]
        if topic_diffs:
            any_diff = True
            print(f"\n=== {topic} ===")
            for k, l, r in topic_diffs:
                print(f"  {k}: {l!r}  →  {r!r}")
    if not any_diff:
        print("No differences.")
    return 0


def cmd_replay(args: argparse.Namespace) -> int:
    """Print the timeline grouped by annotation, one block per annotation."""
    path = Path(args.file)
    with path.open() as fp:
        for line in fp:
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            kind = rec.get("kind")
            if kind == "session_start":
                print(f"[session @ {rec['ts']} on {rec.get('host', '?')}]")
            elif kind == "annotation":
                print(f"\n>>> {rec['ts']} :: {rec['text']}")
            elif kind == "change":
                ts = rec.get("log_ts", rec.get("ts", "?"))
                short_topic = rec["topic"].rsplit("/", 1)[-1]
                hint = ", ".join(rec.get("diff", [])[:6])
                print(f"  [*] [{ts}] {short_topic}: {hint}")
            elif kind == "broadcast" and args.full:
                ts = rec.get("log_ts", rec.get("ts", "?"))
                print(f"  [{ts}] {rec['topic']}: {rec['payload']!r}")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = p.add_subparsers(dest="cmd", required=True)

    rec = sub.add_parser("record", help="record annotated broadcasts")
    rec.add_argument("--host", required=True, help="ssh target, e.g. root@192.168.178.3")
    rec.add_argument("--out", required=True, help="JSONL output path")
    rec.add_argument(
        "--verbose", "-v", action="store_true",
        help="(simple mode only) echo each broadcast on stderr",
    )
    rec.add_argument(
        "--simple", action="store_true",
        help="line-oriented mode (no curses TUI). Useful in CI / dumb terminals.",
    )
    rec.set_defaults(func=cmd_record)

    diff = sub.add_parser("diff", help="diff latest broadcast per topic between two captures")
    diff.add_argument("left")
    diff.add_argument("right")
    diff.set_defaults(func=cmd_diff)

    replay = sub.add_parser("replay", help="pretty-print a capture timeline")
    replay.add_argument("file")
    replay.add_argument(
        "--full", action="store_true",
        help="include every raw broadcast line (default: annotations + change hints only)",
    )
    replay.set_defaults(func=cmd_replay)

    args = p.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
