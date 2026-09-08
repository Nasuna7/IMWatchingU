from dataclasses import replace

import pytest

from screen_qq_ocr.domain.models import KeywordRule, SendOverrides, SendPolicy
from screen_qq_ocr.infrastructure.persistence.database import Database


def test_accounts_restore_default_and_rule_recipients_after_restart(tmp_path, target):
    path = tmp_path / "accounts.db"
    db = Database(path)
    other = replace(target, account_id="654321")
    rule = KeywordRule("test", send_overrides=SendOverrides(targets=(target, other)))
    db.save_rule(rule)
    db.save_policy(SendPolicy(targets=(target, other)))
    db.select_account(target.account_id)
    assert db.default_policy().recipients == (target,)
    assert db.list_rules()[0].send_overrides.resolve(db.default_policy()).recipients == (target,)
    db.save_policy(replace(db.default_policy(), targets=()))
    db.save_rule(replace(db.list_rules()[0], send_overrides=SendOverrides()))
    db.select_account(other.account_id)
    assert db.default_policy().recipients == (other,)
    assert db.list_rules()[0].send_overrides.targets == (other,)
    db.save_policy(replace(db.default_policy(), cooldown=42))
    db.save_rule(replace(db.list_rules()[0], min_count=2))
    reopened = Database(path)
    reopened.select_account(target.account_id)
    assert reopened.default_policy().recipients == ()
    assert reopened.list_rules()[0].send_overrides.targets is None
    reopened.select_account(other.account_id)
    assert reopened.default_policy().recipients == (other,)
    assert reopened.list_rules()[0].send_overrides.targets == (other,)
    reopened.select_account("")
    assert not reopened.default_policy().recipients


def test_account_cannot_save_foreign_recipients(tmp_path, target):
    db = Database(tmp_path / "accounts.db")
    db.select_account("654321")
    with pytest.raises(ValueError, match="当前 QQ"):
        db.save_policy(SendPolicy(target=target))
