"""Strict SHP/DBF conversion with a separate destination and original row IDs."""
from dataclasses import dataclass, field
from pathlib import Path
from collections import Counter
import codecs
import hashlib
import json
import shutil
import tempfile
import time

import shapefile

from .errors import AnnotationError
from .notes import parse_note

POINT_TYPES = (shapefile.POINT, shapefile.POINTZ, shapefile.POINTM)
NOTE_CANDIDATES = ('注记', '注释', '文字', 'text', 'label', 'annotation', 'string')
EXTRA = [('SRC_FID', 'N', 12, 0), ('RAW_NOTE', 'C', 254, 0),
         ('LABEL_TXT', 'C', 254, 0), ('LABEL_HTM', 'C', 254, 0),
         ('NOTE_KIND', 'C', 16, 0), ('NOTE_FLAG', 'C', 80, 0)]


@dataclass
class ConversionConfig:
    note_field: str = None
    note_fields: dict = field(default_factory=dict)
    encoding: str = None
    strict_controls: bool = False
    field_aliases: dict = field(default_factory=dict)

    def validate(self):
        if self.note_field is not None and (not isinstance(self.note_field, str) or not self.note_field):
            raise AnnotationError('note_field must be a nonempty string or None')
        for name, value in [('note_fields', self.note_fields), ('field_aliases', self.field_aliases)]:
            if not isinstance(value, dict) or any(not isinstance(k, str) or not k or not isinstance(v, str) or not v for k,v in value.items()):
                raise AnnotationError(name + ' must map nonempty strings to nonempty strings')
        if not isinstance(self.strict_controls, bool):
            raise AnnotationError('strict_controls must be boolean')


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def publish(stage, output, attempts=40, delay=0.25):
    """Atomically move a finished staging directory into place.

    On Windows a just-written file can be held briefly by antivirus/indexing, making
    the directory rename fail with PermissionError (WinError 5); retry for ~10 s
    before giving up. Other errors are raised immediately."""
    for attempt in range(attempts):
        try:
            Path(stage).rename(output)
            return
        except PermissionError:
            if attempt == attempts - 1:
                raise
            time.sleep(delay)


def companion(path, suffix, required=False):
    path = Path(path)
    matches = [p for p in path.parent.iterdir() if p.is_file() and
               p.stem.casefold() == path.stem.casefold() and p.suffix.casefold() == suffix.casefold()]
    if len(matches) > 1:
        raise AnnotationError('Ambiguous companion filename: ' + str(path) + suffix)
    if not matches:
        if required:
            raise AnnotationError('Missing companion: ' + str(path.with_suffix(suffix)))
        return None
    return matches[0]


def shp_files(directory):
    return sorted(p for p in Path(directory).iterdir() if p.is_file() and p.suffix.casefold() == '.shp')


def find_shp(directory, name):
    matches = [p for p in shp_files(directory) if p.stem == name]
    if len(matches) != 1:
        raise AnnotationError('Missing or ambiguous SHP layer: ' + name)
    return matches[0]


def open_reader(path, encoding=None):
    return shapefile.Reader(shp=str(companion(path, '.shp', True)),
                            shx=str(companion(path, '.shx', True)),
                            dbf=str(companion(path, '.dbf', True)),
                            encoding=encoding_for(path, encoding), encodingErrors='strict')


def encoding_for(path, override=None):
    cpg = companion(path, '.cpg')
    value = override or (cpg.read_text(encoding='utf-8-sig').strip() if cpg else 'gb18030')
    aliases = {'936': 'gbk', '65001': 'utf-8', 'ansi 936': 'gbk', 'ansi 1252': 'cp1252'}
    value = aliases.get(value.lower(), value)
    if value.isdigit():
        value = 'cp' + value
    try:
        return codecs.lookup(value).name
    except LookupError as exc:
        raise AnnotationError('Unknown encoding: ' + value) from exc


def read_points(path, note_field=None, encoding=None):
    path = Path(path)
    codec = encoding_for(path, encoding)
    with open_reader(path, codec) as reader:
        if reader.shapeType not in POINT_TYPES:
            raise AnnotationError('Annotation layer must contain single points: ' + str(path))
        fields = [tuple(f) for f in reader.fields[1:]]
        names = [f[0] for f in fields]
        if len({name.casefold() for name in names}) != len(names):
            raise AnnotationError('Duplicate input DBF field names: ' + path.name)
        if note_field is None:
            matches = [name for name in names if name.casefold() in NOTE_CANDIDATES]
            if len(matches) != 1:
                raise AnnotationError('Specify note_field; candidates=' + repr(matches) + ' in ' + path.name)
            note_field = matches[0]
        if note_field not in names:
            raise AnnotationError('Missing annotation field ' + note_field + ' in ' + path.name)
        records = list(reader.records())
        shapes = list(reader.shapes())
        # Deleted DBF rows cannot be silently compacted against copied geometry.
        if len(records) != len(reader) or len(shapes) != len(reader):
            raise AnnotationError('Deleted/missing DBF or SHP rows: ' + path.name)
        for fid, rec in enumerate(records):
            if getattr(rec, 'oid', fid) != fid:
                raise AnnotationError('Non-contiguous original DBF rows: ' + path.name)
        return fields, records, shapes, note_field, codec


