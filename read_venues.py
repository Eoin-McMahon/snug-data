#!/usr/bin/env python3
"""Read Snug's venue database, `venues.vpack`.

Prints counts by default, or every venue with `--list`.

    python3 read_venues.py venues.vpack            counts
    python3 read_venues.py venues.vpack --json     counts as JSON
    python3 read_venues.py venues.vpack --list     one tab separated row per venue

The venues are OpenStreetMap places. The only thing taken from thesession.org
is a yes or no per venue for whether it lists a session there.

The file is `TRVP`: a fixed header, then blocks compressed with zstd, most of
them against a dictionary stored in the file. Python has no zstd module before
3.14, so this calls the `zstd` command line tool. The record blocks sit next to
each other in the file, and zstd decodes concatenated frames in order, so all
of them go through one `zstd -d -D <dictionary>` call.

The counts mode also reads `TRDV`, the flat, uncompressed format Snug's build
writes before packing.

A file of another version, or with bytes left over at the end, is refused.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

TRDV_MAGIC = b"TRDV"
TRDV_ARTIFACT_VERSION = 1

TRVP_MAGIC = b"TRVP"
TRVP_VERSION = 8
TRVP_HEADER_LEN = (
    4  # magic
    + 4  # version
    + 4  # venue_count
    + 4  # block_len
    + 4  # block_count
    + 8 + 4 + 4  # string table: offset, compressed len, raw len
    + 8  # website block index offset
    + 8  # record block index offset
    + (8 + 4) * 6  # the six side arrays: offset and length apiece
    + 8 + 4  # the record blocks' shared dictionary: offset, length
    + 8 + 4  # the website blocks' shared dictionary: offset, length
)

STRING_RUN = 8192
WEBSITE_BLOCK_GROUP = 64

U8 = struct.Struct("<B")
U32 = struct.Struct("<I")
U64 = struct.Struct("<Q")


class Cursor:
    def __init__(self, blob) -> None:
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

    def u64(self) -> int:
        (value,) = U64.unpack_from(self.blob, self.at)
        self.at += 8
        return value

    def varint(self) -> int:
        value = 0
        shift = 0
        while True:
            byte = self.u8()
            value |= (byte & 0x7F) << shift
            if not byte & 0x80:
                return value
            shift += 7
            if shift >= 64:
                raise SystemExit("a varint is longer than any value this format writes")

    def skip(self, count: int) -> None:
        self.at += count
        if self.at > len(self.blob):
            raise SystemExit("the file ends in the middle of a record")

    def text(self) -> int:
        length = self.u32()
        self.skip(length)
        return length

    def varint_text(self) -> int:
        length = self.varint()
        self.skip(length)
        return length


def walk_trdv(blob: memoryview) -> dict[str, int]:
    cursor = Cursor(blob)
    if bytes(cursor.blob[:4]) != TRDV_MAGIC:
        raise SystemExit("not a snug venue database")
    cursor.skip(4)
    version = cursor.u32()
    if version != TRDV_ARTIFACT_VERSION:
        raise SystemExit(
            f"venue database is version {version}, this script reads {TRDV_ARTIFACT_VERSION}"
        )

    venues = cursor.u32()
    with_street = 0
    with_website = 0
    holding_sessions = 0
    for _ in range(venues):
        cursor.skip(8)  # OSM id
        cursor.u8()  # kind
        cursor.skip(8)  # scaled latitude, scaled longitude
        cursor.skip(2)  # country
        if cursor.u8():
            holding_sessions += 1
        cursor.text()  # name
        if cursor.text():
            with_street += 1
        cursor.text()  # locality
        cursor.text()  # area
        if cursor.text():
            with_website += 1

    if cursor.at != len(cursor.blob):
        raise SystemExit(f"{len(cursor.blob) - cursor.at} bytes left over after the venues")

    return {
        "format": "TRDV",
        "artifact_version": version,
        "venues": venues,
        "venues_with_street": with_street,
        "venues_with_website": with_website,
        "venues_holding_sessions": holding_sessions,
    }


def zstd_decompress(chunk: bytes, dictionary_path: Path | None = None) -> bytes:
    if shutil.which("zstd") is None:
        raise SystemExit("zstd is not on PATH. brew install zstd")
    args = ["zstd", "-d", "-q", "-c"]
    if dictionary_path is not None:
        args += ["-D", str(dictionary_path)]
    result = subprocess.run(args, input=chunk, capture_output=True, check=False)
    if result.returncode != 0:
        raise SystemExit(f"zstd -d failed: {result.stderr.decode(errors='replace').strip()}")
    return result.stdout


def spill(chunk: bytes) -> Path:
    """Write a zstd dictionary to a temporary file, since the CLI takes a path."""
    handle = tempfile.NamedTemporaryFile(suffix=".zdict", delete=False)
    handle.write(chunk)
    handle.close()
    return Path(handle.name)


def walk_string_table(section: bytes) -> tuple[int, bytes]:
    """Decompress the string table.

    The table is varints for the string count, the run length and the run
    count, then run count + 1 u32 offsets bounding the runs, then the runs,
    each its own zstd frame.
    """
    cursor = Cursor(section)
    count = cursor.varint()
    run_len = cursor.varint()
    runs = cursor.varint()
    if run_len != STRING_RUN or runs != -(-count // max(run_len, 1)):
        raise SystemExit(
            f"the string table says {count} strings in {runs} runs of {run_len}, "
            "which does not add up"
        )
    directory = cursor.at
    raw = bytearray()
    for run in range(runs):
        start, end = struct.unpack_from("<II", section, directory + run * 4)
        piece = zstd_decompress(section[start:end])
        raw += piece
    return count, bytes(raw)


def walk_website_block(raw: bytes) -> int:
    """Count the entries in one website group.

    A group covers `WEBSITE_BLOCK_GROUP` record blocks. Each entry is a varint
    row delta and a varint length prefixed website. There is no count: the
    entries run to the end of the group.
    """
    cursor = Cursor(raw)
    count = 0
    while cursor.at < len(cursor.blob):
        cursor.varint()  # row delta
        cursor.varint_text()  # website
        count += 1
    if cursor.at != len(cursor.blob):
        raise SystemExit("a website entry ran past the end of its group")
    return count


def walk_record_blocks(raw: bytes, block_boundaries: list[int]) -> int:
    """Count the records that have a street.

    `raw` is every record block decompressed, in order, and `block_boundaries`
    is each block's decompressed length. String index 0 is the empty string.
    """
    cursor = Cursor(raw)
    with_street = 0
    for raw_len in block_boundaries:
        end = cursor.at + raw_len
        while cursor.at < end:
            cursor.varint()  # latitude delta, zigzag
            cursor.varint()  # longitude delta, zigzag
            cursor.u8()  # origin
            cursor.varint()  # numeric id
            cursor.u8()  # kind
            cursor.varint()  # locality string index
            cursor.varint()  # area string index
            cursor.varint()  # country string index
            if cursor.varint():  # street string index
                with_street += 1
            cursor.varint()  # shared prefix length with the previous name
            cursor.varint_text()  # name suffix
        if cursor.at != end:
            raise SystemExit("a record ran past the end of its block")
    if cursor.at != len(cursor.blob):
        raise SystemExit(f"{len(cursor.blob) - cursor.at} bytes left over after the blocks")
    return with_street


def trvp_header(blob: bytes) -> dict:
    if len(blob) < TRVP_HEADER_LEN or blob[:4] != TRVP_MAGIC:
        raise SystemExit("not a snug venue pack")
    cursor = Cursor(blob)
    cursor.skip(4)
    header = {"version": cursor.u32()}
    if header["version"] != TRVP_VERSION:
        raise SystemExit(
            f"venue pack is version {header['version']}, this script reads {TRVP_VERSION}"
        )
    for name, read in (
        ("venue_count", cursor.u32),
        ("block_len", cursor.u32),
        ("block_count", cursor.u32),
        ("string_table_offset", cursor.u64),
        ("string_table_clen", cursor.u32),
        ("string_table_rawlen", cursor.u32),
        ("website_block_index_offset", cursor.u64),
        ("block_index_offset", cursor.u64),
    ):
        header[name] = read()
    header["side"] = {}
    for name in ("grams", "ids", "grid", "listed", "keys", "priors"):
        header["side"][name] = (cursor.u64(), cursor.u32())
    for name, read in (
        ("dictionary_offset", cursor.u64),
        ("dictionary_len", cursor.u32),
        ("website_dictionary_offset", cursor.u64),
        ("website_dictionary_len", cursor.u32),
    ):
        header[name] = read()
    if cursor.at != TRVP_HEADER_LEN:
        raise SystemExit("the fixed header did not add up to its own declared length")
    return header


def trvp_blocks(blob: bytes, header: dict) -> list[tuple[int, int, int]]:
    """Return each record block's offset, compressed length and raw length."""
    entries = []
    at = header["block_index_offset"]
    for _ in range(header["block_count"]):
        # u64 first Morton code, u64 offset, u32 compressed length, u32 raw length
        _first_morton, offset, compressed_len, raw_len = struct.unpack_from("<QQII", blob, at)
        entries.append((offset, compressed_len, raw_len))
        at += 24
    if not entries:
        raise SystemExit("a venue pack with no record blocks")
    return entries


