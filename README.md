# tradar-data

This is the database Tradar searches. Tradar is an app that listens to Irish
traditional music being played and tells you what the tune is called. It is not
released yet.

None of the data is ours. It comes from thesession.org and from OpenStreetMap,
both published under the Open Database License, and folding them into one search
index makes a derived database that goes out under the same licence. ODbL section
4.6 asks that anyone given a work built from a derived database also be offered
the database itself, in a machine readable form, free over the internet. This
repository is that offer.

## The file

`tradar.idx`, one binary file, on the
[releases page](https://github.com/Eoin-McMahon/tradar-data/releases). It is
221 MB, uploaded gzipped at 93 MB.

Built 19 August 2026. The thesession.org dump was taken 15 August 2026 and the
OpenStreetMap extract 15 August 2026.

| | |
|---|---|
| Tunes | 23,199 |
| Other names those tunes are known by | 29,249 |
| Settings, each one somebody's written version of a tune | 55,006 |
| Venues | 1,866,291 |
| Venues thesession.org lists a session at | 1,267 |

sha256 of the uncompressed file:

    071f85cbfebdfcdc0f8b472ccca83881693293a5e08873ecfd0d0212db082424

## Where it comes from

The tunes, the settings, the alternative names and the session listings are from
thesession.org's data dump at
[github.com/adactio/TheSession-data](https://github.com/adactio/TheSession-data).

The venues are from OpenStreetMap, taken as a Geofabrik extract and filtered down
to public places where a session could happen.

Contains information from [thesession.org](https://thesession.org), made
available here under the Open Database License (ODbL).

Contains information from OpenStreetMap, © OpenStreetMap contributors, available
under the Open Database License (ODbL).

## Licence

Open Database License 1.0, the full text in `LICENSE.txt`. That is the licence
both upstreams use and the reason this file carries it.

Two things worth saying plainly, because they are easy to get wrong.

thesession.org's own terms on the contents ask that the material is not processed
with a large language model. That condition came from Jeremy Keith, who runs the
site, and it is worth passing on to anyone who takes a copy.

ODbL licenses a database and expressly not the rights in its contents. Plenty of
Irish traditional tunes are out of copyright, but a good number in the standard
session repertoire were written by living or recent composers, and the settings
here carry the notation. Traditional is a style, not a copyright status.

## Reading it

The format is Tradar's own. There is no library for it outside the app.

`idx_summary.py` in this repository walks the whole file, section by section, and
prints the counts in the table above. It steps over every string rather than
decoding it, so it is not a reader, but it does document the layout well enough
to write one.

    gunzip tradar.idx.gz
    python3 idx_summary.py tradar.idx

It refuses a file whose version it does not know, and it fails if there are bytes
left over at the end, so a clean run is also a check that the download is intact.

## How it was built

Three steps, in the Tradar repository, which is private.

1. Download thesession.org's CSV dumps.
2. Build the venue table from a Geofabrik OSM extract, using osmium and the tag
   list the app itself defines.
3. Fold both into the index with the app's own indexer, in release mode.

The index is deterministic by design: the same dumps through the same code give a
byte identical file. Postings and transition tables are written in sorted order
for that reason.

## Rebuilds

There is no schedule. A new release goes up when the app ships a new index, and
each one keeps the tag it was built under, so an older copy stays fetchable.

## Contact

eoin.mcmahon.personal@gmail.com
