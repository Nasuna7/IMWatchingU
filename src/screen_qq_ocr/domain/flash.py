import colorsys


def classify(r, g, b):
    maximum = max(r, g, b)
    if maximum < 60:
        return "无"
    hue, saturation, _ = colorsys.rgb_to_hsv(r / 255, g / 255, b / 255)
    if min(r, g, b) > 205 and saturation < 0.3:
        return "白"
    if saturation < 0.25:
        return "无"
    hue *= 360
    if hue < 18 or hue >= 342:
        return "红"
    return "橙" if hue < 55 else "无"


def dominant(pixels):
    counts = dict.fromkeys(("红", "橙", "白"), 0)
    for pixel in pixels:
        name = classify(*pixel[:3])
        if name in counts:
            counts[name] += 1
    return max(counts, key=counts.get) if any(counts.values()) else "无"


class FlashDetector:
    def __init__(self, cooldown=30):
        self.cooldown = cooldown
        self.last_alarm = float("-inf")
        self.reset()

    def reset(self):
        self.previous = None
        self.last_time = None
        self.changes = 0

    def sample(self, color, now):
        if color is None:
            self.reset()
            return False
        if self.last_time is None or not 0 < now - self.last_time <= 0.5:
            self.changes = 0
        elif color != self.previous:
            self.changes += 1
        else:
            self.changes = 0
        self.previous, self.last_time = color, now
        alarm = self.changes >= 4 and now - self.last_alarm >= self.cooldown
        if alarm:
            self.last_alarm = now
        return alarm
