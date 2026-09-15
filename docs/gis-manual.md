# The GIS component

SurveyHQ's GIS component exists to answer one question the survey data cannot
answer on its own:

> Was this interview collected in the area the interviewer said it was?

Everything else here - reading boundary files, drawing outlines under a map,
colouring pins - is in service of that. This manual covers the whole of it:
what to give it, how to set it up, how to read what it tells you, and what it
deliberately does not do.

It assumes you can already add a dashboard and a widget. If you cannot, read
[the user guide](user-guide.md) first.

---

## Contents

1. [What it is, and what it is not](#1-what-it-is-and-what-it-is-not)
2. [Preparing the boundary file](#2-preparing-the-boundary-file)
3. [Adding a boundary layer](#3-adding-a-boundary-layer)
4. [Putting a map on a dashboard](#4-putting-a-map-on-a-dashboard)
5. [Drawing boundaries under the pins](#5-drawing-boundaries-under-the-pins)
6. [Checking the recorded area against the GPS](#6-checking-the-recorded-area-against-the-gps)
7. [How codes are compared](#7-how-codes-are-compared)
8. [Acting on what the map shows](#8-acting-on-what-the-map-shows)
9. [How the pins are drawn](#9-how-the-pins-are-drawn)
10. [The ground under the map](#10-the-ground-under-the-map)
11. [Limits](#11-limits)
12. [Troubleshooting](#12-troubleshooting)
13. [For administrators](#13-for-administrators)
14. [For automation: the API](#14-for-automation-the-api)

---

## 1. What it is, and what it is not

**What it is.** A store of boundary layers - the frame fieldwork is organised
into - and a map widget that draws interview locations against them and reports
where the two disagree.

**What it is not.** It is not a GIS. There is no editing, no digitising, no
buffering, no spatial join beyond point-in-polygon, no projection, no topology
checking, no raster. If you need those, do them in QGIS and bring the result
here.

That narrowness is deliberate and has a payoff worth knowing about: **reading a
boundary file needs no GIS software on the server and no internet access.**
There is no GDAL, no PostGIS, no DuckDB spatial extension, no `pyproj`. A
GeoPackage is a SQLite file and a shapefile is a documented binary format, so
both are read where they sit. A statistics office behind a ministry firewall is
exactly where this platform is meant to run, and a feature that quietly needs a
download the first time somebody uses it is a feature that fails there.

The one part that does need the internet is the **map tiles** - the photograph
or street map under the pins. See [section 10](#10-the-ground-under-the-map).

---

## 2. Preparing the boundary file

This section is for whoever exports the frame from your GIS. Get it wrong and
the symptoms are confusing, so it is worth reading before you export.

### The coordinates must be longitude and latitude in degrees

**This is the one that catches people.** SurveyHQ does no reprojection at all.
It compares your boundary coordinates directly against the GPS readings on the
devices, and those are WGS84 degrees.

Export as **EPSG:4326 / WGS84 geographic coordinates**.

If you export in a national projected system - UTM, a local grid, anything in
metres - the layer will upload without complaint, it will list the right number
of areas, and then:

- the outlines will not appear anywhere near your fieldwork, and
- **every single record will be reported as "outside every area"**.

A `.prj` file in the zip does not save you. It is carried along for the reader
but nothing reprojects from it.

The quick way to check before you upload: open the file's bounding box. For a
country it should be a pair of small numbers that look like a longitude and a
latitude, e.g. `168.1 to 170.2` and `-20.3 to -13.1`. If you see numbers in the
hundreds of thousands, it is projected and needs converting. In QGIS: right
click the layer, **Export → Save Features As…**, set CRS to **EPSG:4326**.

### The file must contain areas

Polygons and multipolygons only. A file of points or of lines is a different
thing that happens to be geographic; it will be refused rather than silently
producing a layer that draws nothing. Anything that is not an area inside an
otherwise-good file is skipped.

### The attribute table must carry the code you want to match on

The whole area check rests on one column of your boundary file holding the same
enumeration-area code the questionnaire records. Make sure it is in the export,
and make a note of what it is called - you will pick it by name later. Keeping
a human-readable name column too is worth it: it is what gets written on the
map.

### The three formats

| Format | Export as | Notes |
|---|---|---|
| **GeoJSON** | `.geojson` or `.json` | Simplest. A `FeatureCollection`, a single `Feature`, or a bare geometry all work. |
| **GeoPackage** | `.gpkg` | Read as the SQLite database it is. If it holds several spatial layers, the first is taken unless one is named. |
| **Shapefile** | a `.zip` | Must contain at least the `.shp` and the `.dbf`. Include `.shx`, `.prj` and `.cpg` if you have them. |

A shapefile without its `.dbf` is refused: the `.dbf` is the attribute table,
so without it the layer carries no codes and no names and there is nothing to
match against.

---

## 3. Adding a boundary layer

**Datasets → Boundaries → Add boundaries.**

You need the **manager** role or above to add or delete a layer. Anyone signed
in can see the layers their projects can reach and build maps on them.

| Field | What to put |
|---|---|
| **File** | The `.geojson`, `.gpkg` or `.zip` from section 2. |
| **Name** | What people will pick from a list, e.g. `Enumeration areas 2026`. Defaults to the filename. |
| **Description** | Optional. Which frame this is and when it was drawn. Worth filling in once you have more than one. |
| **Project** | Leave **shared** for a national frame every survey works to. Give it a project when the layer was drawn for that survey alone. |

On **Add layer** the file is read, converted to GeoJSON, and stored. The
confirmation names how many areas were found - **check that number against what
you expected.** A frame that should have 4,182 enumeration areas and reports
3,900 lost something in the export.

The list then shows each layer with its area count, its attribute names, and
the format it arrived as. The attribute names are shown on purpose: they are
what you will pick from when setting up the map, so you can see them before you
open the widget.

**Sharing.** A layer in the shared area is offered to every project. A layer
given to a project is offered to that project only - but filtering the list by
project still shows the shared ones, because a national frame is uploaded once
and used by every round that works to it.

**Deleting.** Deleting a layer stops every map drawing it from showing outlines
and from checking recorded areas. The maps keep working as plain maps. Deleting
the *project* a layer belongs to does not delete the layer: it moves to the
shared area.

**Replacing.** There is no in-place replace. Upload the new frame as a new
layer, point the maps at it, then delete the old one. That ordering means no
map is ever briefly pointing at nothing.

---

## 4. Putting a map on a dashboard

**Add widget → Map of interview locations.**

| Setting | What it does |
|---|---|
| **Latitude** / **Longitude** | The variables holding the device's reading. Only numeric variables are offered. |
| **What each pin counts** | How many records, or the total / average / highest / lowest of a variable. |
| **Show on click** | Up to six variables, listed in the popup when a pin is clicked. Put the interviewer's name here: it is what turns a red pin into somebody to ask. |

> **Choose "Show on click" carefully when you add the widget.** It is the one
> map setting that is not on the **✎** panel afterwards, so changing it means
> deleting the widget and adding it again.

### If the GPS arrived as one column

Not every export gives you two columns. ODK Central writes a whole reading into
a single field - `-17.7333 168.3273 42.0 5.0`, being latitude, longitude,
altitude and accuracy - a hand-assembled CSV often holds `-17.7333,168.3273`,
and a database extract can hold `POINT(168.3273 -17.7333)` or a GeoJSON point.
All of those arrive as text, and the **Latitude** and **Longitude** lists offer
numeric variables only, so the reading was in the dataset and unreachable.

**SurveyHQ splits such a column on import.** A column named `gps` holding any of
those forms gains two numeric columns beside it:

| Column | Holds |
|---|---|
| `gps__latitude` | The latitude, as a number |
| `gps__longitude` | The longitude, as a number |

The original column is kept as it was. The two new ones are what you choose in
**Latitude** and **Longitude**, and because of how they are named the platform
also finds them by itself for field progress and for **Data quality > Missing
GPS**. The import notes say which columns were split.

Three things worth knowing:

- **An existing dataset does not gain the columns retrospectively.** The split
  happens when a file is read, so import the file again - or wait for the next
  sync on a connection - and the columns appear.
- **The order is worked out, not assumed.** WKT and GeoJSON put longitude first
  by specification and are read that way. A bare pair is read latitude first,
  which is what ODK, Survey Solutions and every handheld write; and a bare pair
  whose first number is past 90 cannot be a latitude, so it is read the other
  way round rather than plotted in the wrong ocean.
- **A column is split only when it really is coordinates.** At least nine in ten
  sampled values have to parse as a point, and most have to carry decimals. A
  column of small whole-number pairs - a score and a rank, say - is a legal
  coordinate on paper and nonsense on a map, so it is left alone.

A value that does not parse leaves that row with no coordinates, which is what
**Missing GPS** counts. It is not turned into `0, 0`.

Pins are **places, not rows**. The server groups by coordinate before it sends
anything, so several interviews at one household are one pin carrying a number,
rather than a pile of pins hiding each other. Clicking a pin tells you the
number and shows the detail columns the widget carries.

Records with no coordinate are left out, and so are two cases that are not
places:

- a latitude or longitude outside the legal range, and
- exactly `0, 0` - Null Island, which is what a device with no fix records.

If you want to *count* the records with no usable coordinate rather than just
drop them, that is a data-quality check rather than a map: **Data quality →
Missing GPS** counts rows where either coordinate is null or both are zero.

---

## 5. Drawing boundaries under the pins

On the map widget's settings (**✎**):

- **Boundaries** - the layer to draw. The list shows each layer's area count.
- **Write on each area** - which attribute names an area. Hovering an area then
  shows that name. Leave it as **Nothing** for outlines with no labels.

Outlines are drawn as outlines, not filled, so the ground stays visible on the
satellite view. They are always drawn *under* the pins.

**The map frames itself on the layer, not on the pins,** once a layer is
chosen. This is deliberate: one coordinate recorded in the wrong hemisphere
would otherwise squeeze the whole survey into a thumbnail to keep that single
mistake on screen. The legend still counts the strays, which is how you know to
zoom out and look for them.

**Turning the outlines off while reading.** The layers box in the map's top
right corner - the one that chooses the ground - also carries a tick-box for
the boundary layer by name. Untick it and the outlines go; tick it and they
come back, under the pins where they were.

This is a reader's control rather than a setting, and that is the point:
"which of these pins is on the wrong side of the line" is a question you answer
by taking the line off and putting it back. Anyone looking at the dashboard can
do it, including on a shared link, without being able to edit the widget.

---

## 6. Checking the recorded area against the GPS

This is what the boundaries are really for.

A household listing records the enumeration area the interviewer says they were
in. The device records where they actually were. Those two disagreeing is one
of three things, and each is worth knowing **during** fieldwork rather than
after it:

- an EA code typed wrong,
- an interviewer working the wrong area, or
- a boundary the field staff read differently from the office.

### Setting it up

Three things have to be set together. Any one missing and the map is just a
map.

| Setting | What to choose |
|---|---|
| **Boundaries** | The layer to check against. |
| **Recorded area** | The variable holding the code the interviewer recorded. |
| **Matched against** | The attribute on the boundary layer holding the same code. |

If you set **Recorded area** but leave **Matched against** empty, the widget
warns you, because the result would be every record in the country reported as
a mismatch.

### Reading the result

Every pin is coloured by its verdict, and the legend counts each one. Only
verdicts actually present are listed.

| Colour | Verdict | What it means |
|---|---|---|
| **Red**, largest | Area does not match the GPS | The finding. The recorded code is not the area the point falls in. |
| **Amber** | Outside every area in the layer | The point is not in any area in this layer at all. |
| **Purple** | No area recorded | The record has a GPS reading but no area code. |
| **Green**, smallest | Area agrees with the GPS | The quiet majority. |

The sizing is on purpose: a screen of small green dots with four large red ones
reads correctly at a glance, rather than needing to be counted.

**Amber is not a mismatch,** and is kept separate deliberately. A point outside
every area is usually a frame that does not cover an island yet, or a
coordinate in the wrong hemisphere. Folding those in with the real mismatches
would bury them.

**If everything is amber**, the layer is almost certainly in the wrong
coordinate system. See [section 2](#2-preparing-the-boundary-file).

### Clicking a pin

The popup says:

- what the pin counts, and how many records are behind it,
- the verdict, in its colour,
- the area the record says it was in - by its label, not its code, where the
  variable has value labels,
- the area it actually falls in, and
- whatever **Show on click** variables the widget carries, which is where the
  interviewer's name belongs so you know who to ask.

Two households at one coordinate naming *different* enumeration areas stay two
pins rather than one, because that disagreement is itself the finding and
merging them would average it away.

---

## 7. How codes are compared

Codes are compared by what identifies them, not by how they were typed. A code
crosses from a questionnaire to a GIS file as text on one side and a number on
the other, and often with leading zeros on whichever side was written by
somebody who knew they mattered.

These are all treated as the same enumeration area:

| Recorded | Boundary attribute | Match |
|---|---|---|
| `"7"` | `"007"` | yes |
| `7` (a number) | `"007"` | yes |
| `7.0` | `"7"` | yes |
| `"007"` | `"7"` | yes |
| `"008"` | `"007"` | no |

The rules, exactly:

- Leading zeros are stripped, **but only from something that is entirely
  digits**, so a code like `0A1` is left alone and compared as it is.
- Text is compared case-insensitively.
- Whitespace at either end is ignored.
- A blank, or nothing at all, counts as **no area recorded** (purple) rather
  than as a mismatch.

---

## 8. Acting on what the map shows

A worked routine for a fieldwork monitor, once a day:

1. Open the map. Read the legend first, not the map: it counts each verdict.
2. **Amber across the whole survey** means a setup problem, not a field
   problem. Check the layer's coordinate system and that **Matched against**
   names the right attribute.
3. **Red clustered in one place** is usually one interviewer or one boundary
   being read differently on the ground. Click a few and see whether they name
   the same interviewer.
4. **Red scattered thinly everywhere** is usually typing. Look at whether the
   recorded codes are near-misses of the true ones.
5. Use the dashboard's filters to narrow to a supervisor or a date range -
   filters apply to the map like any other widget - and see whether the pattern
   follows a person or a week.
6. **Fill the window**, on the widget's menu, gives you the whole screen for
   the map when you are actually working through pins.

Doing this daily rather than at the end is the entire value: an EA code typed
wrong is a five-minute correction during fieldwork and a permanent hole in the
frame afterwards.

---

## 9. How the pins are drawn

All on the widget's settings (**✎**). The defaults are reasonable; these are
for when they are not.

| Setting | Notes |
|---|---|
| **Point shape** | Circle, square, triangle, diamond, pentagon. |
| **Point colour** | Any colour. The outline is derived from it automatically. |
| **Point size** | 6 to 40 pixels - the size before the value scales it. |
| **Point transparency** | 10% to 100%. Low values let a crowd of overlapping pins read as density rather than one blob. |
| **Bigger pins where the number is bigger** | On by default. |

**Shape versus colour.** A circle is right when the size of the pin carries a
quantity, because a circle's area reads as an amount. A shape is right when the
map answers "what happened here", because shapes are told apart at a glance and
in a photocopy, which two shades of one colour are not.

**Size is by area, not radius.** Doubling a circle's radius quadruples what the
eye reads off it, so the value scales the area. The largest pin on the map sets
the scale, so one busy cluster cannot shrink everything else to an unclickable
dot.

**When the area check is on, point styling is ignored.** Every pin is drawn at
the size its verdict says, and only the colour speaks. Size would be a second
variable competing with the colour that carries the answer.

Turn **Bigger pins where the number is bigger** off when the question is *where
the work reached* rather than *how much of it there was*.

---

## 10. The ground under the map

Three grounds, chosen on the widget and switchable by any reader from the
control in the map's top right corner:

- **Streets** - OpenStreetMap. The default.
- **Satellite** - aerial imagery, with place names and boundaries drawn over it
  as a transparent layer, so a cluster of pins still reads as a village rather
  than an unlabelled shape. The two move together.
- **Terrain** - contours and relief, for fieldwork where what matters is the
  ground between two points.

A reader's choice lasts as long as they have the page open. The one saved on
the widget is what everybody starts on.

**All three fetch tiles from the internet.** This is the only part of the GIS
component that needs it. A server that cannot reach the tile hosts still draws
the pins, on a plain ground, and says so under the map. That is degraded, not
broken.

**Your own tile server.** **Map tiles** takes a URL template and replaces all
three. The switcher disappears with them, since a choice between hosts this
server cannot reach is no choice at all. Use this for an offline deployment
with a local tile service.

---

## 11. Limits

| Limit | Value | What happens, and what to do |
|---|---|---|
| Areas in one layer | **20,000** | Refused on upload, naming the count. Load the level above it, or split the frame by region into several layers. |
| Places on one map | **50,000** | Drawn in descending order of value; the rest are dropped and the map says "showing the busiest only" under it. Filter the dashboard to narrow it. |
| Upload size | **`MAX_UPLOAD_MB`**, 512 MB by default | Refused, naming the limit. |

The 50,000 counts distinct *places*, not interviews, because points are grouped
by coordinate first. A census that enumerates every household at its own GPS
reading will still reach it for a large province.

---

## 12. Troubleshooting

### On upload

| Message | Cause |
|---|---|
| `Boundaries can be read from GeoJSON, a GeoPackage, or a zipped shapefile` | The file extension is none of `.geojson`, `.json`, `.gpkg`, `.zip`. A bare `.shp` is not enough; zip it with its `.dbf`. |
| `This zip holds no .shp file` | The zip is not a shapefile, or the `.shp` is nested somewhere unexpected. |
| `This shapefile has no .dbf, so it carries no area names` | The `.dbf` was left out of the zip. It is the attribute table; without it there is nothing to match on. |
| `This file is not a GeoPackage: it has no geometry columns table` | A `.gpkg` that is a plain SQLite database rather than a GeoPackage. |
| `This GeoPackage holds no spatial layers` | Valid GeoPackage, no spatial tables in it. |
| `This is not readable GeoJSON` / `This JSON is not a GeoJSON feature collection` | Not JSON, or JSON that is not GeoJSON. |
| `No areas were found in this file` | The file was read but contained no polygons - commonly a layer of points or lines. |
| `This layer has N areas, more than the 20,000 a map can draw` | See [Limits](#11-limits). |

### On the map

| Symptom | Likely cause |
|---|---|
| Everything is amber, "outside every area" | The layer is in a projected CRS. See [section 2](#2-preparing-the-boundary-file). |
| Everything is red | **Matched against** names the wrong attribute - one that holds a name, or an ID that is not the recorded code. |
| No outlines at all | No **Boundaries** layer chosen, the layer was deleted, or a reader unticked it in the layers box. |
| No colours on the pins | The area check needs all three of **Boundaries**, **Recorded area** and **Matched against**. |
| Outlines appear but no names | **Write on each area** is set to **Nothing**, or the chosen attribute is empty for those areas. |
| Grey map, pins visible, a note under it | The server cannot reach the tile host. Not a fault; see [section 10](#10-the-ground-under-the-map). |
| Half the map is grey | The widget was resized. It corrects itself; if it does not, reload. |
| "showing the busiest only" | More than 50,000 places. Filter the dashboard. |
| Pins are one dot in the middle of the ocean | Latitude and longitude are the wrong way round. |
| The GPS variable is not in the **Latitude** list | It holds both coordinates as text. Import the file again: the split gives it `__latitude` and `__longitude` columns. See [section 4](#4-putting-a-map-on-a-dashboard). |

---

## 13. For administrators

**Where layers live.** `STORAGE_DIR/boundaries/<layer-id>.geojson`, beside the
datasets, whatever format the layer arrived as. Only the metadata a list has to
show - name, area count, attribute names, bounding box - is in the database. A
national frame is megabytes of coordinates that no query filters on.

**Back it up with the rest of the storage directory.** `make backup` covers it.

**Caching.** Up to 8 layers are held parsed in memory, keyed by file path and
modification time, so a replaced layer is never served from a previous version
of itself. A monitoring dashboard asks the same national frame the same
question on every refresh, and reparsing megabytes each time is work nobody
sees the result of.

**Permissions.**

| Action | Needs |
|---|---|
| See a layer, build a map on it | Signed in, and the layer shared or in a project they can reach |
| Add, rename, re-assign or delete a layer | The **manager** role or above |

A layer in a project the caller cannot reach reports "not found" rather than
"forbidden", so the endpoint cannot be used to discover what another project
holds.

**Shared dashboards.** A published dashboard renders the boundary layer its
author chose, without a reader to check. The dashboard is the unit of access;
which layers may be *chosen* is decided where they are offered, which is
scoped.

**Dependencies.** Only `pyshp` is needed, and only for shapefiles. GeoJSON and
GeoPackage need nothing beyond the standard library.

---

## 14. For automation: the API

All under `/api/v1`, all needing a bearer token.

```
GET    /boundaries                  layers you can reach
GET    /boundaries?project_id=<id>  that project's layers, plus shared ones
GET    /boundaries/{id}             one layer's metadata
GET    /boundaries/{id}/geojson     the areas themselves, whole
POST   /boundaries                  upload a layer                   [manager]
PATCH  /boundaries/{id}             rename, re-describe, re-assign   [manager]
DELETE /boundaries/{id}             delete it                        [manager]
```

Uploading is `multipart/form-data` with `file`, and optional `name`,
`description`, `project_id` and `layer` - the last naming which table to take
from a multi-layer GeoPackage.

```bash
curl -X POST https://your-server/api/v1/boundaries \
  -H "Authorization: Bearer $TOKEN" \
  -F "file=@ea-frame-2026.zip" \
  -F "name=Enumeration areas 2026"
```

The reply is the layer, including `feature_count`, `properties` - the attribute
names, which is what you pick **Matched against** from - and `bbox`.

Uploading and deleting are both written to the audit log.

---

## See also

- [User guide](user-guide.md) - dashboards, widgets, filters and sharing
- [API reference](api.md) - every endpoint
- [Deployment](deployment.md) - storage, backups and offline operation
