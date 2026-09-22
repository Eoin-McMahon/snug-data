#!/usr/bin/env python3
"""Reports what is in a built venue database, as counts and nothing else.

The offer under ODbL 4.6b needs a README saying what the published file holds,
and the numbers in it have to come from the file rather than from memory. This
walks the venue database and prints counts.

It prints no text out of the file, ever. The venue database holds no thesession
material, but `holds_sessions` is set by matching against thesession's session
listings (`snug-cli venue-listings`), and this script's whole reason for
existing is to be trusted with material under that licence without needing a
human to re-check it every run. So the rule that nothing but a count leaves
this script stays exactly as it was when the file held both databases: every
field that holds a name, a street, a locality or a website is measured and
stepped over. See CLAUDE.md.

    python3 scripts/measure/idx_summary.py data/index/venues.vpack
    python3 scripts/measure/idx_summary.py data/index/venues.vpack --json

Reads either of the two formats `crates/snug-corpus` writes, chosen by the
file's own magic bytes:

- `TRVP`, `crates/snug-corpus/src/venue_pack.rs`. What the app bundles and
  what the ODbL offer publishes, since core 829. Block-compressed against a
  shared zstd dictionary, so this script shells out to the `zstd` command line
  tool to decompress; there is no zstd module in the Python standard library
  before 3.14. `zstd -d` on a bare frame handles the string table and the
  website block, which carry no dictionary; the record blocks are one `zstd -d
  -D <dictionary>` over every block's compressed bytes concatenated, which
  works because they sit contiguous in the file and zstd decodes concatenated
  frames in sequence, so this is one process rather than thousands.
- `TRDV`, `crates/snug-corpus/src/artifact.rs`. The flat format `snug
  build-index --venues-out` still writes to `data/index/venues.idx`, kept
  readable here because it is still a real, still-used file: a comparison
  target for checking a pack was built from the same rows, and the only format
  this script needed to read before core 829. It is a build intermediate now,
  not what the app ships or what the offer publishes.

Both are version locked: meeting an unknown version stops rather than
guesses, because a misparse here reports confident nonsense.

Core 813, ADR-0018: the venue database left the tune index for its own
artifact (magic `TRDV`). Core 810 repointed this script at that file, since the
ODbL offer covers the venue database and never covered the tune corpus this
script used to walk. Core 823 made the phone read `venue_pack` instead, and
core 829 is what taught this script the format the app and the offer actually
carry.
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

# `venue_pack.rs`'s own constants, and the reason this file breaks when they
# move. Version 6 to 8 was two units on one day, 5f1e6b933 paging the string
# table and 397cbaaef adding the sixth side array, and neither moved this
# reader. It went unnoticed for four days because nothing runs it: core 957.
STRING_RUN = 8192
WEBSITE_BLOCK_GROUP = 64

U8 = struct.Struct("<B")
U32 = struct.Struct("<I")
U64 = struct.Struct("<Q")


class Cursor:
    """A position in a blob, with just enough to walk it."""

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
        """Steps over a length prefixed string, returning its length only."""
        length = self.u32()
        self.skip(length)
        return length

    def varint_text(self) -> int:
        """As `text`, but the length prefix is a varint, not a fixed `u32`."""
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
    """Shells out to the `zstd` command line tool, since Python before 3.14
    carries no zstd module. A missing binary is refused with a message naming
    what to install rather than a bare `FileNotFoundError`."""
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
    """A zstd dictionary on disk, because the CLI wants a path."""
    handle = tempfile.NamedTemporaryFile(suffix=".zdict", delete=False)
    handle.write(chunk)
    handle.close()
    return Path(handle.name)


def walk_string_table(section: bytes) -> tuple[int, bytes]:
    """The paged string table: a count, the run length, a run count, a
    directory of run offsets, then one independently compressed run apiece.

    Paged since version 7, so that opening a pack materialises no strings at
    all and a query decompresses the one run its answer sits in. A reader that
    decompresses the section in one pass, which is what this did until core
    957, gets nothing: the section is not a zstd frame, it is a directory of
    them.
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
    """One website group: entries of a delta-varint row and a length-prefixed
    string, run to the end.

    A group covers `WEBSITE_BLOCK_GROUP` record blocks, and it carries no count
    of its own: the Rust walks it until the bytes run out, so a count would be
    a second thing to keep true. Version 6 did carry one, which is why this
    read a count and then found a quarter of a megabyte left over.
    """
    cursor = Cursor(raw)
    count = 0
    while cursor.at < len(cursor.blob):
        cursor.varint()  # row delta
        cursor.varint_text()  # website
        count += 1
    if cursor.at != len(cursor.blob):
        raise SystemExit(f"a website entry ran past the end of its group")
    return count


def walk_record_blocks(raw: bytes, block_boundaries: list[int]) -> int:
    """Every record block, concatenated by the caller in block order and
    decompressed in one pass. Walks each record's fields, in the order
    `venue_pack::encode_block` writes them, far enough to tell whether its
    street index is the empty string (index 0, shared by every field that
    interned nothing) without resolving any string. Returns how many carry a
    street.

    `block_boundaries` is each block's raw length, so a record never reads
    across a block it did not start in even though nothing here needs the
    boundary for correctness: every field is length prefixed or fixed width,
    so a record can only ever consume exactly its own bytes.
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


def walk_trvp(blob: bytes) -> dict[str, int]:
    if len(blob) < TRVP_HEADER_LEN or blob[:4] != TRVP_MAGIC:
        raise SystemExit("not a snug venue pack")
    cursor = Cursor(blob)
    cursor.skip(4)
    version = cursor.u32()
    if version != TRVP_VERSION:
        raise SystemExit(f"venue pack is version {version}, this script reads {TRVP_VERSION}")
    venue_count = cursor.u32()
    block_len = cursor.u32()
    block_count = cursor.u32()
    string_table_offset = cursor.u64()
    string_table_clen = cursor.u32()
    string_table_rawlen = cursor.u32()
    website_block_index_offset = cursor.u64()
    block_index_offset = cursor.u64()
    side = {}
    for name in ("grams", "ids", "grid", "listed", "keys", "priors"):
        side[name] = (cursor.u64(), cursor.u32())
    dictionary_offset = cursor.u64()
    dictionary_len = cursor.u32()
    website_dictionary_offset = cursor.u64()
    website_dictionary_len = cursor.u32()
    if cursor.at != TRVP_HEADER_LEN:
        raise SystemExit("the fixed header did not add up to its own declared length")

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

        entries = []
        at = block_index_offset
        for _ in range(block_count):
            # first_morton (u8; 8), offset (u8; 8), compressed_len (u32), raw_len (u32)
            first_morton, offset, compressed_len, raw_len = struct.unpack_from(
                "<QQII", blob, at
            )
            entries.append((offset, compressed_len, raw_len))
            at += 24
        if not entries:
            raise SystemExit("a venue pack with no record blocks")
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

    listed_offset, listed_len = side["listed"]
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


def summarize(data: bytes) -> dict[str, int]:
    if data[:4] == TRVP_MAGIC:
        return walk_trvp(data)
    if data[:4] == TRDV_MAGIC:
        return walk_trdv(memoryview(data))
    raise SystemExit("not a snug venue database: unknown magic bytes")


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
