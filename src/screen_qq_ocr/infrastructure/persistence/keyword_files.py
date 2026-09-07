import json
from dataclasses import asdict, dataclass, field

from screen_qq_ocr.domain.matching import normalize
from screen_qq_ocr.domain.models import KeywordRule, QQTarget, SendOverrides, SendPolicy


def _target_from_dict(value):
    return value if isinstance(value, QQTarget) else QQTarget(**value)


def _targets_from_dict(value):
    return tuple(_target_from_dict(item) for item in (value or ()))


def policy_from_dict(data):
    data = dict(data)
    if data.get("target"):
        data["target"] = _target_from_dict(data["target"])
    if "targets" in data:
        data["targets"] = _targets_from_dict(data["targets"])
    elif data.get("target"):
        data["targets"] = (data["target"],)
    result = SendPolicy(**data)
    result.validate()
    return result


def rule_from_dict(data):
    data = dict(data)
    overrides = dict(data.pop("send_overrides", {}) or {})
    if overrides.get("target"):
        overrides["target"] = _target_from_dict(overrides["target"])
    if overrides.get("targets") is not None:
        overrides["targets"] = _targets_from_dict(overrides["targets"])
    elif overrides.get("target"):
        overrides["targets"] = (overrides["target"],)
    data["send_overrides"] = SendOverrides(**overrides)
    rule = KeywordRule(**data)
    return rule


@dataclass
class ImportPreview:
    rules: list = field(default_factory=list)
    errors: list = field(default_factory=list)
    duplicates: list = field(default_factory=list)
    default_policy: SendPolicy | None = None


def parse_txt(text):
    preview = ImportPreview()
    seen = set()
    for number, line in enumerate(text.lstrip("\ufeff").splitlines(), 1):
        if not line.strip():
            continue
        try:
            fields = line.split("|", 2)
            keyword = fields[0].strip()
            count = int(fields[1]) if len(fields) > 1 else 1
            body = fields[2] if len(fields) > 2 else ""
            if len(body) > 2000:
                raise ValueError("消息超过 2000 字符")
            overrides = SendOverrides(body_source="fixed", body=body) if body else SendOverrides()
            rule = KeywordRule(keyword, count, sort_order=len(preview.rules), send_overrides=overrides)
            normalized = normalize(rule.keyword)
            if normalized in seen:
                preview.duplicates.append(f"第 {number} 行：重复关键词 {keyword}")
            else:
                seen.add(normalized)
                preview.rules.append(rule)
        except (ValueError, TypeError) as error:
            preview.errors.append(f"第 {number} 行：{error}")
    return preview


def parse_json(text):
    data = json.loads(text.lstrip("\ufeff"))
    if data.get("schema_version") != 1:
        raise ValueError("不支持的规则 JSON 版本")
    preview = ImportPreview(default_policy=policy_from_dict(data["default_policy"]))
    seen = set()
    for index, item in enumerate(data["rules"], 1):
        try:
            rule = rule_from_dict(item)
            rule.send_overrides.resolve(preview.default_policy)
            key = normalize(rule.keyword)
            if key in seen:
                preview.duplicates.append(f"第 {index} 项：重复关键词 {rule.keyword}")
            else:
                seen.add(key)
                preview.rules.append(rule)
        except (KeyError, ValueError, TypeError) as error:
            preview.errors.append(f"第 {index} 项：{error}")
    return preview


def export_json(rules, default):
    return json.dumps(
        dict(schema_version=1, default_policy=asdict(default), rules=[asdict(rule) for rule in rules]),
        ensure_ascii=False,
        indent=2,
    )


def export_txt(rules):
    lines = []
    for rule in rules:
        body = rule.send_overrides.body if rule.send_overrides.body_source == "fixed" else ""
        body = body or ""
        if any(c in rule.keyword for c in "|\r\n") or any(c in body for c in "\r\n"):
            raise ValueError("关键词含分隔符或消息含换行，请使用 JSON 完整导出")
        lines.append(f"{rule.keyword}|{rule.min_count}|{body}")
    return "\n".join(lines)