def portable_names(fields, aliases):
    used = {f[0].casefold() for f in EXTRA}
    mapping = {}
    for i, item in enumerate(fields):
        name = item[0]
        candidate = aliases.get(name, name)
        if '\x00' in candidate or any(c.isspace() for c in candidate) or not candidate or len(candidate.encode('utf-8')) > 10 or candidate.casefold() in used:
            if name in aliases:
                raise AnnotationError('Invalid or duplicate configured field alias: ' + candidate)
            serial = i
            candidate = 'F' + str(serial).zfill(7)
            while candidate.casefold() in used:
                serial += 1
                candidate = 'F' + str(serial).zfill(7)
        used.add(candidate.casefold())
        mapping[name] = candidate
    return mapping


def convert_layer(source, output, config=None):
    """Create a new directory containing one converted SHP plus its report.

    The directory must not already exist. All work is staged beside it; an
    encoding/length/write failure leaves the destination absent.
    """
    config = config or ConversionConfig()
    config.validate()
    source, output = Path(source).resolve(), Path(output).resolve()
    if output.exists() or output.is_relative_to(source.parent) or source.parent.is_relative_to(output):
        raise AnnotationError('Use a new output directory outside the source directory tree')
    fields, records, shapes, note_field, codec = read_points(
        source, config.note_fields.get(source.stem, config.note_field), config.encoding)
    mapping = portable_names(fields, config.field_aliases)
    names = [f[0] for f in fields]
    index = names.index(note_field)
    parsed = [parse_note(rec[index], strict=config.strict_controls) for rec in records]
    new_records = []
    for fid, (record, note) in enumerate(zip(records, parsed)):
        values = list(record)
        values[index] = note.unicode
        new_records.append(values + [fid, note.raw, note.plain, note.html, note.kind, '|'.join(note.warnings)])
    new_fields = [(mapping[f[0]], *f[1:]) for f in fields] + EXTRA
    for i, (name, kind, width, decimals) in enumerate(new_fields):
        if kind == 'C':
            width = max([1] + [len(str(rec[i] or '').encode('utf-8')) for rec in new_records])
            if width > 254:
                raise AnnotationError('UTF-8 DBF overflow (>254 bytes): ' + source.name + '/' + name + '; no truncation performed')
            new_fields[i] = (name, kind, width, decimals)
    companions = [p for s in ('.shp', '.shx', '.dbf', '.cpg', '.prj') for p in [companion(source, s)] if p]
    before = {str(p): sha256(p) for p in companions}
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.mapgis-', dir=str(output.parent)) as temporary:
        stage = Path(temporary) / 'product'
        stage.mkdir()
        target = stage / source.name
        for suffix in ('.shp', '.shx', '.prj'):
            original = companion(source, suffix)
            if original:
                shutil.copyfile(original, target.with_suffix(suffix))
        with shapefile.Writer(dbf=str(target.with_suffix('.dbf')), encoding='utf-8') as writer:
            for spec in new_fields:
                writer.field(*spec)
            for values in new_records:
                writer.record(*values)
        target.with_suffix('.cpg').write_text('UTF-8', encoding='ascii')
        with open_reader(target, 'utf-8') as check:
            if len(check) != len(records) or [list(r) for r in check.records()] != new_records:
                raise AnnotationError('DBF read-back failed: ' + source.name)
        if before != {str(p): sha256(p) for p in companions}:
            raise AnnotationError('Source changed during conversion')
        warnings = Counter(w for note in parsed for w in note.warnings)
        if not companion(source, '.prj'):
            warnings['MISSING_CRS'] += 1
        report = {'layer': source.stem, 'records': len(records), 'note_field': note_field,
                  'output_note_field': mapping[note_field], 'encoding': codec, 'field_map': mapping,
                  'changed': sum(note.raw != note.unicode for note in parsed),
                  'warnings': dict(warnings), 'source_sha256': before,
                  'geometry_unchanged': True, 'crs_file_present': bool(companion(source, '.prj'))}
        (stage / 'conversion.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        publish(stage, output)
    return report


def inspect_dataset(directory, encoding=None):
    """Read-only schema/geometry inventory; no annotation field assumptions."""
    result = []
    for path in shp_files(directory):
        codec = encoding_for(path, encoding)
        with open_reader(path, codec) as reader:
            result.append({'layer': path.stem, 'records': len(reader), 'shape_type': reader.shapeType,
                           'fields': [f[0] for f in reader.fields[1:]], 'encoding': codec,
                           'has_prj': bool(companion(path, '.prj')), 'filename': path.name})
    if not result:
        raise AnnotationError('No .shp files found in ' + str(directory))
    return result
