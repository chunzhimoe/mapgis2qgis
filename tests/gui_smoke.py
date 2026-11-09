"""Exercise an actual Tk window and the real conversion/rendering subprocess."""
import argparse
import json
from pathlib import Path
import tempfile
import time
from unittest.mock import patch

import native_fixtures as F
from mapgis_annotations.runtime import configure_runtime
from mapgis_annotations import export_native, verify_dataset


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('report', type=Path)
    parser.add_argument('--hold', action='store_true')
    parser.add_argument('--multi', action='store_true')
    parser.add_argument('--multi-shp', action='store_true')
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
        if args.multi or args.multi_shp:
            F.write_points(source/'extra.WT', [{'x':105.02,'y':35.02,'text':'多选'}],
                           proj=0, ellipsoid=7, scale=0)
            selected = (str(source/'map.WT'), str(source/'extra.WT'))
            if args.multi_shp:
                F.write_points(source/'unselected.WT', [{'x':105.03,'y':35.03,'text':'未选'}],
                               proj=0, ellipsoid=7, scale=0)
                shp = Path(temporary)/'shp'
                export_native(source, shp)
                selected = (str(shp/'map_点.shp'), str(shp/'extra_点.shp'))
            else:
                (source/'unselected.WT').write_bytes(b'not selected')
            with patch('tkinter.filedialog.askopenfilenames', return_value=selected):
                app.choose_source_file()
            assert len(app.source_value()) == 2
        app.output.set(str(output))
        app.render.set(True)
        profile = Path(temporary)/'部分配置.json'
        profile.write_text(json.dumps({'strict_native':False}), encoding='utf-8-sig')
        app.load_profile(profile)
        assert app.render.get(), 'Loading a partial profile must retain the drawing checkbox'
        assert app.auto_font.get()
        app.width.set('180')
        app.dpi.set('96')
        deadline = time.monotonic()+90
        errors = []
        def check():
            if app.result:
                verify_dataset(output)
                assert app.picture.width() > 0
                assert json.loads((output/'map/export.json').read_text())['auto_font_size']
                assert all(str(button['state']) == 'normal' for button, _ in app.result_buttons)
                if args.multi or args.multi_shp:
                    manifest = json.loads((output/'manifest.json').read_text(encoding='utf-8'))
                    if args.multi:
                        assert manifest['native_summary']['layers'] == 2
                        assert manifest['native_summary']['unreadable'] == 0
                    else:
                        assert manifest['input_format'] == 'shp'
                        assert manifest['annotations']['converted_layers'] == 2
                        verify_dataset(output/'annotations')
                        assert not any('unselected' in p for p in manifest['source_sha256'])
                    assert manifest['audit']['records'] == 3
                    assert json.loads((output/'map/export.json').read_text())['rendered_labels'] == 3
                result = {'status':'PASS','actual_window':True,'background_subprocess':True,
                          'map_rendered':(output/'map/map.png').exists(),'preview_visible':True,
                          'window_size':[root.winfo_width(),root.winfo_height()]}
                if args.multi or args.multi_shp:
                    result.update(multiselect=True, selected_layers=2, unselected_layer_excluded=True,
                                  source_hashes_verified=True, pdf_exported=(output/'map/map.pdf').is_file())
                    result['input_format'] = 'shp' if args.multi_shp else 'native'
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
