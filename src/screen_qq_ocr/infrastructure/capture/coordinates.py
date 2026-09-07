def normalize_roi(x1, y1, x2, y2, width, height):
    left, right = sorted((min(width, max(0, x1)), min(width, max(0, x2))))
    top, bottom = sorted((min(height, max(0, y1)), min(height, max(0, y2))))
    if right - left < 16 or bottom - top < 16:
        raise ValueError("识别区域至少为 16×16 物理像素")
    return left / width, top / height, (right - left) / width, (bottom - top) / height


def pixel_box(roi, width, height):
    x, y, w, h = roi
    if w <= 0 or h <= 0 or x < 0 or y < 0 or x + w > 1.000001 or y + h > 1.000001:
        raise ValueError("区域坐标越界，请重新选择")
    left, top = round(x * width), round(y * height)
    right, bottom = min(width, round((x + w) * width)), min(height, round((y + h) * height))
    if right - left < 16 or bottom - top < 16:
        raise ValueError("识别区域至少为 16×16 物理像素")
    return left, top, right, bottom
