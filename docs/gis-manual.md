# The GIS component

The GIS component in SurveyHQ helps you answer one question:

> Was this interview done in the area the interviewer recorded?

To do this it reads boundary files, draws area outlines on a map and colours
interview points by whether they match. This manual explains what files to use,
how to set up a map, how to read the results and what the component doesn't do.

You should already know how to add a dashboard and a widget. If not, read
[the user guide](user-guide.md) first.

---

## Contents

1. [What it does](#1-what-it-does)
2. [Preparing the boundary file](#2-preparing-the-boundary-file)
3. [Adding a boundary layer](#3-adding-a-boundary-layer)
4. [Putting a map on a dashboard](#4-putting-a-map-on-a-dashboard)
5. [Drawing boundaries under the pins](#5-drawing-boundaries-under-the-pins)
6. [Checking the recorded area against the GPS](#6-checking-the-recorded-area-against-the-gps)
7. [The data quality layers](#7-the-data-quality-layers)
8. [How codes are compared](#8-how-codes-are-compared)
9. [Using the map during fieldwork](#9-using-the-map-during-fieldwork)
10. [How the pins are drawn](#10-how-the-pins-are-drawn)
11. [Map backgrounds](#11-map-backgrounds)
12. [Limits](#12-limits)
13. [Troubleshooting](#13-troubleshooting)
14. [For administrators](#14-for-administrators)
15. [For automation: the API](#15-for-automation-the-api)

---

## 1. What it does

The GIS component stores boundary layers (for example enumeration areas) and
provides a map widget. The map shows interview locations against the boundaries
and highlights where they don't match.

It is not a full GIS. It can't edit or digitise boundaries, create buffers,
reproject data, check topology or use raster data, and the only spatial
operation is finding which area a point falls in. Do that kind of work in QGIS
and upload the result.

Reading boundary files doesn't need any GIS software on the server or an
internet connection. There is no GDAL, PostGIS, DuckDB spatial extension or
`pyproj`. GeoPackages (SQLite files) and shapefiles are read directly. This means
the component works on servers with no internet access.

The only part that needs the internet is the **map background** (street map or
satellite imagery). See [section 11](#11-map-backgrounds).

---

## 2. Preparing the boundary file

This section is for the person who exports the boundaries from your GIS.

### The coordinates must be longitude and latitude in degrees

SurveyHQ doesn't reproject boundaries. It compares them directly with the GPS
points from the devices, which are in WGS84 degrees.

Export the file as **EPSG:4326 (WGS84)**.

If you export in a projected system (UTM, a national grid or anything in
metres), the file uploads and shows the right number of areas, but:

- the outlines won't appear near your fieldwork, and
- **every record will be reported as "outside every area"**.

Including a `.prj` file in the zip doesn't help, because nothing is reprojected.

**To check before uploading,** look at the file's bounding box. Longitudes
should be between -180 and 180 and latitudes between -90 and 90. If you see
numbers in the hundreds of thousands, the file is projected and needs
converting. In QGIS, right-click the layer, choose **Export → Save Features
As…** and set the CRS to **EPSG:4326**.

### The file must contain areas

Only polygons and multipolygons are accepted. A file of points or lines is
refused. If a file has a mix, anything that isn't an area is skipped.

### The attribute table must include the code you want to match on

One column in the boundary file must hold the same enumeration area code that the
questionnaire records. Make sure it is included in the export and note its name,
because you'll choose it later. It also helps to include a name column, which can
be shown on the map.

### Supported formats

| Format | File | Notes |
|---|---|---|
| **GeoJSON** | `.geojson` or `.json` | The simplest option. A `FeatureCollection`, a single `Feature` or a bare geometry all work. |
| **GeoPackage** | `.gpkg` | If it has several spatial layers, the first one is used unless you name one. |
| **Shapefile** | `.zip` | Must contain at least the `.shp` and `.dbf` files. Include `.shx`, `.prj` and `.cpg` if you have them. |

A shapefile without a `.dbf` is refused, because the `.dbf` holds the attribute
table with the codes and names.

---

## 3. Adding a boundary layer

Go to **Datasets → Boundaries → Add boundaries**.

You need the **manager** role or above to add or delete a layer. Anyone who is
signed in can see the layers for their projects and use them on maps.

| Field | What to enter |
|---|---|
| **File** | The `.geojson`, `.gpkg` or `.zip` file. |
| **Name** | The name people will choose from a list, for example `Enumeration areas 2026`. Defaults to the file name. |
| **Description** | Optional. Which frame it is and when it was made. Useful once you have more than one layer. |
| **Project** | Leave as **shared** for boundaries used by every survey. Choose a project if the layer is only for that survey. |

Click **Add layer**. The file is read, converted to GeoJSON and stored. The
confirmation shows how many areas were found. **Check this against the number
you expect.** If the frame should have 4,182 enumeration areas and shows 3,900,
something was lost in the export.

The list shows each layer with its number of areas, its attribute names and its
original format. You'll choose from these attribute names when you set up the
map.

**Sharing.** Shared layers are available to every project. A layer assigned to a
project is only available to that project. Filtering the list by project still
shows the shared layers.

**Deleting.** If you delete a layer, maps that use it stop showing outlines and
stop checking areas. They still work as plain maps. If you delete the project a
layer belongs to, the layer is moved to the shared area instead of being deleted.

**Replacing a layer.** You can't replace a layer in place. Upload the new file as
a new layer, change your maps to use it, then delete the old one.

---

## 4. Putting a map on a dashboard

Choose **Add widget → Map of interview locations**.

| Setting | What it does |
|---|---|
| **Latitude** / **Longitude** | The variables with the GPS coordinates. Only numeric variables are listed. |
| **What each pin counts** | The number of records, or the total, average, highest or lowest value of a variable. |
| **Show on click** | Up to six variables shown when someone clicks a pin. Include the interviewer's name so you know who to ask. |

> **Note:** You can't change **Show on click** later from **✎**. To change it,
> delete the widget and add it again.

### If the GPS is in one column

Some exports store the whole GPS reading in one text column, for example:

- ODK Central: `-12.3456 34.5678 42.0 5.0` (latitude, longitude, altitude,
  accuracy)
- CSV: `-12.3456,34.5678`
- Database extracts: `POINT(34.5678 -12.3456)` or a GeoJSON point

Because the **Latitude** and **Longitude** lists only show numeric variables,
these columns can't be used directly.

**SurveyHQ splits these columns when the file is imported.** A column called
`gps` gets two new numeric columns:

| Column | Holds |
|---|---|
| `gps__latitude` | Latitude |
| `gps__longitude` | Longitude |

The original column is kept. Choose the new columns for **Latitude** and
**Longitude**. They are also picked up automatically for field progress and for
**Data quality > Missing GPS**. The import notes list which columns were split.

**How splitting works**

- **Existing datasets don't get the new columns automatically.** Import the file
  again, or wait for the next scheduled import.
- **The order is detected.** WKT and GeoJSON are read longitude first, as the
  formats require. A plain pair of numbers is read latitude first, which is what
  ODK, Survey Solutions and GPS devices use. If the first number is above 90 it
  can't be a latitude, so the pair is read the other way round.
- **Only real coordinates are split.** At least 90% of sampled values must look
  like a point. A value such as `10.0.0.1` (an IP address) isn't split. A plain
  pair must have at least four decimal places (about 11 metres), so pairs such
  as a height and a weight aren't mistaken for coordinates. WKT, GeoJSON and
  scientific notation (`1.683273e2`) don't need the decimal places.
- **New rounds use the same columns.** If you append a file to a dataset that
  already has split coordinates, the new rows are split too, even if there are
  too few of them to be detected on their own.

If a value can't be read, that row has no coordinates and is counted by **Missing
GPS**. It is not set to `0, 0`.

**Pins are places, not rows.** Interviews at the same coordinates are grouped
into one pin that shows the count. Clicking a pin shows the count and the
**Show on click** variables.

Records are left off the map if they have:

- no coordinates
- a latitude or longitude outside the valid range
- exactly `0, 0`, which is what a device records when it has no fix

To count records with no usable coordinates, use a data quality check instead:
**Data quality → Missing GPS** counts rows where either coordinate is missing or
both are zero.

---

## 5. Drawing boundaries under the pins

In the map widget's settings (**✎**):

- **Boundaries.** The layer to draw. The list shows the number of areas in each
  layer.
- **Write on each area.** The attribute used as the area's name, shown when you
  hover over it. Choose **Nothing** for outlines without names.
- **Show the names.** Choose **On hover**, or **Always, written on the map** to
  print the names in white in the middle of each area, like a field map.

Areas are drawn as outlines without fill, so you can still see the satellite
image. They are always drawn under the pins.

**Once you choose a layer, the map zooms to the layer, not the pins.** This stops
one wrong coordinate from zooming the map out too far. The key still counts
points outside the layer, so you know to zoom out and look for them.

**Hiding the outlines.** The layers box in the top right corner of the map has a
tick box for the boundary layer. Untick it to hide the outlines and tick it to
show them again. Anyone viewing the dashboard can do this, including on a share
link.

---

## 6. Checking the recorded area against the GPS

The main reason to add boundaries is to check that each interview was done in
the area that was recorded.

When the recorded area and the GPS location don't match, it is usually because:

- the EA code was typed wrong,
- the interviewer worked in the wrong area, or
- field staff understood a boundary differently from the office.

It is best to find these during fieldwork, while they can still be fixed.

### Setting it up

You need to set all three of these. If any are missing, the map works as a plain
map.

| Setting | What to choose |
|---|---|
| **Boundaries** | The layer to check against. |
| **Recorded area** | The variable with the area code the interviewer recorded. |
| **Matched against** | The attribute in the boundary layer with the same code. |

If you set **Recorded area** but not **Matched against**, the widget shows a
warning.

### Reading the result

Each pin is coloured by its result. The box in the top right corner lists each
result with its colour, a tick box and a count. Only results that occur are
listed.

| Colour | Result | Meaning |
|---|---|---|
| **Red** (largest) | Area does not match the GPS | The recorded code isn't the area the point falls in. |
| **Amber** | Outside every area in the layer | The point isn't in any area in the layer. |
| **Purple** | No area recorded | The record has GPS but no area code. |
| **Green** (smallest) | Area agrees with the GPS | No problem. |

Red pins are drawn larger and green pins smaller so problems stand out.

**Amber isn't a mismatch.** A point outside every area usually means the boundary
file doesn't cover that place, or the coordinates are wrong (for example in the
wrong hemisphere).

**If everything is amber,** the layer is probably in the wrong coordinate system.
See [section 2](#2-preparing-the-boundary-file).

### Clicking a pin

The popup shows:

- what the pin counts and how many records it includes
- the result, in its colour
- the recorded area (its label if the variable has value labels)
- the area the point actually falls in
- the **Show on click** variables, such as the interviewer's name

If two households at the same coordinates have different recorded areas, they are
shown as two separate pins.

---

## 7. The data quality layers

The **Data quality layers** section of the map settings adds extra checks. Each
check is a separate layer, listed in the corner of the map with its colour and
count. Anyone viewing the map can turn layers on and off, including on a share
link. A layer you turn off stays off when you zoom or when the dashboard
refreshes.

| Layer | Shown as | What it shows |
|---|---|---|
| **Duplicated GPS (within 100 m)** | Black ring around the pin | Readings with another record within the distance you set. The popup says how many. |
| **Manual location agrees with the area** | Blue dot with a white edge | The second location is in the recorded area. |
| **Manual location is in another area** | Yellow dot with a white edge | The second location is in a different area from the one recorded. |
| **Manual location outside every area** / **no area recorded** | Grey / lilac dot | Same as for GPS. |
| **GPS and manual over 100 m apart** | Dashed white line | A line from the GPS reading to the second location when they are further apart than the distance you set. Click the line to see the distance. |
| **Areas with interviews (12 of 30)** | Amber shading | Areas with at least one GPS reading. |

### Setting them up

- **Flag duplicated GPS.** Tick it and set a distance in metres. Records with
  exactly the same reading are always flagged. Where houses are close together,
  a large distance flags most of them, so start with 10 to 20 m and increase it
  if needed.
- **Second location.** The latitude and longitude variables for a location
  entered by hand, and a name for it ("Manual" if left blank). It is checked
  against the areas whenever the map checks recorded areas.
- **Draw a line where the two are more than … metres apart.** 100 by default.
- **Shade the areas with interviews.** Needs a boundary layer.

Use the household-level dataset. In a roster file, every member has the same
coordinates as their household and would be flagged as duplicates.

### What to look for

- **A group of rings** can mean two interviews were entered from the same place,
  a reading was copied between forms, or a supervisor's device recorded for the
  whole team. Click a ringed pin to see how many others are nearby.
- **A yellow dot with a line to a green pin** means the location entered by hand
  is in a different area from the GPS. One of them is wrong. The length of the
  line shows how far apart they are.
- **A blue or yellow dot with no line and no GPS pin** is a record where the
  device got no GPS fix and the location was entered by hand.
- **An area with no shading** has no interviews yet. Compare with your target
  list to see where fieldwork hasn't reached.

The checks are done on the server using every location as recorded, before pins
are grouped. On large maps where pins are grouped into cells, a cell with a
flagged location is ringed and its popup says how many locations are flagged.

---

## 8. How codes are compared

Area codes are often stored as text in one file and as numbers in another, and
leading zeros may be missing. SurveyHQ allows for this. All of these match:

| Recorded | Boundary attribute | Match |
|---|---|---|
| `"7"` | `"007"` | yes |
| `7` (a number) | `"007"` | yes |
| `7.0` | `"7"` | yes |
| `"007"` | `"7"` | yes |
| `"008"` | `"007"` | no |

The rules are:

- Leading zeros are removed, **but only from codes made up entirely of digits**.
  A code like `0A1` is compared as it is.
- Text is compared without regard to case.
- Spaces at the start and end are ignored.
- A blank or missing value counts as **no area recorded** (purple), not a
  mismatch.

---

## 9. Using the map during fieldwork

A suggested daily routine for a fieldwork monitor:

1. Open the map and read the key in the corner first. It counts each result and
   each data quality layer. Untick **Area agrees with the GPS** and **Manual
   location agrees** to show only the problems.
2. **If almost everything is amber,** it is a setup problem. Check the layer's
   coordinate system and that **Matched against** uses the right attribute.
3. **Red pins grouped in one place** usually mean one interviewer, or a boundary
   being understood differently on the ground. Click a few to see if they have
   the same interviewer.
4. **Red pins spread thinly everywhere** usually mean typing errors. Check
   whether the recorded codes are close to the correct ones.
5. Use the dashboard filters to look at one supervisor or a date range, and see
   whether the problem is linked to a person or a particular week.
6. Then check **rings** (locations shared with another record) and **lines**
   (households where the two locations don't agree). These are often linked to
   one interviewer, so check the popups for names.
7. Use **Fill the window** from the widget's menu to make the map full screen
   while you work through it.

A wrong EA code is easy to fix during fieldwork and much harder to fix
afterwards, so check daily.

---

## 10. How the pins are drawn

These settings are in the widget's settings (**✎**). The defaults work for most
maps.

| Setting | Notes |
|---|---|
| **Point shape** | Circle, square, triangle, diamond or pentagon. |
| **Point colour** | Any colour. The outline colour is set automatically. |
| **Point size** | 6 to 40 pixels. This is the size before scaling by value. |
| **Point transparency** | 10% to 100%. Lower values help show density where pins overlap. |
| **Bigger pins where the number is bigger** | On by default. |

**Shapes.** Use circles when pin size shows a quantity. Use other shapes when you
want to show different types of thing, because shapes are easier to tell apart
than shades of one colour, including when printed in black and white.

**Size.** Pins are scaled by area, not radius. The largest value on the map sets
the scale.

**When the area check is on, point settings are ignored.** Pins are sized by
their result and only the colour matters.

Turn off **Bigger pins where the number is bigger** when you only want to show
where interviews took place, not how many.

---

## 11. Map backgrounds

There are three backgrounds. You choose the default on the widget, and anyone
viewing the map can switch using the control in the top right corner:

- **Streets.** OpenStreetMap. This is the default.
- **Satellite.** Aerial images, with place names and boundaries shown on top.
- **Terrain.** Contours and relief.

A viewer's choice lasts until they close the page. Everyone starts with the one
saved on the widget.

**All three backgrounds need an internet connection.** This is the only part of
the GIS component that does. If the server can't reach the map tile servers, the
pins are still drawn on a plain background and a note is shown under the map.

**Using your own tile server.** Enter a URL template in **Map tiles** to replace
all three backgrounds. The background switcher is then hidden. Use this for
offline installations with a local tile server.

---

## 12. Limits

| Limit | Value | What happens |
|---|---|---|
| Areas in one layer | **20,000** | The upload is refused and the message gives the count. Use a higher-level boundary, or split the frame into several layers by region. |
| Places on one map | **50,000** | The places with the highest values are shown and the map says "showing the busiest only". Filter the dashboard to show fewer. |
| Upload size | **`MAX_UPLOAD_MB`** (20 GB by default) | The upload is refused and the message gives the limit. |
| Second locations on one map | **50,000** places | Same as for GPS. |
| Discrepancy lines | **5,000**, longest first | The key gives the full count. Increase the line distance to see only the worst. |
| Duplicates counted for one pin | **99** | The popup says "99+". |

The 50,000 limit counts places, not interviews, because interviews at the same
coordinates are grouped. A census with a separate GPS reading for every household
can still reach this limit for a large province.

The area check and data quality layers use every location exactly as recorded,
so they can reach the limit sooner than a plain map.

**Downloaded and published dashboards** show maps with interview locations only.
They don't include boundaries or the checks that need them, because boundary
files are large.

---

## 13. Troubleshooting

### Upload errors

| Message | Cause |
|---|---|
| `Boundaries can be read from GeoJSON, a GeoPackage, or a zipped shapefile` | The file isn't `.geojson`, `.json`, `.gpkg` or `.zip`. A `.shp` file on its own isn't enough; zip it with its `.dbf`. |
| `This zip holds no .shp file` | The zip isn't a shapefile, or the `.shp` is in an unexpected folder. |
| `This shapefile has no .dbf, so it carries no area names` | The `.dbf` file is missing from the zip. |
| `This file is not a GeoPackage: it has no geometry columns table` | The `.gpkg` is a plain SQLite database, not a GeoPackage. |
| `This GeoPackage holds no spatial layers` | The GeoPackage has no spatial tables. |
| `This is not readable GeoJSON` / `This JSON is not a GeoJSON feature collection` | The file isn't JSON, or isn't GeoJSON. |
| `No areas were found in this file` | The file has no polygons. It may contain points or lines. |
| `This layer has N areas, more than the 20,000 a map can draw` | See [Limits](#12-limits). |

### Map problems

| Problem | Likely cause |
|---|---|
| Everything is amber ("outside every area") | The layer uses a projected coordinate system. See [section 2](#2-preparing-the-boundary-file). |
| Everything is red | **Matched against** uses the wrong attribute, such as a name or a different ID. |
| No outlines | No **Boundaries** layer chosen, the layer was deleted, or someone unticked it in the layers box. |
| Pins aren't coloured | The area check needs **Boundaries**, **Recorded area** and **Matched against**. |
| Outlines but no names | **Write on each area** is set to **Nothing**, or the attribute is empty. |
| Grey map with pins and a note | The server can't reach the map tile server. See [section 11](#11-map-backgrounds). |
| Half the map is grey | The widget was resized. Reload the page if it doesn't fix itself. |
| "showing the busiest only" | More than 50,000 places. Filter the dashboard. |
| All pins are in one spot in the ocean | Latitude and longitude are the wrong way round. |
| The GPS variable isn't in the **Latitude** list | It holds both coordinates as text. Import the file again so it is split into `__latitude` and `__longitude` columns. See [section 4](#4-putting-a-map-on-a-dashboard). |

---

## 14. For administrators

**Storage.** Layers are stored as `STORAGE_DIR/boundaries/<layer-id>.geojson`,
whatever format they were uploaded in. The database only holds the metadata
(name, area count, attribute names and bounding box).

**Backups.** Back up the storage directory. `make backup` includes it.

**Caching.** Up to 8 layers are kept in memory, keyed by file path and
modification time, so a replaced file is always read fresh.

**Permissions**

| Action | Needs |
|---|---|
| See a layer and use it on a map | Signed in, and the layer is shared or in a project the user can access |
| Add, rename, reassign or delete a layer | **Manager** role or above |

If a user asks for a layer in a project they can't access, they get "not found"
instead of "forbidden".

**Shared dashboards.** A shared dashboard shows the boundary layer its author
chose. Access is controlled by the dashboard itself. Which layers an author can
choose depends on their projects.

**Dependencies.** Only `pyshp` is needed, and only for shapefiles. GeoJSON and
GeoPackage use the Python standard library.

---

## 15. For automation: the API

All endpoints are under `/api/v1` and need a bearer token.

```
GET    /boundaries                  layers you can reach
GET    /boundaries?project_id=<id>  that project's layers, plus shared ones
GET    /boundaries/{id}             one layer's metadata
GET    /boundaries/{id}/geojson     the areas themselves, whole
POST   /boundaries                  upload a layer                   [manager]
PATCH  /boundaries/{id}             rename, re-describe, re-assign   [manager]
DELETE /boundaries/{id}             delete it                        [manager]
```

To upload, send `multipart/form-data` with `file` and, optionally, `name`,
`description`, `project_id` and `layer` (the table to use from a GeoPackage with
several layers).

```bash
curl -X POST https://your-server/api/v1/boundaries \
  -H "Authorization: Bearer $TOKEN" \
  -F "file=@ea-frame-2026.zip" \
  -F "name=Enumeration areas 2026"
```

The response is the layer, including `feature_count`, `properties` (the attribute
names, used for **Matched against**) and `bbox`.

Uploads and deletions are recorded in the audit log.

The map widget's settings (boundary layer, area check, area names and data
quality layers) are stored in its `config`. See **A map widget** in the
[API reference](api.md).

---

## See also

- [User guide](user-guide.md): dashboards, widgets, filters and sharing
- [API reference](api.md): every endpoint
- [Deployment](deployment.md): storage, backups and offline use
