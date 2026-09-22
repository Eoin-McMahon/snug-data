# snug-data

The databases Snug ships, offered under ODbL section 4.6. Snug is an app that
listens to Irish traditional music being played and tells you what the tune is
called, and helps you find a session to play at.

The app carries two databases derived from ODbL sources, and each is
published here as its own release, in the same bytes the app carries, with its
own reader and its own README:

| Database | Download | Reader |
|---|---|---|
| The tune index, derived from thesession.org's dump | [`snug.idx.gz`](https://github.com/Eoin-McMahon/snug-data/releases/download/tunes-2026-09-09/snug.idx.gz), release `tunes-2026-09-09` | `read_tunes.py` |
| The venue database, derived from OpenStreetMap and thesession.org's session listings | [`venues.vpack.gz`](https://github.com/Eoin-McMahon/snug-data/releases/download/venues-2026-09-09/venues.vpack.gz), release `venues-2026-09-09` | `read_venues.py` |

**The databases are release files, not files in this repository**, because
each is over GitHub's 100 MB limit for a file in a repository. The readers sit
here beside this README. thesession.org's session listings are inside the
venue database, as a yes or no per venue for whether a session is listed
there, which is what the app's map draws; `read_venues.py` counts them.

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

`songs-<date>` is not part of the ODbL offer: it is the song fingerprint pack
Snug's build fetches, and its release notes say what it holds.

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
