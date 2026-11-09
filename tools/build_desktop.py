"""Build the self-contained macOS arm64 PKG and wrap it in a DMG."""
import argparse
import configparser
import hashlib
import json
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def make_context(wheel, directory, version):
    directory = Path(directory).resolve()
    directory.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(wheel, directory/Path(wheel).name)
    for name in ('post_install.sh','install_desktop.py'):
        shutil.copyfile(ROOT/'packaging'/name, directory/name)
    license_text = (ROOT/'LICENSE').read_text()+'\n\n'+(ROOT/'THIRD_PARTY_NOTICES.md').read_text()+'\n\n'+(ROOT/'licenses/Apache-2.0.txt').read_text()
    (directory/'LICENSE.txt').write_text(license_text, encoding='utf-8')
    spec = {'name':'MapGIS2QGIS', 'version':version, 'channels':['conda-forge'],
            'specs':['python >=3.11,<3.12','qgis >=3.40,<3.42','pyshp >=2.3,<4','pyproj >=3.4,<4',
                     'shapely >=2,<3','tk >=8.6,<9','pip'],
            'installer_type':'pkg', 'installer_filename':'MapGIS2QGIS-'+version+'-macOS-arm64.pkg',
            'pkg_name':'MapGIS2QGIS-'+version, 'default_location_pkg':'Applications',
            'reverse_domain_identifier':'io.github.chunzhimoe', 'license_file':'LICENSE.txt',
            'post_install':'post_install.sh', 'initialize_conda':False, 'register_envs':False,
            'menu_packages':[], 'keep_pkgs':False, 'welcome_image':'',
            'welcome_text':'Offline MapGIS conversion and rendering workbench. Python, Tk and QGIS are included.',
            'readme_text':'Install, then open MapGIS2QGIS.app inside the installation folder in Applications.',
            'conclusion_text':'Open the versioned MapGIS2QGIS application in Applications to start.',
            'build_outputs':['licenses','info.json','lockfile','pkgs_list'],
            'extra_files':[{Path(wheel).name:'app_payload/'+Path(wheel).name},
                           {'install_desktop.py':'app_payload/install_desktop.py'}, {'LICENSE.txt':'app_payload/LICENSE.txt'}]}
    (directory/'construct.yaml').write_text(json.dumps(spec, indent=2), encoding='utf-8')
    return spec


def source_archive(destination):
    with zipfile.ZipFile(destination, 'w', zipfile.ZIP_DEFLATED) as archive:
        for name in ('src','tests','tools','packaging','docs','examples','.github'):
            for path in (ROOT/name).rglob('*'):
                if path.is_file() and '__pycache__' not in path.parts and not any(p.endswith('.egg-info') for p in path.parts) and path.suffix not in ('.pyc','.pyo'):
                    archive.write(path, path.relative_to(ROOT))
        for name in ('README.md','LICENSE','THIRD_PARTY_NOTICES.md','setup.cfg','setup.py','pyproject.toml','MANIFEST.in'):
            archive.write(ROOT/name, name)
        for path in (ROOT/'licenses').glob('*'):
            archive.write(path, path.relative_to(ROOT))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--context', type=Path, default=ROOT/'build/desktop-arm64')
    parser.add_argument('--output', type=Path, default=ROOT/'dist/installers')
    parser.add_argument('--prepare-only', action='store_true')
    args = parser.parse_args()
    if sys.platform != 'darwin' or platform.machine() != 'arm64':
        raise RuntimeError('The full installer is built on macOS Apple Silicon only')
    config = configparser.ConfigParser()
    config.read(ROOT/'setup.cfg')
    version = config['metadata']['version']
    wheel = ROOT/'dist'/('mapgis_annotations-'+version+'-py3-none-any.whl')
    subprocess.run([sys.executable,'-m','pip','wheel','--no-deps','--no-build-isolation',str(ROOT),'-w',str(ROOT/'dist')], check=True)
    make_context(wheel, args.context, version)
    if args.prepare_only:
        return
    args.output.mkdir(parents=True, exist_ok=True)
    subprocess.run(['constructor',str(args.context),'--output-dir',str(args.output)], check=True)
    package = args.output/('MapGIS2QGIS-'+version+'-macOS-arm64.pkg')
    if not package.is_file():
        raise RuntimeError('Constructor did not produce the installer')
    image_source = args.context/'dmg'
    image_source.mkdir(exist_ok=True)
    shutil.copyfile(package, image_source/package.name)
    for path in args.output.iterdir():
        if path.is_file() and path.suffix not in ('.pkg','.dmg'):
            shutil.copyfile(path, image_source/path.name)
    source_archive(image_source/'MapGIS2QGIS-source.zip')
    shutil.copyfile(args.context/'LICENSE.txt', image_source/'LICENSE.txt')
    (image_source/'安装说明.txt').write_text('MapGIS2QGIS — macOS Apple Silicon\n\n双击 PKG 安装器。安装后在 Applications 中打开带版本号的 MapGIS2QGIS 应用。\n'
        '本安装包内含 Python、GUI、转换库和 QGIS 渲染环境；安装和使用无需再下载依赖。\n'
        '未使用 Apple Developer 证书签名或公证。\n第三方组件许可证、版本与构建记录随安装包提供。\n', encoding='utf-8')
    dmg = args.output/('MapGIS2QGIS-'+version+'-macOS-arm64.dmg')
    subprocess.run(['hdiutil','create','-volname','MapGIS2QGIS','-srcfolder',str(image_source),'-ov','-format','UDZO',str(dmg)], check=True)
    subprocess.run(['hdiutil','verify',str(dmg)], check=True)
    report = {'version':version,'architecture':'arm64','includes':['Python','Tk','MapGIS library','QGIS','PyProj','Shapely'],
              'signed':False,'notarized':False,'sha256':hashlib.sha256(dmg.read_bytes()).hexdigest(),'bytes':dmg.stat().st_size}
    (args.output/'build.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    (args.output/'SHA256SUMS.txt').write_text(report['sha256']+'  '+dmg.name+'\n', encoding='utf-8')


if __name__ == '__main__':
    main()
