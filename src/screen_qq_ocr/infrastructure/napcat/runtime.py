import hashlib
import shutil
import stat
import tempfile
import zipfile
from pathlib import Path, PurePosixPath


def safe_member(name):
    normalized = name.replace("\\", "/")
    path = PurePosixPath(normalized)
    if path.is_absolute() or ".." in path.parts or ":" in normalized:
        raise ValueError("发行包包含非法路径")
    if any(
        part.rstrip(" .").upper().split(".")[0]
        in {
            "CON",
            "PRN",
            "AUX",
            "NUL",
            *[f"COM{i}" for i in range(1, 10)],
            *[f"LPT{i}" for i in range(1, 10)],
        }
        for part in path.parts
    ):
        raise ValueError("发行包包含 Windows 保留路径")
    return path


class RuntimeCatalog:
    """Only independently verified catalog entries may become runnable installations."""

    def __init__(self, manifest):
        self.manifest = manifest

    def prepare(self, archive, destination):
        archive, destination = Path(archive), Path(destination).resolve()
        with archive.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        entry = next(
            (item for item in self.manifest.get("verified_packages", []) if item["sha256"] == digest), None
        )
        if entry is None:
            raise ValueError("该包未列入已验证发行清单，未执行或安装；需完成版本和文件摘要验收")
        if not entry["source"].startswith("https://github.com/NapNeko/NapCatQQ/releases/"):
            raise ValueError("运行时来源未验证")
        version = entry["version"]
        if not version or safe_member(version).parts != (version,):
            raise ValueError("运行时版本路径无效")
        destination.mkdir(parents=True, exist_ok=True)
        target = destination / version
        if target.exists():
            raise ValueError("该版本已经存在，不覆盖现有运行时")
        with zipfile.ZipFile(archive) as bundle:
            total = 0
            for info in bundle.infolist():
                safe_member(info.filename)
                if stat.S_ISLNK(info.external_attr >> 16):
                    raise ValueError("发行包包含符号链接")
                total += info.file_size
                if total > 4 * 1024**3:
                    raise ValueError("发行包展开体积超过上限")
            with tempfile.TemporaryDirectory(dir=destination) as temporary:
                bundle.extractall(temporary)
                for name, expected in entry["files"].items():
                    file = Path(temporary).joinpath(*safe_member(name).parts)
                    with file.open("rb") as stream:
                        actual = hashlib.file_digest(stream, "sha256").hexdigest()
                    if actual != expected:
                        raise ValueError("运行时文件摘要不匹配")
                shutil.copytree(temporary, target)
        return target
