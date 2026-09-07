import hashlib
from pathlib import Path

import pytest

from screen_qq_ocr.domain.models import KeywordRule, SendOverrides, SendPolicy
from screen_qq_ocr.infrastructure.persistence.database import Database
from screen_qq_ocr.infrastructure.persistence.keyword_files import (
    export_json,
    export_txt,
    parse_json,
    parse_txt,
)


def test_legacy_eleven_and_immutable_source(tmp_path):
    path = Path(__file__).parents[2] / "legacy/keywords.txt"
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    preview = parse_txt(path.read_text(encoding="utf-8-sig"))
    assert not preview.errors and len(preview.rules) == 11
    db = Database(tmp_path / "app.db")
    db.import_rules(preview)
    restored = Database(tmp_path / "app.db").list_rules()
    assert restored == preview.rules
    assert hashlib.sha256(path.read_bytes()).hexdigest() == before


def test_import_diagnostics_bom_and_pipe():
    preview = parse_txt("\ufeff甲|2|消息|完整\r\n甲 |1|重复\n乙|9999|错误\n|2|空词\n丙|NaN|错误\n丁")
    assert len(preview.rules) == 2
    assert len(preview.duplicates) == 1
    assert len(preview.errors) == 3
    assert preview.rules[0].send_overrides.body == "消息|完整"
    assert preview.rules[1].min_count == 1


def test_unique_normalized_keywords_and_replace_backup(tmp_path):
    db = Database(tmp_path / "app.db")
    rule = KeywordRule("C erb")
    db.save_rule(rule)
    with pytest.raises(ValueError):
        db.save_rule(KeywordRule("Ce\nrb"))
    assert db.list_rules() == [rule]
    db.import_rules(parse_txt("new"), mode="replace")
    backups = list((tmp_path / "backups").glob("*.db"))
    assert len(backups) == 1
    assert Database(backups[0]).list_rules() == [rule]


def test_json_round_trip_and_txt_loss(tmp_path, target):
    policy = SendPolicy(target=target)
    rules = [
        KeywordRule(
            "hello", send_overrides=SendOverrides(cooldown=0, body_source="fixed", body="{literal}\nline")
        )
    ]
    restored = parse_json(export_json(rules, policy))
    assert restored.rules == rules and restored.default_policy == policy
    with pytest.raises(ValueError):
        export_txt(rules)
    db = Database(tmp_path / "app.db")
    db.import_rules(restored)
    assert db.default_policy().target is None


def test_invalid_requires_explicit_choice(tmp_path):
    db = Database(tmp_path / "app.db")
    preview = parse_txt("good\nbad|0|")
    with pytest.raises(ValueError):
        db.import_rules(preview)
    assert db.list_rules() == []
    db.import_rules(preview, allow_invalid=True)
    assert len(db.list_rules()) == 1
