"""Normalize explicit selections without broadening them to their folders."""
from pathlib import Path
from os import PathLike

from .errors import AnnotationError


def normalize_source(source):
    selected = isinstance(source, (list, tuple))
    values = source if selected else [source]
    if not values:
        raise AnnotationError('请选择至少一个输入文件')
    paths = []
    for value in values:
        if not isinstance(value, (str, PathLike)) or not str(value).strip():
            raise AnnotationError('输入须为文件路径或文件路径列表')
        path = Path(value).expanduser().resolve()
        if not path.exists():
            raise AnnotationError('Input does not exist: '+str(path))
        if selected and not path.is_file():
            raise AnnotationError('多选列表只能包含文件；导入整个目录请使用文件夹选择')
        if path not in paths:
            paths.append(path)
    return tuple(paths) if selected else paths[0]


def source_paths(source):
    return source if isinstance(source, tuple) else (source,)


def source_description(source):
    return [str(p) for p in source] if isinstance(source, tuple) else str(source)


def validate_output(source, output):
    output = Path(output).expanduser().resolve()
    for path in source_paths(source):
        root = path if path.is_dir() else path.parent
        if output.exists() or output.is_relative_to(root) or root.is_relative_to(output):
            raise AnnotationError('Output must be a new directory outside the input tree')
    return output
