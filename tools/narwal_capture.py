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


def cmd_record(args: argparse.Namespace) -> int:
    """Stream + annotate. Type a label + Enter to mark a moment."""
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
        help="echo each broadcast on stderr (clutters the input prompt; off by default)",
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
