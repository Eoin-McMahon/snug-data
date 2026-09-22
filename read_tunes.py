#!/usr/bin/env python3
"""Reads Snug's tune index, `snug.idx`: counts and structure by default, rows
on request.

This is the reader that ships with the tune index in the ODbL offer at
github.com/Eoin-McMahon/snug-data, so it has to be enough on its own for a
recipient to get every row back out, and it needs nothing outside the Python
standard library.

    python3 read_tunes.py snug.idx                  counts and structure
    python3 read_tunes.py snug.idx --json           the same, machine readable
    python3 read_tunes.py snug.idx --list tunes     one tab separated row per tune
    python3 read_tunes.py snug.idx --list settings  one row per setting, ABC included
    python3 read_tunes.py snug.idx --list transitions

**Inside the Snug repository, never run `--list` so that its output reaches a
Claude session's context window.** The rows are thesession.org's material
under its contents licence, which forbids processing it with a Large Language
Model; see `CLAUDE.md`. Verify it by counting its output (`| wc -l`), never by
looking at it. The default mode prints no text from the file, only numbers,
and is safe to run anywhere.

The format is `crates/snug-corpus/src/artifact.rs`'s `write_tunes`, magic
`TRDX`. Every integer is little endian and every string is a `u32` byte length
followed by that many bytes of UTF-8:

    magic "TRDX", u32 version
    key scheme:        u8 shape, u32 length, u8 merges
    second key scheme: u8 shape, u32 length, u8 merges   (shape 0: none)
    u32 tunes, then per tune:
        u32 tune id, u32 tunebooks, u8 type, string name, u8 difficulty,
        u32 aliases, then a string apiece,
        u32 confusable tunes, then a u32 tune id apiece,
        u8 contour length; unless zero, that many i8 heights, then
            u8 bar count and that many u8 bar starts,
        u8 part count, u8 whether the count was worked out from the bars
    u32 settings, then per setting:
        u32 tune (a position in the tune table, not an id), u32 setting id,
        u32 intervals, then an i16 apiece (semitones between notes),
        string ABC, string contributor, string written key
    two posting tables, one per key scheme, each:
        u32 keys, then per key: u32 key, u32 hits, then per hit:
            u32 setting (a position in the setting table), u16 where in it
    u32 transition rows, then per row:
        u32 from tune id, u32 count, then per count: u32 to tune id, u32 times

A file with bytes left over, or a version this does not know, is refused: a
misparse here reports confident nonsense. `artifact.rs` has a test that fails
when `TRDX_VERSION` below stops matching the version it writes.

Core 1048.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import struct
import sys
from pathlib import Path

TRDX_MAGIC = b"TRDX"
TRDX_VERSION = 14

# `snug_core::tune::TuneType::ALL`, counting from one; zero is "not stated".
TUNE_TYPES = [
    "reel",
    "jig",
    "slip jig",
    "hornpipe",
    "polka",
    "slide",
    "waltz",
    "mazurka",
    "barndance",
    "strathspey",
    "march",
    "three-two",
    "highland",
]

# `snug_corpus::difficulty::Difficulty::ALL`, counting from one; zero is
# "not rated".
DIFFICULTIES = ["straightforward", "middling", "stretch", "handful"]

# `snug_corpus::key::KeyShape`'s codes. Above 16 is a pitch line keyed every
# `code - 16` steps.
KEY_SHAPES = {1: "exact intervals", 2: "folded intervals", 3: "contour"}
LINE_CODE = 16

U8 = struct.Struct("<B")
I8 = struct.Struct("<b")
U32 = struct.Struct("<I")


class Cursor:
    def __init__(self, blob: bytes) -> None:
        self.blob = blob
        self.at = 0

    def need(self, count: int) -> None:
        if self.at + count > len(self.blob):
            raise SystemExit(f"the file ends {self.at + count - len(self.blob)} bytes early")

    def u8(self) -> int:
        self.need(1)
        (value,) = U8.unpack_from(self.blob, self.at)
        self.at += 1
        return value

    def u32(self) -> int:
        self.need(4)
        (value,) = U32.unpack_from(self.blob, self.at)
        self.at += 4
        return value

    def skip(self, count: int) -> None:
        self.need(count)
        self.at += count

    def raw(self, count: int) -> bytes:
        self.need(count)
        value = self.blob[self.at : self.at + count]
        self.at += count
        return value

    def string_len(self) -> int:
        """Steps over a string, returning its length and nothing of it."""
        length = self.u32()
        self.skip(length)
        return length

    def string(self) -> str:
        return self.raw(self.u32()).decode("utf-8")


def scheme_name(shape: int, length: int, merges: int) -> str | None:
    if shape == 0:
        return None
    if shape > LINE_CODE:
        kind = f"pitch line, every {shape - LINE_CODE} steps"
    else:
        kind = KEY_SHAPES.get(shape, f"unknown shape {shape}")
    return f"{kind}, {length} long, {merges} merges"


def open_index(blob: bytes) -> tuple[Cursor, dict]:
    cursor = Cursor(blob)
    if cursor.raw(4) != TRDX_MAGIC:
        raise SystemExit("not a snug tune index")
    version = cursor.u32()
    if version != TRDX_VERSION:
        raise SystemExit(f"tune index is version {version}, this script reads {TRDX_VERSION}")
    first = (cursor.u8(), cursor.u32(), cursor.u8())
    second = (cursor.u8(), cursor.u32(), cursor.u8())
    return cursor, {
        "format": "TRDX",
        "artifact_version": version,
        "key_scheme": scheme_name(*first),
        "second_key_scheme": scheme_name(*second),
    }


def tune_rows(cursor: Cursor, want_text: bool):
    """Yields each tune row. With `want_text` false no string is decoded."""
    for position in range(cursor.u32()):
        tune_id = cursor.u32()
        tunebooks = cursor.u32()
        tune_type = cursor.u8()
        name = cursor.string() if want_text else cursor.string_len()
        difficulty = cursor.u8()
        aliases = [
            cursor.string() if want_text else cursor.string_len() for _ in range(cursor.u32())
        ]
        confusions = [cursor.u32() for _ in range(cursor.u32())]
        contour_len = cursor.u8()
        heights: list[int] = []
        bars: list[int] = []
        if contour_len:
            heights = [value for (value,) in I8.iter_unpack(cursor.raw(contour_len))]
            bars = list(cursor.raw(cursor.u8()))
        parts = cursor.u8()
        worked_out = cursor.u8()
        yield {
            "position": position,
            "tune_id": tune_id,
            "tunebooks": tunebooks,
            "type": TUNE_TYPES[tune_type - 1] if 0 < tune_type <= len(TUNE_TYPES) else "",
            "name": name,
            "difficulty": (
                DIFFICULTIES[difficulty - 1] if 0 < difficulty <= len(DIFFICULTIES) else ""
            ),
            "aliases": aliases,
            "confusions": confusions,
            "contour": heights,
            "bars": bars,
            "parts": parts,
            "parts_worked_out": bool(worked_out),
        }


def setting_rows(cursor: Cursor, tunes: int, want_text: bool):
    for _ in range(cursor.u32()):
        tune = cursor.u32()
        if tune >= tunes:
            raise SystemExit("a setting points at a tune that is not there")
        setting_id = cursor.u32()
        interval_count = cursor.u32()
        intervals = cursor.raw(interval_count * 2)
        if want_text:
            abc, contributor, written_key = cursor.string(), cursor.string(), cursor.string()
        else:
            abc, contributor, written_key = (
                cursor.string_len(),
                cursor.string_len(),
                cursor.string_len(),
            )
        yield {
            "tune": tune,
            "setting_id": setting_id,
            "intervals": intervals,
            "interval_count": interval_count,
            "abc": abc,
            "contributor": contributor,
            "written_key": written_key,
        }


def walk_postings(cursor: Cursor, settings: int) -> tuple[int, int]:
    keys = cursor.u32()
    hits = 0
    for _ in range(keys):
        cursor.u32()  # key
        count = cursor.u32()
        chunk = cursor.raw(count * 6)
        for at in range(0, len(chunk), 6):
            if U32.unpack_from(chunk, at)[0] >= settings:
                raise SystemExit("a posting points at a setting that is not there")
        hits += count
    return keys, hits


def transition_rows(cursor: Cursor):
    for _ in range(cursor.u32()):
        from_id = cursor.u32()
        for _ in range(cursor.u32()):
            yield from_id, cursor.u32(), cursor.u32()


def summarize(blob: bytes) -> dict:
    cursor, summary = open_index(blob)

    tunes = 0
    tunes_typed = 0
    tunes_rated = 0
    tunes_with_contour = 0
    tunes_with_parts = 0
    aliases = 0
    confusions = 0
    name_bytes = 0
    for row in tune_rows(cursor, want_text=False):
        tunes += 1
        tunes_typed += row["type"] != ""
        tunes_rated += row["difficulty"] != ""
        tunes_with_contour += bool(row["contour"])
        tunes_with_parts += row["parts"] > 0
        aliases += len(row["aliases"])
        confusions += len(row["confusions"])
        name_bytes += row["name"]

    settings = 0
    intervals = 0
    abc_bytes = 0
    tunes_with_settings: set[int] = set()
    for row in setting_rows(cursor, tunes, want_text=False):
        settings += 1
        intervals += row["interval_count"]
        abc_bytes += row["abc"]
        tunes_with_settings.add(row["tune"])

    keys, hits = walk_postings(cursor, settings)
    second_keys, second_hits = walk_postings(cursor, settings)

    transition_pairs = 0
    transitions_seen = 0
    from_tunes: set[int] = set()
    for from_id, _, times in transition_rows(cursor):
        transition_pairs += 1
        transitions_seen += times
        from_tunes.add(from_id)

    if cursor.at != len(blob):
        raise SystemExit(f"{len(blob) - cursor.at} bytes left over after the transitions")

    summary.update(
        {
            "tunes": tunes,
            "tunes_with_a_type": tunes_typed,
            "tunes_with_a_difficulty": tunes_rated,
            "tunes_with_a_contour": tunes_with_contour,
            "tunes_with_a_part_count": tunes_with_parts,
            "tunes_with_a_setting": len(tunes_with_settings),
            "aliases": aliases,
            "confusable_pairs": confusions,
            "name_bytes": name_bytes,
            "settings": settings,
            "intervals": intervals,
            "abc_bytes": abc_bytes,
            "posting_keys": keys,
            "postings": hits,
            "second_posting_keys": second_keys,
            "second_postings": second_hits,
            "transition_rows": len(from_tunes),
            "transition_pairs": transition_pairs,
            "transitions_seen": transitions_seen,
        }
    )
    return summary


def clean(text: str) -> str:
    """One field of a tab separated row: tabs and newlines would split it."""
    return text.replace("\\", "\\\\").replace("\t", "\\t").replace("\n", "\\n").replace("\r", "\\r")


def list_rows(blob: bytes, what: str, out) -> None:
    cursor, _ = open_index(blob)
    if what == "tunes":
        out.write(
            "position\ttune_id\tname\ttype\ttunebooks\tdifficulty\tparts\t"
            "parts_worked_out\taliases\tconfusable_tune_ids\tcontour\tbar_starts\n"
        )
    tunes = []
    for row in tune_rows(cursor, want_text=what == "tunes"):
        tunes.append(row["tune_id"])
        if what == "tunes":
            out.write(
                "\t".join(
                    [
                        str(row["position"]),
                        str(row["tune_id"]),
                        clean(row["name"]),
                        row["type"],
                        str(row["tunebooks"]),
                        row["difficulty"],
                        str(row["parts"]),
                        "yes" if row["parts_worked_out"] else "no",
                        " | ".join(clean(alias) for alias in row["aliases"]),
                        " ".join(str(tune) for tune in row["confusions"]),
                        " ".join(str(height) for height in row["contour"]),
                        " ".join(str(bar) for bar in row["bars"]),
                    ]
                )
                + "\n"
            )
    if what == "tunes":
        return

    if what == "settings":
        out.write("setting_id\ttune_id\twritten_key\tcontributor\tintervals\tabc\n")
    settings = 0
    for row in setting_rows(cursor, len(tunes), want_text=what == "settings"):
        settings += 1
        if what == "settings":
            intervals = " ".join(
                str(value) for (value,) in struct.iter_unpack("<h", row["intervals"])
            )
            out.write(
                "\t".join(
                    [
                        str(row["setting_id"]),
                        str(tunes[row["tune"]]),
                        clean(row["written_key"]),
                        clean(row["contributor"]),
                        intervals,
                        clean(row["abc"]),
                    ]
                )
                + "\n"
            )
    if what == "settings":
        return

    walk_postings(cursor, settings)
    walk_postings(cursor, settings)
    out.write("from_tune_id\tto_tune_id\ttimes\n")
    for from_id, to_id, times in transition_rows(cursor):
        out.write(f"{from_id}\t{to_id}\t{times}\n")


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("index", type=Path)
    parser.add_argument("--json", action="store_true", help="machine readable counts")
    parser.add_argument(
        "--list",
        choices=["tunes", "settings", "transitions"],
        help="print every row of one table as tab separated text instead of counts",
    )
    parser.add_argument(
        "--no-hash",
        action="store_true",
        help="skip the sha256, which reads the whole file a second time",
    )
    args = parser.parse_args()

    blob = args.index.read_bytes()
    if args.list:
        list_rows(blob, args.list, sys.stdout)
        return

    summary = {"bytes": len(blob)}
    if not args.no_hash:
        summary["sha256"] = hashlib.sha256(blob).hexdigest()
    summary.update(summarize(blob))

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
