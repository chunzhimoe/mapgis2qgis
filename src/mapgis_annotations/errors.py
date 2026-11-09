class AnnotationError(ValueError):
    """An input cannot be processed without an explicit decision or data loss."""


class MissingDependencyError(AnnotationError):
    """An optional workflow requires an additional runtime."""


class NativeFormatError(AnnotationError):
    """A file is not a readable native MapGIS 6.x work or project file."""
