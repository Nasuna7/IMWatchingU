import json
import sqlite3
import threading
from contextlib import contextmanager
from dataclasses import asdict, replace
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from screen_qq_ocr.domain.matching import normalize
from screen_qq_ocr.domain.models import QQTarget, SendPolicy

from .keyword_files import policy_from_dict, rule_from_dict


class Database:
    """Connections are short-lived; a single lock serializes writes and backups."""

    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.account_id = None
        with self.connect() as db:
            version = db.execute("PRAGMA user_version").fetchone()[0]
            if version > 1:
                raise ValueError("数据库来自更新版本，已保留原文件")
            db.executescript("""
                CREATE TABLE IF NOT EXISTS keyword_rules (
                    id TEXT PRIMARY KEY, normalized TEXT NOT NULL UNIQUE, payload TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS send_policies (id INTEGER PRIMARY KEY, payload TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS account_recipients (
                    account_id TEXT NOT NULL, scope TEXT NOT NULL, payload TEXT NOT NULL,
                    PRIMARY KEY(account_id, scope));
                CREATE TABLE IF NOT EXISTS send_records (
                    id INTEGER PRIMARY KEY, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    task_id TEXT, rule_id TEXT, target TEXT, status TEXT, receipts TEXT, is_test INTEGER);
                CREATE INDEX IF NOT EXISTS record_time ON send_records(created_at);
                CREATE TABLE IF NOT EXISTS napcat_config_revisions (
                    id INTEGER PRIMARY KEY, payload TEXT NOT NULL, stage TEXT NOT NULL);
                PRAGMA user_version=1;
            """)
            db.execute(
                "INSERT OR IGNORE INTO send_policies VALUES (1, ?)", (json.dumps(asdict(SendPolicy())),)
            )
            db.execute("DELETE FROM send_records WHERE created_at < datetime('now', '-7 days')")

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        try:
            with db:
                yield db
        finally:
            db.close()

    def list_rules(self):
        with self.lock, self.connect() as db:
            rules = [
                rule_from_dict(json.loads(row[0])) for row in db.execute("SELECT payload FROM keyword_rules")
            ]
            rules = [replace(r, send_overrides=self._recipients(db, r.id, r.send_overrides)) for r in rules]
        return sorted(rules, key=lambda rule: (rule.sort_order, rule.keyword))

    def default_policy(self):
        with self.lock, self.connect() as db:
            policy = policy_from_dict(
                json.loads(db.execute("SELECT payload FROM send_policies WHERE id=1").fetchone()[0])
            )
            return self._recipients(db, "default", policy)

    def select_account(self, account_id):
        with self.lock:
            self.account_id = str(account_id)

    def _recipients(self, db, scope, policy):
        if self.account_id is None:
            return policy
        row = db.execute(
            "SELECT payload FROM account_recipients WHERE account_id=? AND scope=?",
            (self.account_id, scope),
        ).fetchone()
        if row:
            data = json.loads(row[0])
            targets = None if data is None else tuple(QQTarget(**t) for t in data)
        else:
            targets = tuple(
                t
                for t in (policy.targets or ((policy.target,) if policy.target else ()))
                if t.account_id == self.account_id
            )
            if scope != "default" and not targets:
                targets = None
        return replace(policy, target=None, targets=targets)

    def _save_recipients(self, db, scope, policy, previous):
        if self.account_id is None:
            return
        # Migrate legacy mixed-account selections before replacing the shared policy payload.
        groups = {}
        for t in previous.targets or ((previous.target,) if previous.target else ()):
            groups.setdefault(t.account_id, []).append(asdict(t))
        for account, targets in groups.items():
            db.execute(
                "INSERT OR IGNORE INTO account_recipients VALUES (?, ?, ?)",
                (account, scope, json.dumps(targets)),
            )
        targets = policy.targets or ((policy.target,) if policy.target else ())
        if any(t.account_id != self.account_id for t in targets):
            raise ValueError("发送对象不属于当前 QQ 账号，请重新选择")
        payload = (
            None
            if scope != "default" and policy.targets is None and not policy.target
            else [asdict(t) for t in targets]
        )
        db.execute(
            "INSERT OR REPLACE INTO account_recipients VALUES (?, ?, ?)",
            (self.account_id, scope, json.dumps(payload)),
        )

    def save_policy(self, policy):
        policy.validate()
        for rule in self.list_rules():
            rule.send_overrides.resolve(policy)
        with self.lock, self.connect() as db:
            previous = policy_from_dict(
                json.loads(db.execute("SELECT payload FROM send_policies WHERE id=1").fetchone()[0])
            )
            self._save_recipients(db, "default", policy, previous)
            db.execute("UPDATE send_policies SET payload=? WHERE id=1", (json.dumps(asdict(policy)),))

    @staticmethod
    def _save(db, rule):
        db.execute(
            """INSERT INTO keyword_rules VALUES (?, ?, ?)
                   ON CONFLICT(id) DO UPDATE SET normalized=excluded.normalized, payload=excluded.payload""",
            (rule.id, normalize(rule.keyword), json.dumps(asdict(rule), ensure_ascii=False)),
        )

    def save_rule(self, rule):
        rule.send_overrides.resolve(self.default_policy())
        try:
            with self.lock, self.connect() as db:
                row = db.execute("SELECT payload FROM keyword_rules WHERE id=?", (rule.id,)).fetchone()
                previous = rule_from_dict(json.loads(row[0])).send_overrides if row else rule.send_overrides
                self._save_recipients(db, rule.id, rule.send_overrides, previous)
                self._save(db, rule)
        except sqlite3.IntegrityError as error:
            raise ValueError("去除空白后相同的关键词已存在，未保存") from error

    def delete_rule(self, rule_id):
        with self.lock, self.connect() as db:
            db.execute("DELETE FROM keyword_rules WHERE id=?", (rule_id,))

    def backup(self):
        folder = self.path.parent / "backups"
        folder.mkdir(exist_ok=True)
        path = folder / f"app-{datetime.now():%Y%m%d-%H%M%S-%f}.db"
        with self.lock, self.connect() as source, sqlite3.connect(path) as destination:
            source.backup(destination)
        for stale in sorted(folder.glob("app-*.db"))[:-5]:
            stale.unlink()
        return path

    def import_rules(self, preview, mode="merge", overwrite=False, allow_invalid=False, use_default=False):
        if mode not in ("merge", "replace"):
            raise ValueError("无效导入模式")
        if preview.errors and not allow_invalid:
            raise ValueError("存在无效条目，需明确选择仅导入有效条目")
        default = preview.default_policy if use_default and preview.default_policy else self.default_policy()
        for rule in preview.rules:
            rule.send_overrides.resolve(default)
        with self.lock:
            if mode == "replace":
                self.backup()
            with self.connect() as db:
                if mode == "replace":
                    db.execute("DELETE FROM keyword_rules")
                for rule in preview.rules:
                    previous = rule.send_overrides
                    existing = db.execute(
                        "SELECT payload FROM keyword_rules WHERE normalized=?", (normalize(rule.keyword),)
                    ).fetchone()
                    if existing:
                        if not overwrite:
                            continue
                        old = rule_from_dict(json.loads(existing[0]))
                        previous = old.send_overrides
                        rule = replace(rule, id=old.id, revision=old.revision + 1)
                    elif db.execute("SELECT 1 FROM keyword_rules WHERE id=?", (rule.id,)).fetchone():
                        rule = replace(rule, id=str(uuid4()))
                    self._save_recipients(db, rule.id, self._import_recipients(rule.send_overrides), previous)
                    self._save(db, rule)
                if use_default and preview.default_policy:
                    previous = policy_from_dict(
                        json.loads(db.execute("SELECT payload FROM send_policies WHERE id=1").fetchone()[0])
                    )
                    self._save_recipients(db, "default", self._import_recipients(default), previous)
                    db.execute(
                        "UPDATE send_policies SET payload=? WHERE id=1", (json.dumps(asdict(default)),)
                    )

    def _import_recipients(self, policy):
        if self.account_id is None:
            return policy
        targets = tuple(
            t
            for t in (policy.targets or ((policy.target,) if policy.target else ()))
            if t.account_id == self.account_id
        )
        return replace(
            policy, target=None, targets=targets or (() if isinstance(policy, SendPolicy) else None)
        )

    def record(self, task, status, receipts):
        with self.lock, self.connect() as db:
            db.execute(
                "INSERT INTO send_records(task_id,rule_id,target,status,receipts,is_test) VALUES(?,?,?,?,?,?)",
                (
                    task.task_id,
                    task.rule_id,
                    json.dumps([asdict(target) for target in task.policy.recipients], ensure_ascii=False),
                    status,
                    json.dumps([asdict(r) for r in receipts]),
                    task.is_test,
                ),
            )

    def records(self):
        with self.lock, self.connect() as db:
            return db.execute(
                "SELECT created_at,task_id,status,target,receipts,is_test FROM send_records ORDER BY id DESC LIMIT 1000"
            ).fetchall()