def walk_trvp(blob: bytes) -> dict[str, int]:
    header = trvp_header(blob)
    version = header["version"]
    venue_count = header["venue_count"]
    block_len = header["block_len"]
    block_count = header["block_count"]
    string_table_offset = header["string_table_offset"]
    string_table_clen = header["string_table_clen"]
    string_table_rawlen = header["string_table_rawlen"]
    website_block_index_offset = header["website_block_index_offset"]
    side = header["side"]
    dictionary_offset = header["dictionary_offset"]
    dictionary_len = header["dictionary_len"]
    website_dictionary_offset = header["website_dictionary_offset"]
    website_dictionary_len = header["website_dictionary_len"]

    dictionary_path = None
    if dictionary_len:
        dictionary_bytes = blob[dictionary_offset : dictionary_offset + dictionary_len]
        if len(dictionary_bytes) != dictionary_len:
            raise SystemExit("the shared dictionary falls outside the file")
        dictionary_path = spill(dictionary_bytes)

    try:
        string_table_bytes = blob[string_table_offset : string_table_offset + string_table_clen]
        string_count, string_table_raw = walk_string_table(string_table_bytes)
        if len(string_table_raw) != string_table_rawlen:
            raise SystemExit(
                f"the string table decompressed to {len(string_table_raw)} bytes, "
                f"the header says {string_table_rawlen}"
            )

        with_website = 0
        website_dictionary_path = None
        if website_dictionary_len:
            website_dictionary_path = spill(
                blob[
                    website_dictionary_offset : website_dictionary_offset
                    + website_dictionary_len
                ]
            )
        groups = -(-block_count // WEBSITE_BLOCK_GROUP)
        for group in range(groups):
            at = website_block_index_offset + group * 16
            offset, compressed_len, raw_len = struct.unpack_from("<QII", blob, at)
            if not compressed_len:
                continue
            raw = zstd_decompress(
                blob[offset : offset + compressed_len], website_dictionary_path
            )
            if len(raw) != raw_len:
                raise SystemExit("a website group decompressed to an unexpected length")
            with_website += walk_website_block(raw)

        entries = trvp_blocks(blob, header)
        first_block_offset = entries[0][0]
        blocks_span = sum(entry[1] for entry in entries)
        block_bytes = blob[first_block_offset : first_block_offset + blocks_span]
        if len(block_bytes) != blocks_span:
            raise SystemExit("the record blocks fall outside the file")
        records_raw = zstd_decompress(block_bytes, dictionary_path)
        with_street = walk_record_blocks(records_raw, [entry[2] for entry in entries])
    finally:
        if dictionary_path is not None:
            dictionary_path.unlink(missing_ok=True)

    _, listed_len = side["listed"]
    if listed_len % 4 != 0:
        raise SystemExit("the listed rows array is not a whole number of u32 rows")
    holding_sessions = listed_len // 4

    return {
        "format": "TRVP",
        "artifact_version": version,
        "venues": venue_count,
        "venues_with_street": with_street,
        "venues_with_website": with_website,
        "venues_holding_sessions": holding_sessions,
        "blocks": block_count,
        "block_len": block_len,
    }


VENUE_KINDS = [
    "pub",
    "bar",
    "restaurant",
    "cafe",
    "community centre",
    "arts centre",
    "social centre",
    "hotel",
]
ORIGINS = {0: "n", 1: "w", 2: "r"}


def clean(text: str) -> str:
    return text.replace("\\", "\\\\").replace("\t", "\\t").replace("\n", "\\n")


def varint_string(raw: bytes, cursor: Cursor) -> str:
    length = cursor.varint()
    start = cursor.at
    cursor.skip(length)
    return raw[start : start + length].decode("utf-8")


def list_trvp(blob: bytes, out) -> None:
    """Write every venue as one tab separated row, in the file's row order.

    Coordinates are stored as zigzag varint deltas of degrees times ten
    million. A name is stored as the length it shares with the previous name
    in its block, then the rest of it.
    """
    header = trvp_header(blob)
    block_len = header["block_len"]

    offset = header["string_table_offset"]
    _, string_raw = walk_string_table(blob[offset : offset + header["string_table_clen"]])
    strings = []
    cursor = Cursor(string_raw)
    while cursor.at < len(string_raw):
        strings.append(varint_string(string_raw, cursor))

    websites: dict[int, str] = {}
    website_dictionary_path = None
    if header["website_dictionary_len"]:
        start = header["website_dictionary_offset"]
        website_dictionary_path = spill(blob[start : start + header["website_dictionary_len"]])
    try:
        for group in range(-(-header["block_count"] // WEBSITE_BLOCK_GROUP)):
            at = header["website_block_index_offset"] + group * 16
            start, compressed_len, _ = struct.unpack_from("<QII", blob, at)
            if not compressed_len:
                continue
            raw = zstd_decompress(blob[start : start + compressed_len], website_dictionary_path)
            first_row = group * WEBSITE_BLOCK_GROUP * block_len
            cursor = Cursor(raw)
            row = 0
            while cursor.at < len(raw):
                row += cursor.varint()
                websites[first_row + row] = varint_string(raw, cursor)
    finally:
        if website_dictionary_path is not None:
            website_dictionary_path.unlink(missing_ok=True)

    listed_offset, listed_len = header["side"]["listed"]
    listed = {
        value for (value,) in U32.iter_unpack(blob[listed_offset : listed_offset + listed_len])
    }

    entries = trvp_blocks(blob, header)
    dictionary_path = None
    if header["dictionary_len"]:
        start = header["dictionary_offset"]
        dictionary_path = spill(blob[start : start + header["dictionary_len"]])
    try:
        first = entries[0][0]
        span = sum(entry[1] for entry in entries)
        records = zstd_decompress(blob[first : first + span], dictionary_path)
    finally:
        if dictionary_path is not None:
            dictionary_path.unlink(missing_ok=True)

    out.write(
        "row\tosm_id\tkind\tlatitude\tlongitude\tname\tstreet\tlocality\tarea\t"
        "country\tholds_sessions\twebsite\n"
    )
    cursor = Cursor(records)
    row = 0
    for block, (_, _, raw_len) in enumerate(entries):
        end = cursor.at + raw_len
        row = block * block_len
        lat = lon = 0
        name = b""
        while cursor.at < end:
            lat += unzigzag(cursor.varint())
            lon += unzigzag(cursor.varint())
            origin = cursor.u8()
            numeric = cursor.varint()
            kind = cursor.u8()
            locality, area, country, street = (strings[cursor.varint()] for _ in range(4))
            shared = cursor.varint()
            length = cursor.varint()
            name = name[:shared] + records[cursor.at : cursor.at + length]
            cursor.skip(length)
            out.write(
                "\t".join(
                    [
                        str(row),
                        f"{ORIGINS.get(origin, 'd')}{numeric}",
                        VENUE_KINDS[kind - 1] if 0 < kind <= len(VENUE_KINDS) else "",
                        f"{lat / 1e7:.7f}",
                        f"{lon / 1e7:.7f}",
                        clean(name.decode("utf-8")),
                        clean(street),
                        clean(locality),
                        clean(area),
                        clean(country),
                        "yes" if row in listed else "no",
                        clean(websites.get(row, "")),
                    ]
                )
                + "\n"
            )
            row += 1
        if cursor.at != end:
            raise SystemExit("a record ran past the end of its block")
    if row != header["venue_count"]:
        raise SystemExit(f"listed {row} venues, the header says {header['venue_count']}")


def unzigzag(value: int) -> int:
    return (value >> 1) ^ -(value & 1)


def summarize(data: bytes) -> dict[str, int]:
    if data[:4] == TRVP_MAGIC:
        return walk_trvp(data)
    if data[:4] == TRDV_MAGIC:
        return walk_trdv(memoryview(data))
    raise SystemExit("not a snug venue database: unknown magic bytes")


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("index", type=Path)
    parser.add_argument("--json", action="store_true", help="machine readable")
    parser.add_argument(
        "--list",
        action="store_true",
        help="print every venue as a tab separated row instead of counts",
    )
    parser.add_argument(
        "--no-hash",
        action="store_true",
        help="skip the sha256, which reads the whole file a second time",
    )
    args = parser.parse_args()

    data = args.index.read_bytes()
    if args.list:
        if data[:4] != TRVP_MAGIC:
            raise SystemExit("--list reads the venue pack the app ships, venues.vpack")
        list_trvp(data, sys.stdout)
        return
    summary = {"bytes": len(data)}
    if not args.no_hash:
        summary["sha256"] = hashlib.sha256(data).hexdigest()
    summary.update(summarize(data))

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
