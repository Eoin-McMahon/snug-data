# snug-data

Snug is an app that names Irish traditional tunes as they are played and helps
you find a session. It carries two databases derived from ODbL sources. This
repository offers both, under section 4.6 of the Open Database License.

| Database | Source | Download | Reader |
|---|---|---|---|
| Tune index | thesession.org | [`snug.idx.gz`](https://github.com/Eoin-McMahon/snug-data/releases/download/tunes-2026-09-09/snug.idx.gz) | `read_tunes.py` |
| Venue database | OpenStreetMap, thesession.org session listings | [`venues.vpack.gz`](https://github.com/Eoin-McMahon/snug-data/releases/download/venues-2026-09-09/venues.vpack.gz) | `read_venues.py` |

Each file is the same bytes the app carries, gzipped. They are too large to
keep in the repository, so each one is a
[release](https://github.com/Eoin-McMahon/snug-data/releases), tagged with the
date it was built. Each release has its own README. Older releases stay up.

The readers need Python 3 and its standard library. `read_venues.py` also
needs the `zstd` command line tool. Both print counts by default and every row
with `--list`.

The venue database holds one yes or no per venue for whether thesession.org
lists a session there. No other text from thesession.org is in it.

The tune index is also under thesession.org's contents licence, in
`thesession-contents-licence.md`, which forbids processing the material with a
Large Language Model. Some of its settings are of compositions still in
copyright, which ODbL does not license. Read the tune release's README before
using it.

The `songs-*` releases are not part of this offer. `index-2026-08-19` is an
older file that combined both databases. It is kept so existing links work.

## Licences

`LICENSE.txt` is the Open Database License 1.0, which covers both databases.
`thesession-contents-licence.md` covers the material in the tune index.

Contains information from OpenStreetMap, © OpenStreetMap contributors, and
from [thesession.org](https://thesession.org), available under the Open
Database License (ODbL).

## Contact

eoin.mcmahon.personal@gmail.com
