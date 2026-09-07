import math
import struct
import wave
from pathlib import Path

from PySide6.QtCore import QObject, QTimer


class Audio(QObject):
    def __init__(self, cache):
        super().__init__()
        self.cache = Path(cache)
        self.cache.mkdir(parents=True, exist_ok=True)
        self.effect = None
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.stop)

    def load(self):
        if self.effect is None:
            from PySide6.QtMultimedia import QSoundEffect

            self.effect = QSoundEffect(self)
        return self.effect

    def play(self, name):
        if name == "静音":
            return
        effect = self.load()
        if effect.isPlaying():
            return
        path = self.cache / f"tone-{['急促警报', '双短鸣', '长鸣', '柔和提示'].index(name)}.wav"
        if not path.exists():
            rate = 16000
            frequency = 440 if name == "柔和提示" else 880
            values = []
            for i in range(rate * 3):
                phase = (i / rate) % 1
                on = name == "长鸣" or (phase < 0.15 or 0.3 < phase < 0.45)
                if name == "急促警报":
                    on = (i / rate) % 0.2 < 0.1
                sample = int(6000 * math.sin(2 * math.pi * frequency * i / rate)) if on else 0
                values.append(struct.pack("<h", sample))
            with wave.open(str(path), "wb") as stream:
                stream.setparams((1, 2, rate, 0, "NONE", "not compressed"))
                stream.writeframes(b"".join(values))
        from PySide6.QtCore import QUrl

        effect.setSource(QUrl.fromLocalFile(str(path)))
        effect.setVolume(0.3)
        effect.play()
        self.timer.start(3000)

    def stop(self):
        self.timer.stop()
        if self.effect is not None:
            self.effect.stop()
