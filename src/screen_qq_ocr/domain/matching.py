from dataclasses import dataclass


def normalize(text: str) -> str:
    return "".join(text.split())


@dataclass(frozen=True)
class Match:
    count: int
    hit: bool
    hit_line: str
    line_indices: tuple[int, ...] = ()


def match(text: str, keyword: str, threshold: int = 1, lines=()) -> Match:
    needle = normalize(keyword)
    if not needle:
        raise ValueError("关键词不能为空")
    count = normalize(text).count(needle)
    text_lines = tuple(line.text if hasattr(line, "text") else str(line) for line in lines) or tuple(
        text.splitlines()
    )
    line_indices = tuple(index for index, line in enumerate(text_lines) if needle in normalize(line))
    line = text_lines[line_indices[0]] if line_indices else ""
    return Match(count, count >= threshold, line or text, line_indices)
