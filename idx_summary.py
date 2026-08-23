#!/usr/bin/env python3
"""Reports what is in a built `tradar.idx`, as counts and nothing else.

The offer under ODbL 4.6b needs a README saying what the published file holds,
and the numbers in it have to come from the file rather than from memory. This
walks the artifact and prints counts.

It prints no text out of the index, ever. thesession.org's contents licence
forbids processing the material with a large language model, and the output of
this script lands in front of one every time an agent runs it. So every field
that holds a name, an alias, an ABC body or a contributor is measured and
stepped over. See CLAUDE.md.

    python3 scripts/idx_summary.py data/index/tradar.idx
    python3 scripts/idx_summary.py data/index/tradar.idx --json

The layout is `crates/tradar-corpus/src/artifact.rs` and it is version locked,
same as `pack_index.py`: meeting an unknown version stops rather than guesses,
because a misparse here reports confident nonsense.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import struct
import sys
from pathlib import Path

MAGIC = b"TRDX"
ARTIFACT_VERSION = 9

U8 = struct.Struct("<B")
U32 = struct.Struct("<I")
VENUE_FIXED = struct.Struct("<QBiiBBB")


class Cursor:
    """A position in the artifact, with just enough to walk it."""

    def __init__(self, blob: memoryview) -> None:
        self.blob = blob
        self.at = 0

    def u8(self) -> int:
        (value,) = U8.unpack_from(self.blob, self.at)
        self.at += 1
        return value

    def u32(self) -> int:
        (value,) = U32.unpack_from(self.blob, self.at)
        self.at += 4
        return value

    def skip(self, count: int) -> None:
        self.at += count
        if self.at > len(self.blob):
            raise SystemExit("the index ends in the middle of a record")

    def text(self) -> int:
        """Steps over a length prefixed string, returning its length only."""
        length = self.u32()
        self.skip(length)
        return length


def walk(blob: memoryview) -> dict[str, int]:
    cursor = Cursor(blob)
    if bytes(cursor.blob[:4]) != MAGIC:
        raise SystemExit("not a tradar index artifact")
    cursor.skip(4)
    version = cursor.u32()
    if version != ARTIFACT_VERSION:
        raise SystemExit(f"index is version {version}, this script reads {ARTIFACT_VERSION}")

    cursor.u8()  # key scheme shape
    key_length = cursor.u32()
    cursor.u8()  # key scheme merges

    tunes = cursor.u32()
    aliases = 0
    contours = 0
    for _ in range(tunes):
        cursor.skip(8)  # id, tunebooks
        cursor.u8()  # tune type
        cursor.text()  # name
        cursor.u8()  # difficulty
        for _ in range(cursor.u32()):
            cursor.text()  # alias
            aliases += 1
        cursor.skip(4 * cursor.u32())  # confusions
        heights = cursor.u8()
        if heights:
            contours += 1
            cursor.skip(heights)
            cursor.skip(cursor.u8())
        cursor.u8()  # parts

    settings = cursor.u32()
    intervals = 0
    abc_bytes = 0
    for _ in range(settings):
        cursor.skip(8)  # tune, setting id
        count = cursor.u32()
        intervals += count
        cursor.skip(2 * count)
        abc_bytes += cursor.text()
        cursor.text()  # contributor
        cursor.text()  # written key

    postings = cursor.u32()
    positions = 0
    for _ in range(postings):
        cursor.skip(4)  # key
        count = cursor.u32()
        positions += count
        cursor.skip(4 * count)

    transitions_from = cursor.u32()
    transitions = 0
    for _ in range(transitions_from):
        cursor.skip(4)  # tune
        count = cursor.u32()
        transitions += count
        cursor.skip(8 * count)

    venues = cursor.u32()
    with_sessions = 0
    with_website = 0
    for _ in range(venues):
        head = VENUE_FIXED.unpack_from(cursor.blob, cursor.at)
        cursor.skip(VENUE_FIXED.size)
        if head[6]:
            with_sessions += 1
        cursor.text()  # name
        cursor.text()  # locality
        cursor.text()  # area
        if cursor.text():
            with_website += 1

    if cursor.at != len(cursor.blob):
        raise SystemExit(f"{len(cursor.blob) - cursor.at} bytes left over after the venue table")

    return {
        "artifact_version": version,
        "key_length": key_length,
        "tunes": tunes,
        "aliases": aliases,
        "tunes_with_contour": contours,
        "settings": settings,
        "intervals": intervals,
        "abc_bytes": abc_bytes,
        "postings_keys": postings,
        "posting_positions": positions,
        "transition_sources": transitions_from,
        "transition_pairs": transitions,
        "venues": venues,
        "venues_holding_sessions": with_sessions,
        "venues_with_website": with_website,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("index", type=Path)
    parser.add_argument("--json", action="store_true", help="machine readable")
    parser.add_argument(
        "--no-hash",
        action="store_true",
        help="skip the sha256, which reads the whole file a second time",
    )
    args = parser.parse_args()

    data = args.index.read_bytes()
    summary = {"bytes": len(data)}
    if not args.no_hash:
        summary["sha256"] = hashlib.sha256(data).hexdigest()
    summary.update(walk(memoryview(data)))

    if args.json:
        json.dump(summary, sys.stdout, indent=2)
        sys.stdout.write("\n")
        return
    width = max(len(key) for key in summary)
    for key, value in summary.items():
        printed = f"{value:,}" if isinstance(value, int) else value
        print(f"{key.ljust(width)}  {printed}")


if __name__ == "__main__":
    main()
