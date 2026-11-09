"""Optional PyQGIS renderer. No QGIS import or application side effect at import."""
from pathlib import Path
import gc
import json
import math
import os
import shutil
import sys
import tempfile

from .errors import AnnotationError, MissingDependencyError
from .shapefiles import publish, sha256
from .workflow import verify_dataset, write_json
from .render_views import validate_views, render_views


def export_project(dataset, output, *, width_mm=1000, dpi=300, font_size=9,
                   font_family='Times New Roman', font_unit='points', render_crs=None,
                   max_pixels=120000000, missing_crs='error', details=None, title='MapGIS'):
    """Create a self-contained QGZ, vector PDF, PNG and preview from a workflow.

    Run in a Python environment providing PyQGIS, e.g. QGIS's Python console
    or its own interpreter. No fixed installation path is required. An
    existing QGIS application is reused and never shut down by this library.
    """
    dataset, output = Path(dataset).resolve(), Path(output).resolve()
    if output.exists() or output.is_relative_to(dataset) or dataset.is_relative_to(output):
        raise AnnotationError('Export output must be a new directory outside the dataset tree')
    if not all(math.isfinite(v) and v > 0 for v in (width_mm, dpi, font_size, max_pixels)):
        raise AnnotationError('Width, dpi, font size and pixel budget must be finite positive values')
    if dpi < 1 or int(dpi) != dpi:
        raise AnnotationError('dpi must be a positive integer')
    if font_unit not in ('points', 'map'):
        raise AnnotationError('font_unit must be points or map')
    if missing_crs not in ('error', 'exclude'):
        raise AnnotationError('missing_crs must be error or exclude')
    details = [] if details is None else details
    validate_views(details)
    verification = verify_dataset(dataset, verify_sources=False)
    from .runtime import configure_runtime
    configure_runtime()
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    try:
        from qgis.core import QgsApplication
    except ImportError as exc:
        raise MissingDependencyError('QGIS export requires PyQGIS; use QGIS Python, not pip install qgis') from exc
    app = QgsApplication.instance()
    owned = app is None
    if owned:
        QgsApplication.setPrefixPath(os.environ.get('QGIS_PREFIX_PATH', sys.prefix), True)
        app = QgsApplication([], False)
        app.initQgis()
    failure = None
    result = None
    try:
        result = _export(dataset, output, verification, width_mm, int(dpi), font_size,
                         font_family, font_unit, render_crs, max_pixels, missing_crs, details, title)
    except Exception as exc:
        # Release native objects while QGIS is live, including frames held in
        # an exception traceback; then raise an ordinary actionable API error.
        failure = AnnotationError(str(exc))
        exc.__traceback__ = None
    gc.collect()
    if owned:
        app.exitQgis()
    if failure:
        raise failure
    return result


