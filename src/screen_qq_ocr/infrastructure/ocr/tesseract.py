import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

from screen_qq_ocr.domain.models import OcrLine, OcrResult

from .preprocessing import merge_tile_lines, prepare, recognition_tiles


class Tesseract:
    def __init__(self, executable="", max_edge=1920, preprocess=True):
        self.executable = executable or shutil.which("tesseract") or ""
        self.max_edge, self.preprocess = max_edge, preprocess

    def recognize(self, frame):
        started = time.monotonic()
        parts = []
        results = []
        for tile, offset in recognition_tiles(frame, self.max_edge):
            result = self._recognize_tile(tile)
            results.append(result)
            parts.append((result.lines, offset))
        if len(results) == 1:
            return results[0]
        lines = merge_tile_lines(parts)
        return OcrResult(
            frame,
            "Tesseract",
            "\n".join(line.text for line in lines),
            (time.monotonic() - started) * 1000,
            lines,
        )

    def _recognize_tile(self, frame):
        if not self.executable or not Path(self.executable).is_file():
            raise ValueError("未找到 Tesseract，请在设置中选择含中文模型的本地引擎")
        started = time.monotonic()
        with tempfile.TemporaryDirectory(prefix="screen-qq-ocr-") as directory:
            source = Path(directory) / "input.png"
            image = prepare(frame, self.max_edge, self.preprocess)
            image.save(source)
            result = subprocess.run(
                [self.executable, str(source), "stdout", "-l", "chi_sim+eng", "tsv"],
                capture_output=True,
                timeout=20,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
            if result.returncode:
                raise ValueError("Tesseract 识别失败，请检查 chi_sim/eng 语言模型及引擎路径")
            text, lines = self.parse_tsv(result.stdout.decode("utf-8"), frame, image.size)
        return OcrResult(frame, "Tesseract", text, (time.monotonic() - started) * 1000, lines)

    @staticmethod
    def parse_tsv(data, frame, image_size):
        import csv
        from io import StringIO

        scale_x = frame.width / image_size[0]
        scale_y = frame.height / image_size[1]
        groups = {}
        order = []
        for row in csv.DictReader(StringIO(data), delimiter="\t"):
            text = (row.get("text") or "").strip()
            if not text:
                continue
            key = tuple(row.get(name, "") for name in ("page_num", "block_num", "par_num", "line_num"))
            if key not in groups:
                groups[key] = {"words": [], "left": [], "top": [], "right": [], "bottom": []}
                order.append(key)
            try:
                left = float(row["left"])
                top = float(row["top"])
                width = float(row["width"])
                height = float(row["height"])
            except (KeyError, ValueError):
                continue
            groups[key]["words"].append(text)
            groups[key]["left"].append(left)
            groups[key]["top"].append(top)
            groups[key]["right"].append(left + width)
            groups[key]["bottom"].append(top + height)
        lines = []
        texts = []
        for key in order:
            group = groups[key]
            if not group["words"]:
                continue
            left = min(group["left"])
            top = min(group["top"])
            right = max(group["right"])
            bottom = max(group["bottom"])
            text = " ".join(group["words"])
            texts.append(text)
            lines.append(
                OcrLine(
                    text,
                    left * scale_x,
                    top * scale_y,
                    (right - left) * scale_x,
                    (bottom - top) * scale_y,
                )
            )
        return "\n".join(texts), tuple(lines)
