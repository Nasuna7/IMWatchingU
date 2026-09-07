from dataclasses import replace
from io import BytesIO

from PIL import Image, ImageOps, ImageStat


def recognition_tiles(frame, max_edge):
    """Keep tall regions legible, with overlap for text crossing tile boundaries."""
    if frame.height <= frame.width * 2:
        yield frame, 0
        return
    height = min(max_edge, max(256, frame.width * 2))
    if frame.height <= height:
        yield frame, 0
        return
    overlap = min(128, height // 4)
    top = 0
    stride = frame.width * 3
    while True:
        bottom = min(frame.height, top + height)
        yield replace(frame, height=bottom - top, rgb=frame.rgb[top * stride : bottom * stride]), top
        if bottom == frame.height:
            break
        top = bottom - overlap


def merge_tile_lines(parts):
    """Restore frame coordinates and deduplicate only spatially overlapping lines."""
    merged = []
    for lines, offset in parts:
        for line in lines:
            line = replace(line, y=line.y + offset)
            for index, previous in enumerate(merged):
                vertical = min(line.y + line.height, previous.y + previous.height) - max(line.y, previous.y)
                horizontal = min(line.x + line.width, previous.x + previous.width) - max(line.x, previous.x)
                if (
                    vertical > min(line.height, previous.height) * 0.5
                    and horizontal > min(line.width, previous.width) * 0.5
                ):
                    if len(line.text) > len(previous.text):
                        merged[index] = line
                    break
            else:
                merged.append(line)
    return tuple(sorted(merged, key=lambda line: (line.y, line.x)))


def frame_image(frame):
    return Image.frombytes("RGB", (frame.width, frame.height), frame.rgb)


def prepare(frame, max_edge=1920, preprocess=True):
    image = frame_image(frame)
    factor = min(2 if max(image.size) < 960 else 1, max_edge / max(image.size))
    if factor != 1:
        image = image.resize(
            (max(1, round(image.width * factor)), max(1, round(image.height * factor))),
            Image.Resampling.LANCZOS,
        )
    if preprocess:
        image = ImageOps.autocontrast(ImageOps.grayscale(image))
        if ImageStat.Stat(image).mean[0] < 110:
            image = ImageOps.invert(image)
    return image


def encode_png(frame):
    stream = BytesIO()
    frame_image(frame).save(stream, format="PNG")
    return stream.getvalue()
