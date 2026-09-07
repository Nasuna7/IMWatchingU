import json
import os
import sys
import tempfile
from pathlib import Path


def bundled_napcat():
    bases = []
    env = os.environ.get("IMWATCHINGU_NAPCAT_DIR")
    if env:
        bases.append(Path(env))
    if getattr(sys, "frozen", False):
        bases.append(Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent)) / "runtime" / "NapCat.Shell")
    bases.extend(Path(drive) / "NapCat.Shell" for drive in ("D:/", "E:/"))
    for base in bases:
        launcher = next(
            (base / name for name in ("launcher-user.bat", "launcher.bat") if (base / name).is_file()), None
        )
        config = base / "config"
        if launcher:
            onebot = next(
                (item.name for item in config.glob("onebot11*.json") if item.name == "onebot11.json"),
                "onebot11.json",
            )
            return {"launcher": str(launcher), "config_dir": str(config), "onebot_config": onebot}
    return {"launcher": "", "config_dir": "", "onebot_config": "onebot11.json"}


DEFAULTS = {
    "schema_version": 1,
    "ocr": {"engine": "windows", "interval": 3, "max_edge": 1920, "preprocess": True, "tesseract": ""},
    "capture": {"source_id": "", "roi": [0, 0, 1, 1]},
    "napcat": bundled_napcat(),
    "flash": {"enabled": False, "cooldown": 30, "sound": "双短鸣"},
    "appearance": {"reduce_motion": False, "low_resource": False, "theme": "light"},
    "lifecycle": {"close_to_tray": True},
}


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(dir=path.parent, prefix=path.name, suffix=".tmp")
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


class Settings:
    def __init__(self, path):
        self.path = Path(path)
        self.values = json.loads(json.dumps(DEFAULTS))
        if self.path.exists():
            try:
                data = json.loads(self.path.read_text(encoding="utf-8"))
                if data.get("schema_version") != 1:
                    raise ValueError("不支持的设置版本")
                for group in DEFAULTS:
                    if isinstance(DEFAULTS[group], dict) and group in data:
                        self.values[group].update(data[group])
            except (ValueError, TypeError, AttributeError) as error:
                raise ValueError(f"设置损坏或不兼容，已保留原文件：{self.path}") from error

    def save(self, values):
        atomic_json(self.path, values)
        self.values = values
