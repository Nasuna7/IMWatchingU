from string import Formatter

VARIABLES = frozenset(("keyword", "count", "threshold", "hit_line", "ocr_text", "capture_time"))


def validate_template(template: str):
    for _, name, spec, conversion in Formatter().parse(template):
        if name is not None and (name not in VARIABLES or spec or conversion):
            raise ValueError("模板仅允许指定变量，不允许表达式、属性或格式代码")


def render(policy, rule, result, matched) -> tuple[str, bool]:
    policy.validate()
    if policy.message_type == "image":
        return "", False
    values = dict(
        keyword=rule.alias or rule.keyword,
        count=matched.count,
        threshold=rule.min_count,
        hit_line=matched.hit_line,
        ocr_text=result.text,
        capture_time=result.frame.capture_time.astimezone().strftime("%Y-%m-%d %H:%M:%S"),
    )
    if policy.body_source == "fixed":
        text = policy.body
    elif policy.body_source == "template":
        text = policy.body.format_map(values)
    else:
        text = values[policy.body_source]
    truncated = len(text) > 2000
    return (text[:1999] + "…" if truncated else text), truncated