def _export(dataset, output, verification, width_mm, dpi, font_size, font_family,
            font_unit, render_crs, max_pixels, missing_crs, details, title):
    from qgis.core import (Qgis, QgsApplication, QgsVectorLayer, QgsProject, QgsRectangle,
        QgsCoordinateReferenceSystem, QgsCoordinateTransform, QgsWkbTypes,
        QgsField, QgsFeature, QgsVectorFileWriter, QgsMarkerSymbol, QgsLineSymbol,
        QgsFillSymbol, QgsTextFormat, QgsPalLayerSettings, QgsVectorLayerSimpleLabeling,
        QgsProperty, QgsPrintLayout, QgsLayoutItemMap, QgsLayoutPoint, QgsLayoutSize,
        QgsLayoutExporter, QgsMapSettings, QgsMapRendererParallelJob)
    from qgis.PyQt.QtCore import QVariant, QSize
    from qgis.PyQt.QtGui import QColor, QFont

    manifest = json.loads((dataset/'manifest.json').read_text(encoding='utf-8'))
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.mapgis-export-', dir=str(output.parent)) as temporary:
        stage = Path(temporary)/'export'
        stage.mkdir()
        for relative in manifest['product_sha256']:
            target = stage/'data'/relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(dataset/relative, target)
        shutil.copyfile(dataset/'manifest.json', stage/'data/manifest.json')
        project = QgsProject()
        layers, report, excluded = [], [], []
        for name, item in manifest['layers'].items():
            layer = QgsVectorLayer(str(stage/'data'/item['path']), name, 'ogr')
            if not layer.isValid() or layer.featureCount() != item['records']:
                raise AnnotationError('Cannot load converted layer: ' + name)
            if layer.featureCount() == 0:
                excluded.append({'name': name, 'reason': 'EMPTY_LAYER'})
                continue
            if not (stage/'data'/item['path']).with_suffix('.prj').is_file() or not layer.crs().isValid():
                if missing_crs == 'exclude':
                    excluded.append({'name': name, 'reason': 'MISSING_CRS'})
                    continue
                raise AnnotationError('QGIS export requires a CRS for every layer: ' + name)
            display_field = 'LABEL_HTM'
            if item.get('display'):
                values = json.loads((dataset/item['display']).read_text(encoding='utf-8'))['display']
                memory = QgsVectorLayer(QgsWkbTypes.displayString(layer.wkbType()), name, 'memory')
                memory.setCrs(layer.crs())
                fields = list(layer.fields())
                display_field = 'DISPLAY_H'
                while display_field in layer.fields().names():
                    display_field += '_'
                memory.dataProvider().addAttributes(fields + [QgsField(display_field, QVariant.String)])
                memory.updateFields()
                features, originals = [], {}
                for feature in layer.getFeatures():
                    fid = int(feature['SRC_FID'])
                    copied = QgsFeature(memory.fields())
                    copied.setGeometry(feature.geometry())
                    copied.setAttributes(feature.attributes()+[values[str(fid)]])
                    features.append(copied)
                    originals[fid] = feature.geometry().asWkb()
                ok, _ = memory.dataProvider().addFeatures(features)
                if not ok:
                    raise AnnotationError('Cannot copy display layer: ' + name)
                memory.updateExtents()
                settings = QgsVectorFileWriter.SaveVectorOptions()
                settings.driverName, settings.layerName = 'GPKG', name
                gpkg = stage/'display.gpkg'
                settings.actionOnExistingFile = (QgsVectorFileWriter.CreateOrOverwriteLayer if gpkg.exists()
                                                else QgsVectorFileWriter.CreateOrOverwriteFile)
                status = QgsVectorFileWriter.writeAsVectorFormatV3(memory, str(gpkg), project.transformContext(), settings)
                if status[0] != QgsVectorFileWriter.NoError:
                    raise AnnotationError('GPKG write failed: ' + str(status))
                layer = QgsVectorLayer(str(gpkg)+'|layername='+name, name, 'ogr')
                if not layer.isValid() or layer.featureCount() != item['records']:
                    raise AnnotationError('GPKG read-back failed: ' + name)
                for feature in layer.getFeatures():
                    if feature.geometry().asWkb() != originals[int(feature['SRC_FID'])]:
                        raise AnnotationError('Display geometry changed: ' + name)
            if item['converted']:
                text = QgsTextFormat()
                text.setFont(QFont(font_family))
                text.setSize(font_size)
                text.setSizeUnit(Qgis.RenderUnit.Points if font_unit == 'points' else Qgis.RenderUnit.MapUnits)
                text.setColor(QColor('black'))
                text.setAllowHtmlFormatting(True)
                label = QgsPalLayerSettings()
                label.fieldName, label.isExpression = display_field, False
                label.setFormat(text)
                properties = label.dataDefinedProperties()
                for key, value in [(QgsPalLayerSettings.PositionX, 'x($geometry)'),
                                   (QgsPalLayerSettings.PositionY, 'y($geometry)'),
                                   (QgsPalLayerSettings.Hali, "'Left'"),
                                   (QgsPalLayerSettings.Vali, "'Base'"),
                                   (QgsPalLayerSettings.AlwaysShow, 'true')]:
                    properties.setProperty(key, QgsProperty.fromExpression(value))
                label.setDataDefinedProperties(properties)
                layer.setLabeling(QgsVectorLayerSimpleLabeling(label))
                layer.setLabelsEnabled(True)
                layer.renderer().setSymbol(QgsMarkerSymbol.createSimple({'color':'0,0,0,0', 'outline_style':'no', 'size':'0'}))
                for original, mapped in item['conversion']['field_map'].items():
                    layer.setFieldAlias(layer.fields().indexFromName(mapped), original)
            elif layer.geometryType() == Qgis.GeometryType.Line:
                layer.renderer().setSymbol(QgsLineSymbol.createSimple({'line_color':'95,95,95,255', 'line_width':'0.08'}))
            elif layer.geometryType() == Qgis.GeometryType.Polygon:
                layer.renderer().setSymbol(QgsFillSymbol.createSimple({'style':'no', 'outline_color':'145,145,145,255', 'outline_width':'0.08'}))
            else:
                layer.renderer().setSymbol(QgsMarkerSymbol.createSimple({'color':'0,0,0,255', 'size':'0.6'}))
            project.addMapLayer(layer)
            layers.append(layer)
            report.append({'name': name, 'records': layer.featureCount(), 'converted': item['converted'],
                           'crs': layer.crs().toWkt(), 'display_field': display_field if item['converted'] else None})
        if not layers:
            raise AnnotationError('No drawable layers with a valid CRS')
        destination = QgsCoordinateReferenceSystem(render_crs) if render_crs else layers[0].crs()
        if not destination.isValid():
            raise AnnotationError('Invalid render_crs')
        project.setCrs(destination)
        extent = QgsRectangle()
        extent.setMinimal()
        for layer in layers:
            if layer.extent().isNull():
                continue
            transform = QgsCoordinateTransform(layer.crs(), destination, project)
            extent.combineExtentWith(transform.transformBoundingBox(layer.extent()))
        # Include label extents conservatively in destination map units.
        unit_size = font_size if font_unit == 'map' else font_size * max(extent.width(), extent.height(), 1)/(width_mm*72/25.4)
        for layer, info in zip(layers, report):
            if not info['converted']:
                continue
            transform = QgsCoordinateTransform(layer.crs(), destination, project)
            for feature in layer.getFeatures():
                if feature.geometry().isEmpty():
                    continue
                point = transform.transform(feature.geometry().asPoint())
                text = feature['LABEL_TXT']
                if isinstance(text, str) and text:
                    extent.combineExtentWith(QgsRectangle(point.x()-unit_size*.5, point.y()-unit_size,
                        point.x()+(len(text)+1)*unit_size*1.1, point.y()+unit_size*2))
        if extent.width() <= 0 or extent.height() <= 0 or not all(math.isfinite(v) for v in
                (extent.xMinimum(), extent.xMaximum(), extent.yMinimum(), extent.yMaximum())):
            raise AnnotationError('No finite drawable map extent')
        extent.grow(extent.width()*.008)
        height_mm = width_mm*extent.height()/extent.width()
        pixel_width, pixel_height = round(width_mm*dpi/25.4), round(height_mm*dpi/25.4)
        if pixel_width*pixel_height > max_pixels:
            raise AnnotationError('Raster pixel budget exceeded; reduce width_mm or dpi')
        ordered = sorted(layers, key=lambda l: int(l.geometryType()))
        layout = QgsPrintLayout(project)
        layout.initializeDefaults()
        layout.setName('Annotations')
        layout.pageCollection().pages()[0].setPageSize(QgsLayoutSize(width_mm, height_mm))
        layout.renderContext().setDpi(dpi)
        map_item = QgsLayoutItemMap(layout)
        layout.addLayoutItem(map_item)
        map_item.attemptMove(QgsLayoutPoint(0, 0))
        map_item.attemptResize(QgsLayoutSize(width_mm, height_mm))
        map_item.setLayers(ordered)
        map_item.setKeepLayerSet(True)
        map_item.setCrs(destination)
        map_item.zoomToExtent(extent)
        exporter = QgsLayoutExporter(layout)
        pdf = QgsLayoutExporter.PdfExportSettings()
        pdf.dpi, pdf.forceVectorOutput, pdf.simplifyGeometries = dpi, True, False
        pdf.textRenderFormat = Qgis.TextRenderFormat.AlwaysText
        pdf.appendGeoreference = False
        if exporter.exportToPdf(str(stage/'map.pdf'), pdf) != QgsLayoutExporter.Success:
            raise AnnotationError('PDF export failed: ' + exporter.errorMessage())
        image = exporter.renderPageToImage(0, dpi=dpi)
        if image.isNull():
            raise AnnotationError('Image rendering failed')
        image.setDotsPerMeterX(round(dpi/.0254))
        image.setDotsPerMeterY(round(dpi/.0254))
        if not image.save(str(stage/'map.png'), 'PNG'):
            raise AnnotationError('Cannot save PNG')
        # A separate render verifies labels are actually placed, not only XML.
        settings = QgsMapSettings()
        settings.setLayers(ordered)
        settings.setDestinationCrs(destination)
        settings.setExtent(extent)
        settings.setOutputSize(QSize(2000, max(1, round(2000*extent.height()/extent.width()))))
        settings.setBackgroundColor(QColor('white'))
        job = QgsMapRendererParallelJob(settings)
        job.start()
        job.waitForFinished()
        if job.errors():
            raise AnnotationError('Map rendering errors: ' + repr([(e.layerID,e.message) for e in job.errors()]))
        job.renderedImage().save(str(stage/'preview.png'))
        labels = job.takeLabelingResults()
        labels = labels.allLabels() if labels else []
        if any(not label.isPinned for label in labels):
            raise AnnotationError('An annotation was moved from its fixed anchor')
        detail_results = render_views(project, ordered, stage, details, title)
        project.layoutManager().addLayout(layout)
        project.setFilePathStorage(Qgis.FilePathType.Relative)
        if not project.write(str(stage/'map.qgz')):
            raise AnnotationError('Project write failed')
        reopened = QgsProject()
        if not reopened.read(str(stage/'map.qgz')) or not all(l.isValid() for l in reopened.mapLayers().values()):
            raise AnnotationError('Project reopening failed')
        result = {'status':'PASS', 'qgis':Qgis.QGIS_VERSION, 'layers':report, 'rendered_labels':len(labels),
                  'font_size':font_size, 'font_unit':font_unit, 'font_family':font_family,
                  'render_crs':destination.toWkt(), 'page_mm':[width_mm,height_mm], 'dpi':dpi,
                  'input_verification':verification, 'project_reopened':True,
                  'excluded_layers':excluded, 'details':detail_results,
                  'limitations':['No original symbol-library or font/rotation reconstruction; gray linework.',
                                 'Pairing is a configurable layout heuristic; audit unresolved records.']}
        result['product_sha256'] = {str(p.relative_to(stage)):sha256(p) for p in stage.rglob('*')
                                    if p.is_file() and p.suffix != '.qgz~'}
        write_json(stage/'export.json', result)
        reopened.clear()
        project.clear()
        publish(stage, output)
    return result
