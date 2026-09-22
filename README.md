# snug-data

The databases Snug ships, offered under ODbL section 4.6. Snug is an app that
listens to Irish traditional music being played and tells you what the tune is
called, and helps you find a session to play at.

The app carries two databases derived from ODbL sources, and each is
published here as its own release, in the same bytes the app carries, with its
own reader and its own README:

| Release | File | Derived from | Reader |
|---|---|---|---|
| `tunes-<date>` | `snug.idx.gz`, the tune index | thesession.org's dump | `read_tunes.py` |
| `venues-<date>` | `venues.vpack.gz`, the venue database | OpenStreetMap, and thesession.org's session listings | `read_venues.py` |

The date is the day the database was built. They are on the
[releases page](https://github.com/Eoin-McMahon/snug-data/releases), and an
older release stays fetchable when a newer one goes up.

**The tune index carries thesession.org's contents licence as well as ODbL**,
in `thesession-contents-licence.md`. It forbids processing the material with a
Large Language Model. Read the tune release's README before using that file:
some of the settings in it are of compositions still in copyright, and ODbL
does not license those.

Both readers need Python 3 and nothing outside its standard library, except
that `read_venues.py` shells out to the `zstd` command line tool. Each prints
counts by default and every row with `--list`.

`index-2026-08-19` is an older, combined file from before the two databases
were split, superseded by the per-database releases and kept only so a link to
it still works.

## Licences

`LICENSE.txt` is the Open Database License 1.0, which covers both databases.
`thesession-contents-licence.md` is thesession.org's contents licence, which
covers the material in the tune index.

Contains information from OpenStreetMap, © OpenStreetMap contributors, and
from [thesession.org](https://thesession.org), available under the Open
Database License (ODbL).

## Contact

eoin.mcmahon.personal@gmail.com
