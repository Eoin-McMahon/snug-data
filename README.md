# snug-data

This is the venue database Snug searches to help a user find a session.
Snug is an app that listens to Irish traditional music being played and
tells you what the tune is called. It is not released yet.

None of the data is ours. The venues come from OpenStreetMap, published under
the Open Database License, and which of them hold a session is cross-checked
against thesession.org's own listings, published under the same licence.
Folding the two into one searchable database makes a derived database that
goes out under the same licence. ODbL section 4.6 asks that anyone given a
work built from a derived database also be offered the database itself, in a
machine readable form, free over the internet. This repository is that offer.

**This is the venue database alone.** Snug's tune corpus, the settings and
the notation, is a separate file under thesession.org's own contents licence,
which asks that the material not be processed with a large language model.
That file has never been what ODbL 4.6 is about, and this repository does not
carry it.

## The file

`venues.vpack`, one binary file, on the
[releases page](https://github.com/Eoin-McMahon/snug-data/releases). It is
the same bytes the app itself carries, block-compressed against a shared
dictionary rather than a flat record per venue, and 211 MB, uploaded
gzipped at 162 MB.

Built 9 September 2026 from an OpenStreetMap extract taken 9 September 2026, cross-referenced
against a thesession.org session listing dump taken 15 August 2026 to mark which
venues hold one.

| | |
|---|---|
| Venues | 3,106,447 |
| Venues thesession.org lists a session at | 1,342 |
| Venues with a website | 693,451 |

sha256 of the uncompressed file:

    3da959a714e30952f35be72bd492c3d437dce30b94839bb9cceb38e98bf23219

## Where it comes from

Every public place is from OpenStreetMap, taken as a Geofabrik extract and
filtered down to the kinds of place a session could plausibly happen in: pubs,
bars, community and arts centres, and the like.

Which of those places thesession.org has a listed session at comes from its
data dump at
[github.com/adactio/TheSession-data](https://github.com/adactio/TheSession-data),
matched to a venue by name and by distance. That match produces one boolean
per venue and nothing else: no session name, no date, no text from the dump
travels into this file.

Contains information from OpenStreetMap, © OpenStreetMap contributors,
available under the Open Database License (ODbL).

Contains information from [thesession.org](https://thesession.org), made
available here under the Open Database License (ODbL).

## Licence

Open Database License 1.0, the full text in `LICENSE.txt`. That is the licence
both upstreams use and the reason this file carries it.

ODbL licenses a database and expressly not the rights in its contents. Nothing
in this file is copyrightable subject matter in the way a tune setting is: it
is places, coordinates and a website link.

## Reading it

The format is Snug's own. There is no library for it outside the app.

`idx_summary.py` in this repository walks the whole file and prints the counts
in the table above. Blocks of records are compressed against a shared zstd
dictionary carried in the file's own header, so the script shells out to the
`zstd` command line tool (`brew install zstd`, or your package manager's
equivalent) to decompress rather than reimplementing zstd itself; nothing else
it needs is outside the Python standard library. It steps over every name,
street, locality and website rather than decoding them, so it is not a reader,
but it documents the layout well enough to write one.

    gunzip venues.vpack.gz
    python3 idx_summary.py venues.vpack

It refuses a file whose version it does not know, and it fails if there are
bytes left over at the end, so a clean run is also a check that the download is
intact.

## How it was built

Three steps, in the Snug repository, which is private.

1. Fetch a Geofabrik OpenStreetMap extract and filter it with osmium, using the
   tag list the app itself defines.
2. Download thesession.org's `sessions.csv` and match its listings to venues by
   name and by distance.
3. Fold both into the venue database with the app's own indexer, in release
   mode.

The database is deterministic by design: the same extract and the same
listings through the same code give a byte identical file.

## Rebuilds

There is no schedule. A new release goes up when the app ships a new venue
database, and each one keeps the tag it was built under, so an older copy
stays fetchable.

## Contact

eoin.mcmahon.personal@gmail.com
