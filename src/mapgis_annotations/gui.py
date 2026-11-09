"""A Tk desktop UI; processing always runs in an isolated child process."""
import importlib.util
import json
import math
import os
from pathlib import Path
import queue
import subprocess
import sys

from .errors import AnnotationError, MissingDependencyError
from .gui_job import JobRunner, make_job

STAGES = {'prepare':'准备数据', 'native':'读取原生与判定坐标', 'audit':'核查几何与属性',
          'annotations':'标准注记与空间关联', 'render':'绘制全图与局部', 'verify':'核查产物',
          'publish':'发布结果', 'complete':'完成'}


class Workbench:
    def __init__(self, root):
        import tkinter as tk
        from tkinter import ttk
        from tkinter.scrolledtext import ScrolledText
        self.root, self.runner, self.closing, self.result = root, JobRunner(), False, None
        self.controls = []
        root.title('MapGIS 转换工作台')
        root.geometry('1120x850')
        root.minsize(960, 750)
        style = ttk.Style(root)
        if 'clam' in style.theme_names():
            style.theme_use('clam')
        style.configure('TFrame', background='#f4f6f8')
        style.configure('TLabel', background='#f4f6f8', foreground='#243746', font=('sans-serif', 11))
        style.configure('Title.TLabel', font=('sans-serif', 22, 'bold'))
        style.configure('Accent.TButton', background='#235b72', foreground='white', padding=(16,9))
        style.configure('TButton', padding=(9,6))
        sidebar = tk.Frame(root, background='#183442', width=210)
        sidebar.pack(side='left', fill='y')
        sidebar.pack_propagate(False)
        tk.Label(sidebar, text='MapGIS\n转换工作台', background='#183442', foreground='white',
                 font=('sans-serif', 23, 'bold'), justify='left').pack(anchor='w', padx=24, pady=(34,28))
        for text in ('01   原生读取与坐标', '02   注记与空间关联', '03   全图与局部预览', '04   核验与成果导出'):
            tk.Label(sidebar, text=text, background='#183442', foreground='#c5d9e1',
                     font=('sans-serif', 12), anchor='w').pack(fill='x', padx=24, pady=13)
        tk.Label(sidebar, text='保留原数据\n记录每一项判定', background='#183442', foreground='#8eabb8',
                 font=('sans-serif', 11), justify='left').pack(side='bottom', anchor='w', padx=24, pady=28)
        body = ttk.Frame(root, padding=24)
        body.pack(side='left', expand=True, fill='both')
        ttk.Label(body, text='从原生图件到可核验成果', style='Title.TLabel').pack(anchor='w')
        ttk.Label(body, text='支持 MapGIS 6.x 点、线、区、工程文件及已导出的 SHP').pack(anchor='w', pady=(6,18))
        self.source, self.output, self.profile = (tk.StringVar() for _ in range(3))
        self.form = ttk.Frame(body)
        self.form.pack(fill='x')
        self.form.columnconfigure(1, weight=1)
        self._path_row(0, '输入数据', self.source, [('文件夹', self.choose_source_folder), ('文件/工程', self.choose_source_file)])
        self._path_row(1, '新输出目录', self.output, [('选择位置', self.choose_output)])
        self._path_row(2, '处理配置', self.profile, [('选择 JSON', self.choose_profile), ('五龙沟示例', self.example)])
        advanced = ttk.LabelFrame(body, text='坐标与制图选项', padding=12)
        advanced.pack(fill='x', pady=(15,12))
        self.epsg, self.factor = tk.StringVar(), tk.StringVar()
        self.dpi, self.width, self.size = tk.StringVar(value='300'), tk.StringVar(value='1000'), tk.StringVar(value='9')
        self.unit = tk.StringVar(value='points')
        for col, (label, variable) in enumerate((('EPSG（留空自动）',self.epsg), ('换算系数（自动）',self.factor),
                                                ('幅宽 mm',self.width), ('DPI',self.dpi), ('字号',self.size))):
            ttk.Label(advanced, text=label).grid(row=0, column=col, sticky='w', padx=4)
            entry = ttk.Entry(advanced, textvariable=variable, width=15 if col < 2 else 9)
            entry.grid(row=1, column=col, sticky='ew', padx=4, pady=(5,9))
            self.controls.append(entry)
            advanced.columnconfigure(col, weight=1)
        self.render = tk.BooleanVar(value=importlib.util.find_spec('qgis') is not None)
        check = ttk.Checkbutton(advanced, text='生成全图、PDF 和 QGIS 工程', variable=self.render)
        check.grid(row=2, column=0, columnspan=3, sticky='w')
        self.controls.append(check)
        unit = ttk.Combobox(advanced, textvariable=self.unit, values=['points','map'], state='readonly', width=10)
        unit.grid(row=2, column=3, columnspan=2, sticky='e', padx=4)
        self.controls.append(unit)
        bar = ttk.Frame(body)
        bar.pack(fill='x', pady=4)
        self.start_button = ttk.Button(bar, text='开始转换', style='Accent.TButton', command=self.start)
        self.start_button.pack(side='left')
        self.cancel_button = ttk.Button(bar, text='停止', command=self.cancel, state='disabled')
        self.cancel_button.pack(side='left', padx=10)
        self.state = tk.StringVar(value='就绪 · 请选择数据和输出位置')
        ttk.Label(body, textvariable=self.state, wraplength=800).pack(anchor='w', pady=(10,6))
        self.progress = ttk.Progressbar(body, maximum=100)
        self.progress.pack(fill='x', pady=(0,12))
        self.tabs = ttk.Notebook(body)
        self.tabs.pack(fill='both', expand=True)
        log_frame, self.preview_frame = ttk.Frame(self.tabs), ttk.Frame(self.tabs)
        self.tabs.add(log_frame, text='运行记录')
        self.tabs.add(self.preview_frame, text='成果预览')
        self.log = ScrolledText(log_frame, height=10, wrap='word', relief='flat', font=('sans-serif', 11), state='disabled')
        self.log.pack(fill='both', expand=True, padx=2, pady=2)
        self.preview = ttk.Label(self.preview_frame, text='完成绘图后在这里查看全图与局部预览', anchor='center')
        self.preview.pack(fill='both', expand=True)
        actions = ttk.Frame(body)
        actions.pack(fill='x', pady=(12,0))
        self.result_buttons = []
        for title, relative in (('打开数据','annotations'), ('打开全图','map/map.png'), ('打开工程','map/map.qgz')):
            button = ttk.Button(actions, text=title, state='disabled', command=lambda p=relative:self.open_result(p))
            button.pack(side='left', padx=(0,8))
            self.result_buttons.append((button, relative))
        root.protocol('WM_DELETE_WINDOW', self.close)
        root.after(100, self.poll)

    def _path_row(self, row, label, variable, buttons):
        from tkinter import ttk
        ttk.Label(self.form, text=label).grid(row=row, column=0, sticky='w', padx=(0,10), pady=6)
        entry = ttk.Entry(self.form, textvariable=variable)
        entry.grid(row=row, column=1, sticky='ew', pady=6)
        self.controls.append(entry)
        for i, (title, callback) in enumerate(buttons):
            button = ttk.Button(self.form, text=title, command=callback)
            button.grid(row=row, column=2+i, padx=(8,0), pady=6)
            self.controls.append(button)

    def choose_source_folder(self):
        from tkinter import filedialog
        path = filedialog.askdirectory(title='选择 MapGIS 或 SHP 文件夹')
        if path:
            self.source.set(path)

    def choose_source_file(self):
        from tkinter import filedialog
        path = filedialog.askopenfilename(title='选择 MapGIS 文件', filetypes=[('MapGIS','*.MPJ *.mpj *.WT *.wt *.WL *.wl *.WP *.wp'),('所有文件','*')])
        if path:
            self.source.set(path)

    def choose_output(self):
        from tkinter import filedialog
        parent = filedialog.askdirectory(title='选择输出父目录，将在其中新建结果文件夹')
        if parent:
            stem = Path(self.source.get()).stem if self.source.get() else 'MapGIS'
            path, index = Path(parent)/(stem+'_转换结果'), 2
            while path.exists():
                path = Path(parent)/(stem+'_转换结果_'+str(index))
                index += 1
            self.output.set(str(path))

    def choose_profile(self):
        from tkinter import filedialog
        path = filedialog.askopenfilename(title='选择处理配置', filetypes=[('JSON','*.json')])
        if path:
            self.load_profile(path)

    def example(self):
        self.load_profile(Path(__file__).parent/'profiles/wulonggou_pipeline.json')

    def load_profile(self, path):
        from tkinter import messagebox
        try:
            from .pipeline import PipelineConfig
            config = PipelineConfig.from_dict(json.loads(Path(path).read_text(encoding='utf-8')))
            self.profile.set(str(path))
            self.render.set(config.render.get('enabled', False))
            self.size.set(str(config.render.get('font_size',9)))
            self.unit.set(config.render.get('font_unit','points'))
            self.width.set(str(config.render.get('width_mm',1000)))
            self.dpi.set(str(config.render.get('dpi',300)))
        except (AnnotationError, OSError, ValueError) as exc:
            messagebox.showerror('配置无法读取', str(exc))

    def append(self, text):
        self.log.configure(state='normal')
        self.log.insert('end', text+'\n')
        self.log.see('end')
        self.log.configure(state='disabled')

    def start(self):
        from tkinter import messagebox
        try:
            spec = make_job(self.source.get(), self.output.get(), self.profile.get(), render=self.render.get(),
                            epsg=self.epsg.get(), factor=self.factor.get(), dpi=self.dpi.get(), width=self.width.get(),
                            font_size=self.size.get(), font_unit=self.unit.get())
            self.runner.start(spec)
        except (AnnotationError, OSError, ValueError) as exc:
            messagebox.showerror('无法开始', str(exc))
            return
        self.result = None
        self.progress['value'] = 0
        self.state.set('正在准备数据…')
        self.append('开始：'+str(spec.source)+'\n输出：'+str(spec.output))
        self.start_button.configure(state='disabled')
        self.cancel_button.configure(state='normal')
        for widget in self.controls:
            widget.configure(state='disabled')
        for button, _ in self.result_buttons:
            button.configure(state='disabled')

    def cancel(self):
        self.runner.cancel()
        self.state.set('正在停止，当前步骤结束后清理临时结果…')
        self.cancel_button.configure(state='disabled')

    def poll(self):
        import tkinter as tk
        from tkinter import ttk
        try:
            while True:
                event = self.runner.events.get_nowait()
                if event['type'] == 'progress':
                    self.progress['value'] = event['percent']
                    label = STAGES.get(event['stage'],event['stage'])
                    self.state.set(label+'…')
                    self.append(label)
                else:
                    self.start_button.configure(state='normal')
                    self.cancel_button.configure(state='disabled')
                    for widget in self.controls:
                        widget.configure(state='readonly' if isinstance(widget, ttk.Combobox) else 'normal')
                    if event['type'] == 'complete':
                        self.result = Path(event['result']['output'])
                        result = event['result']
                        self.progress['value'] = 100
                        self.state.set('完成 · %s 个要素，%s 条注记标准化' % (result['audit']['records'], result['annotations']['changed_notes']))
                        self.append('核验通过：'+str(self.result))
                        for button, relative in self.result_buttons:
                            button.configure(state='normal' if (self.result/relative).exists() else 'disabled')
                        picture = next((self.result/p for p in ('map/overview.png','map/preview.png') if (self.result/p).exists()), None)
                        if picture:
                            self.tabs.select(self.preview_frame)
                            self.root.update_idletasks()
                            self.picture = tk.PhotoImage(file=str(picture))
                            width = max(200, self.preview_frame.winfo_width()-12)
                            height = max(80, self.preview_frame.winfo_height()-12)
                            factor = max(1, math.ceil(self.picture.width()/width), math.ceil(self.picture.height()/height))
                            self.picture = self.picture.subsample(factor)
                            self.preview.configure(image=self.picture, text='')
                    else:
                        self.state.set('已停止' if event['type']=='cancelled' else '处理失败 · 查看运行记录')
                        self.append(event['message'])
                    if self.closing:
                        self.root.destroy()
                        return
        except queue.Empty:
            pass
        self.root.after(100, self.poll)

    def open_result(self, relative):
        if not self.result:
            return
        path = self.result/relative
        if os.name == 'nt':
            os.startfile(path)
        else:
            subprocess.Popen(['open' if sys.platform=='darwin' else 'xdg-open', str(path)])

    def close(self):
        if self.runner.running:
            self.closing = True
            self.cancel()
        else:
            self.root.destroy()


def run_gui():
    try:
        import tkinter as tk
        root = tk.Tk()
    except ImportError as exc:
        raise MissingDependencyError('桌面GUI需要Tcl/Tk；离线安装包已包含，源码环境请安装tk') from exc
    except tk.TclError as exc:
        raise AnnotationError('无法启动图形界面：'+str(exc)) from exc
    Workbench(root)
    root.mainloop()
    return 0
