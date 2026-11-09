"""Configurable detail views; no dependency on any map name or region."""
import math
from pathlib import Path

from .errors import AnnotationError


def validate_views(views):
    if not isinstance(views, list) or len(views) > 6:
        raise AnnotationError('details must be a list of at most six views')
    names = set()
    allowed = {'name', 'label', 'extent', 'layer', 'field', 'text', 'pick', 'padding', 'size', 'layers'}
    for view in views:
        if not isinstance(view, dict) or set(view) - allowed:
            raise AnnotationError('Unknown detail-view options')
        name = view.get('name', '')
        if not isinstance(name, str) or not name or name in ('.', '..') or any(c in name for c in '/\\:') or name in names:
            raise AnnotationError('Each detail needs a unique simple filename in name')
        names.add(name)
        if 'extent' not in view and not {'layer', 'text'} <= set(view):
            raise AnnotationError('A detail needs extent or layer/text')
        for key, length, default in (('extent', 4, None), ('padding', 4, [1000]*4), ('size', 2, [1600, 1050])):
            value = view.get(key, default)
            if value is None:
                continue
            if not isinstance(value, list) or len(value) != length or any(
                    not isinstance(n, (int, float)) or not math.isfinite(n) for n in value):
                raise AnnotationError('Invalid detail ' + key)
            if key != 'extent' and any(n <= 0 for n in value):
                raise AnnotationError('Detail padding and size must be positive')
        if 'extent' in view and (view['extent'][2] <= view['extent'][0] or view['extent'][3] <= view['extent'][1]):
            raise AnnotationError('Invalid detail extent bounds')
        size = view.get('size', [1600, 1050])
        if any(int(n) != n for n in size) or size[0]*size[1] > 16000000:
            raise AnnotationError('Detail size must be integral and at most 16 million pixels')
        if view.get('pick', 'first') not in ('first', 'middle'):
            raise AnnotationError('Detail pick must be first or middle')
        if 'layers' in view and (not isinstance(view['layers'], list) or not view['layers']):
            raise AnnotationError('Detail layers must be a nonempty list')


def render_views(project, ordered, output, views, title, font_family='sans-serif'):
    from qgis.core import (QgsMapSettings, QgsMapRendererParallelJob, QgsRectangle, QgsCoordinateTransform)
    from qgis.PyQt.QtCore import QSize, Qt
    from qgis.PyQt.QtGui import QImage, QPainter, QFont, QColor
    results = []
    by_name = {layer.name(): layer for layer in ordered}
    for view in views:
        selected = None
        if 'extent' in view:
            extent = QgsRectangle(*view['extent'])
        else:
            layer = by_name.get(view['layer'])
            field = view.get('field', 'LABEL_TXT')
            if layer is None or field not in layer.fields().names():
                raise AnnotationError('Detail layer/field not found: ' + view['name'])
            candidates = [f for f in layer.getFeatures() if str(f[field]) == view['text'] and not f.geometry().isEmpty()]
            if not candidates:
                raise AnnotationError('Detail text not found: ' + view['name'])
            candidates.sort(key=lambda f: f.geometry().centroid().asPoint().x())
            selected = candidates[len(candidates)//2 if view.get('pick') == 'middle' else 0]
            point = QgsCoordinateTransform(layer.crs(), project.crs(), project).transform(selected.geometry().centroid().asPoint())
            left, bottom, right, top = view.get('padding', [1000]*4)
            extent = QgsRectangle(point.x()-left, point.y()-bottom, point.x()+right, point.y()+top)
        names = view.get('layers', list(by_name))
        if set(names) - set(by_name):
            raise AnnotationError('Unknown layer in detail: ' + view['name'])
        settings = QgsMapSettings()
        settings.setLayers([by_name[name] for name in names])
        settings.setDestinationCrs(project.crs())
        settings.setExtent(extent)
        settings.setOutputSize(QSize(*view.get('size', [1600, 1050])))
        settings.setBackgroundColor(QColor('white'))
        job = QgsMapRendererParallelJob(settings)
        job.start()
        job.waitForFinished()
        if job.errors():
            raise AnnotationError('Detail render failed: ' + view['name'])
        filename = Path('details') / (view['name'] + '.png')
        (output / filename).parent.mkdir(exist_ok=True)
        if not job.renderedImage().save(str(output / filename)):
            raise AnnotationError('Cannot write detail PNG')
        labels = job.takeLabelingResults()
        labels = labels.allLabels() if labels else []
        if any(not label.isPinned for label in labels):
            raise AnnotationError('A detail annotation moved from its anchor')
        if selected is not None and layer.labelsEnabled() and not any(
                label.layerID == layer.id() and label.featureId == selected.id() for label in labels):
            raise AnnotationError('Selected detail annotation was not placed')
        results.append({'name': view['name'], 'path': filename.as_posix(), 'rendered_labels': len(labels),
                        'selected_text': view.get('text'), 'selected_feature': selected.id() if selected is not None else None})
    if results:
        full = QImage(str(output / 'preview.png'))
        cell_width, cell_height = 965, 690
        top = 80 + full.height()
        panel = QImage(2000, top + math.ceil(len(results)/2)*cell_height + 20, QImage.Format_ARGB32)
        panel.fill(QColor('white'))
        painter = QPainter(panel)
        painter.setPen(QColor('#202020'))
        painter.setFont(QFont(font_family, 24))
        painter.drawText(20, 45, str(title)[:100])
        painter.drawImage(0, 65, full)
        for index, (view, result) in enumerate(zip(views, results)):
            x, y = 20 + (index % 2)*995, top + (index//2)*cell_height
            painter.setFont(QFont(font_family, 18))
            painter.drawText(x, y+25, str(view.get('label', view['name']))[:60])
            picture = QImage(str(output/result['path'])).scaled(cell_width, cell_height-50, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            painter.drawImage(x, y+40, picture)
        painter.end()
        if not panel.save(str(output/'overview.png')):
            raise AnnotationError('Cannot save overview')
    return results
