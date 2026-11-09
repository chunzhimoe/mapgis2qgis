"""Public API. Importing it never imports QGIS or initializes an application."""
from .errors import AnnotationError, MissingDependencyError, NativeFormatError
from .notes import ParsedNote, parse_note
from .shapefiles import ConversionConfig, convert_layer, inspect_dataset
from .workflow import WorkflowConfig, run_workflow, verify_dataset
from .spatial import AnnotationPoint, PairingConfig, pair_annotations, crosswalk
from .mapgis_native import NativeLayer, read_native_layer, read_mpj_paths, write_shapefile
from .georef import export_native
from .pipeline import PipelineConfig, PipelineCancelled, run_pipeline

__version__ = '0.4.2'
__all__ = ['AnnotationError', 'MissingDependencyError', 'NativeFormatError', 'ParsedNote', 'parse_note',
           'ConversionConfig', 'convert_layer', 'inspect_dataset', 'WorkflowConfig',
           'run_workflow', 'verify_dataset', 'AnnotationPoint', 'PairingConfig',
           'pair_annotations', 'crosswalk', 'NativeLayer', 'read_native_layer', 'read_mpj_paths',
           'write_shapefile', 'export_native', 'PipelineConfig', 'PipelineCancelled', 'run_pipeline']
