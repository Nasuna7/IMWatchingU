from pathlib import Path
from PyInstaller.utils.hooks import collect_submodules, collect_data_files

root = Path(SPECPATH).parent
hidden = collect_submodules('winrt') + collect_submodules('windows_capture')
app_name = 'IMWatchingU❤'


def napcat_datas():
    candidates = []
    import os

    if os.environ.get('IMWATCHINGU_NAPCAT_DIR'):
        candidates.append(Path(os.environ['IMWATCHINGU_NAPCAT_DIR']))
    candidates.extend(Path(drive) / 'NapCat.Shell' for drive in ('D:/', 'E:/'))
    source = next((path for path in candidates if path.is_dir()), None)
    if not source:
        return []
    skipped = {'cache', 'logs'}
    sensitive_config_names = {'webui.json', 'passkey.json'}
    sensitive_config_prefixes = ('onebot11_', 'napcat_', 'napcat_protocol_')
    datas = []
    for file in source.rglob('*'):
        relative = file.relative_to(source)
        if not file.is_file() or any(part in skipped for part in relative.parts):
            continue
        if relative.parts and relative.parts[0] == 'config':
            name = file.name
            if name in sensitive_config_names or name.startswith(sensitive_config_prefixes):
                continue
            if name != 'onebot11.json':
                continue
        if relative.suffix.lower() in ('.bak', '.log'):
            continue
        target = Path('runtime') / 'NapCat.Shell' / relative.parent
        datas.append((str(file), target.as_posix()))
    return datas


a = Analysis([str(root / 'src/screen_qq_ocr/__main__.py')], pathex=[str(root / 'src')],
             datas=collect_data_files('screen_qq_ocr') + napcat_datas(), hiddenimports=hidden,
             excludes=['tkinter', 'matplotlib', 'onnxruntime'])
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name=app_name, console=False,
          manifest=str(root / 'packaging/app.manifest'), icon=str(root / 'packaging/app.ico'))
coll = COLLECT(exe, a.binaries, a.datas, name=app_name)
