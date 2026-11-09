# Third-party notices

`src/mapgis_annotations/native_crs.py` adapts the coordinate-header decoding
approach from [leecugb/mapgis2shp](https://github.com/leecugb/mapgis2shp),
`src/pymapgis/reader.py` at commit `c4257a6cfcdc122d8827777bddf5f2604b300cc6`.
Upstream author: Shijie Li (leecugb) and pymapgis contributors.
Upstream license: Apache License 2.0, included in `licenses/Apache-2.0.txt`.
That module is distributed under Apache-2.0; the original project files retain
their MIT license. No upstream NOTICE file was present in that revision.

Changes: isolated the header decoder from GeoPandas and NumPy, added strict
signed fractional DMS validation, preserved named geographic datums where
established by conventional indices, omitted fixed regional `towgs84` shifts,
and returned auditable candidates for the existing coordinate-validation flow.
This attribution does not imply endorsement by upstream authors.
