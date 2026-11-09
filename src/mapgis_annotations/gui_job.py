"""GUI-independent subprocess worker, with a queue for main-thread UI updates."""
from dataclasses import asdict, dataclass
import json
import math
import os
from pathlib import Path
import queue
import subprocess
import sys
import tempfile
import threading
import time

from .errors import AnnotationError
from .pipeline import PipelineConfig


@dataclass
class JobSpec:
    source: Path
    output: Path
    config: dict


def make_job(source, output, profile='', *, render=False, epsg='', factor='', dpi='300', width='1000',
             font_size='9', font_unit='points', input_format='auto'):
    if not str(source).strip() or not str(output).strip():
        raise AnnotationError('请选择输入数据和输出目录')
    source, output = Path(source).expanduser().resolve(), Path(output).expanduser().resolve()
    root = source if source.is_dir() else source.parent
    if not source.exists():
        raise AnnotationError('输入数据不存在')
    if output.exists() or output.is_relative_to(root) or root.is_relative_to(output):
        raise AnnotationError('输出须为输入目录以外的新目录')
    config = PipelineConfig.from_dict(json.loads(Path(profile).read_text(encoding='utf-8'))) if profile else PipelineConfig()
    config.input_format = input_format
    try:
        if epsg.strip():
            config.native['epsg'] = int(epsg)
        if factor.strip():
            config.native['factor'] = float(factor)
        config.render.update(enabled=bool(render), dpi=int(dpi), width_mm=float(width),
                             font_size=float(font_size), font_unit=font_unit)
    except ValueError as exc:
        raise AnnotationError('EPSG/DPI须为整数；比例系数、幅宽和字号须为数字') from exc
    for value in (config.render['dpi'], config.render['width_mm'], config.render['font_size'], config.native.get('factor', 1)):
        if not math.isfinite(value) or value <= 0:
            raise AnnotationError('比例系数、幅宽、DPI和字号必须是有限正数')
    config.validate()
    return JobSpec(source, output, asdict(config))


class JobRunner:
    def __init__(self):
        self.events = queue.Queue()
        self.cancel_requested = threading.Event()
        self.thread = None

    @property
    def running(self):
        return self.thread is not None and self.thread.is_alive()

    def start(self, spec):
        if self.running:
            raise AnnotationError('已有任务正在运行')
        self.cancel_requested.clear()
        self.thread = threading.Thread(target=self._run, args=(spec,), daemon=True)
        self.thread.start()

    def cancel(self):
        self.cancel_requested.set()

    def _run(self, spec):
        try:
            with tempfile.TemporaryDirectory(prefix='mapgis-gui-') as temporary:
                root = Path(temporary)
                config, events, cancel, log = (root/name for name in ('config.json','events.jsonl','cancel','worker.log'))
                config.write_text(json.dumps(spec.config, ensure_ascii=False), encoding='utf-8')
                command = [sys.executable, '-m', 'mapgis_annotations', 'pipeline', str(spec.source), str(spec.output),
                           '--config', str(config), '--events', str(events), '--cancel-file', str(cancel)]
                env = dict(os.environ, PYTHONIOENCODING='utf-8', PYTHONUNBUFFERED='1')
                flags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
                position = 0
                with log.open('wb') as handle:
                    if self.cancel_requested.is_set():
                        cancel.touch()
                    process = subprocess.Popen(command, stdout=handle, stderr=subprocess.STDOUT, env=env, creationflags=flags)
                    while True:
                        if self.cancel_requested.is_set() and not cancel.exists():
                            cancel.touch()
                        if events.exists():
                            with events.open(encoding='utf-8') as stream:
                                stream.seek(position)
                                while True:
                                    start = stream.tell()
                                    line = stream.readline()
                                    if not line or not line.endswith('\n'):
                                        position = start
                                        break
                                    self.events.put({'type':'progress', **json.loads(line)})
                                    position = stream.tell()
                        if process.poll() is not None:
                            break
                        time.sleep(.1)
                text = log.read_text(encoding='utf-8', errors='replace')
                if process.returncode == 0:
                    result = json.loads((spec.output/'manifest.json').read_text(encoding='utf-8'))
                    self.events.put({'type':'complete','result':result})
                elif self.cancel_requested.is_set():
                    self.events.put({'type':'cancelled','message':'任务已停止，未发布输出目录'})
                else:
                    self.events.put({'type':'error','message':text[-10000:] or '转换失败，未生成结果'})
        except Exception as exc:
            self.events.put({'type':'error','message':str(exc)})
