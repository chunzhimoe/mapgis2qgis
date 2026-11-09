"""Exercise an actual Tk window and the real conversion/rendering subprocess."""
import argparse
import json
from pathlib import Path
import tempfile
import time

import native_fixtures as F
from mapgis_annotations.runtime import configure_runtime
from mapgis_annotations import verify_dataset


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('report', type=Path)
    parser.add_argument('--hold', action='store_true')
    args = parser.parse_args()
    configure_runtime()
    import tkinter as tk
    from mapgis_annotations.gui import Workbench
    with tempfile.TemporaryDirectory(prefix='mapgis-gui-smoke-') as temporary:
        source = Path(temporary)/'input'
        source.mkdir()
        F.write_points(source/'map.WT', [{'x':105,'y':35,'text':'A#-2'}, {'x':105.01,'y':35.01,'text':'测试'}],
                       proj=0, ellipsoid=7, scale=0)
        output = Path(temporary)/'result'
        root = tk.Tk()
        app = Workbench(root)
        app.source.set(str(source))
        app.output.set(str(output))
        app.render.set(True)
        profile = Path(temporary)/'部分配置.json'
        profile.write_text(json.dumps({'strict_native':False}), encoding='utf-8-sig')
        app.load_profile(profile)
        assert app.render.get(), 'Loading a partial profile must retain the drawing checkbox'
        app.width.set('180')
        app.dpi.set('96')
        deadline = time.monotonic()+90
        errors = []
        def check():
            if app.result:
                verify_dataset(output)
                assert app.picture.width() > 0
                assert all(str(button['state']) == 'normal' for button, _ in app.result_buttons)
                result = {'status':'PASS','actual_window':True,'background_subprocess':True,
                          'map_rendered':(output/'map/map.png').exists(),'preview_visible':True,
                          'window_size':[root.winfo_width(),root.winfo_height()]}
                args.report.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
                print(json.dumps(result, ensure_ascii=False), flush=True)
                if not args.hold:
                    root.after(500, root.destroy)
                return
            if time.monotonic() > deadline or app.state.get().startswith('处理失败'):
                errors.append(app.log.get('1.0','end'))
                root.destroy()
                return
            root.after(100, check)
        root.after(150, app.start)
        root.after(250, check)
        root.mainloop()
        if errors:
            raise AssertionError(errors)


if __name__ == '__main__':
    main()
