"""Read-back inventory of converted SHPs, including empty and invalid geometry."""
import csv
import math
from pathlib import Path

import shapefile

from .errors import AnnotationError
from .shapefiles import open_reader, shp_files
from .workflow import write_json


def audit_shapefiles(directory, output):
    try:
        from shapely.geometry import shape
    except ImportError:
        shape = None
    rows = []
    for path in shp_files(directory):
        with open_reader(path) as reader:
            records = len(reader.records())
            geometries = list(reader.shapes())
            if len(geometries) != records:
                raise AnnotationError('SHP/DBF count mismatch: ' + path.name)
            invalid, nulls = 0, 0
            for geometry in geometries:
                if geometry.shapeType == shapefile.NULL:
                    nulls += 1
                    continue
                if any(not math.isfinite(c) for p in geometry.points for c in p):
                    raise AnnotationError('Nonfinite coordinates: ' + path.name)
                if shape and geometry.shapeType in (5, 15, 25):
                    invalid += not shape(geometry.__geo_interface__).is_valid
            rows.append({'layer': path.stem, 'records': records, 'shape_type': reader.shapeType,
                         'has_prj': path.with_suffix('.prj').is_file(), 'null_geometries': nulls,
                         'invalid_polygons': invalid if shape else None})
    report = {'status': 'PASS', 'layers': rows, 'records': sum(row['records'] for row in rows),
              'geometry_validity_checked': shape is not None,
              'invalid_polygons': sum(row['invalid_polygons'] for row in rows) if shape else None,
              'null_geometries': sum(row['null_geometries'] for row in rows)}
    output = Path(output)
    write_json(output.with_suffix('.json'), report)
    with output.with_suffix('.csv').open('w', encoding='utf-8-sig', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]) if rows else ['layer'])
        writer.writeheader()
        writer.writerows(rows)
    return report
