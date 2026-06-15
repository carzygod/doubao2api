from __future__ import annotations

import asyncio
import json
import os
import re
import sqlite3
import threading
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, Optional

from .browser_client import BrowserClient, DEFAULT_SESSION_FILE


ACCOUNT_STATUSES = {
    "new",
    "starting",
    "ready",
    "not_logged_in",
    "captcha_required",
    "error",
    "stopped",
    "disabled",
}


def account_data_root() -> str:
    explicit = os.environ.get("DOUBAO_ACCOUNT_DATA_DIR") or os.environ.get("DOUBAO_DATA_DIR")
    if explicit:
        return explicit

    session_file = os.environ.get("DOUBAO_SESSION_FILE")
    if session_file:
        return os.path.dirname(session_file)

    browser_data = os.environ.get("DOUBAO_BROWSER_DATA")
    if browser_data:
        return os.path.dirname(browser_data)

    return "/app/data" if os.path.isdir("/app") else os.path.join(os.getcwd(), "data")


def account_db_path() -> str:
    explicit = os.environ.get("DOUBAO_ACCOUNT_DB")
    if explicit:
        return explicit
    return os.path.join(account_data_root(), "doubao_accounts.sqlite3")


def _now() -> int:
    return int(time.time())


def _safe_id(value: str) -> str:
    value = value.strip().lower()
    value = re.sub(r"[^a-z0-9_-]+", "-", value)
    value = value.strip("-_")
    return value or f"acct-{uuid.uuid4().hex[:10]}"


class DoubaoAccountStore:
    def __init__(self, path: Optional[str] = None):
        self.path = path or account_db_path()
        self._lock = threading.RLock()
        parent = os.path.dirname(self.path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        self._init_db()
        self.ensure_default_account()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=30)
        conn.row_factory = sqlite3.Row
        return conn

    @contextmanager
    def _connection(self):
        conn = self._connect()
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def _init_db(self) -> None:
        with self._lock, self._connection() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS doubao_accounts (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    status TEXT NOT NULL DEFAULT 'new',
                    session_file TEXT NOT NULL,
                    user_data_dir TEXT NOT NULL,
                    proxy_url TEXT NOT NULL DEFAULT '',
                    tags_json TEXT NOT NULL DEFAULT '[]',
                    models_json TEXT NOT NULL DEFAULT '[]',
                    quota_json TEXT NOT NULL DEFAULT '{}',
                    last_used_at INTEGER,
                    last_validated_at INTEGER,
                    last_error TEXT NOT NULL DEFAULT '',
                    created_at INTEGER NOT NULL,
                    updated_at INTEGER NOT NULL
                )
                """
            )
            for column, ddl in {
                "proxy_url": "ALTER TABLE doubao_accounts ADD COLUMN proxy_url TEXT NOT NULL DEFAULT ''",
                "tags_json": "ALTER TABLE doubao_accounts ADD COLUMN tags_json TEXT NOT NULL DEFAULT '[]'",
                "models_json": "ALTER TABLE doubao_accounts ADD COLUMN models_json TEXT NOT NULL DEFAULT '[]'",
                "quota_json": "ALTER TABLE doubao_accounts ADD COLUMN quota_json TEXT NOT NULL DEFAULT '{}'",
                "last_used_at": "ALTER TABLE doubao_accounts ADD COLUMN last_used_at INTEGER",
                "last_validated_at": "ALTER TABLE doubao_accounts ADD COLUMN last_validated_at INTEGER",
                "last_error": "ALTER TABLE doubao_accounts ADD COLUMN last_error TEXT NOT NULL DEFAULT ''",
            }.items():
                cols = {row["name"] for row in conn.execute("PRAGMA table_info(doubao_accounts)").fetchall()}
                if column not in cols:
                    conn.execute(ddl)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_doubao_accounts_enabled ON doubao_accounts(enabled)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_doubao_accounts_status ON doubao_accounts(status)")

    def ensure_default_account(self) -> Dict[str, Any]:
        existing = self.get("default")
        if existing:
            return existing

        root = account_data_root()
        session_file = os.environ.get("DOUBAO_SESSION_FILE") or DEFAULT_SESSION_FILE
        user_data_dir = os.environ.get(
            "DOUBAO_BROWSER_DATA",
            os.path.join(os.path.expanduser("~"), ".doubao_browser"),
        )
        now = _now()
        with self._lock, self._connection() as conn:
            conn.execute(
                """
                INSERT INTO doubao_accounts (
                    id, name, enabled, status, session_file, user_data_dir,
                    models_json, created_at, updated_at
                ) VALUES (?, ?, 1, 'new', ?, ?, ?, ?, ?)
                """,
                (
                    "default",
                    "默认豆包账号",
                    session_file or os.path.join(root, ".doubao_session.json"),
                    user_data_dir,
                    json.dumps(["chat", "image", "video", "audio"], ensure_ascii=False),
                    now,
                    now,
                ),
            )
        return self.get("default") or {}

    def create_account(self, name: str = "", account_id: str = "") -> Dict[str, Any]:
        root = account_data_root()
        raw_id = account_id or name or f"acct-{uuid.uuid4().hex[:10]}"
        account_id = _safe_id(raw_id)
        if account_id == "default" or self.get(account_id):
            account_id = f"{account_id}-{uuid.uuid4().hex[:6]}"
        if not name:
            name = f"豆包账号 {account_id[-6:]}"

        base = os.path.join(root, "accounts", account_id)
        session_file = os.path.join(base, "session.json")
        user_data_dir = os.path.join(base, "profile")
        now = _now()
        with self._lock, self._connection() as conn:
            conn.execute(
                """
                INSERT INTO doubao_accounts (
                    id, name, enabled, status, session_file, user_data_dir,
                    models_json, created_at, updated_at
                ) VALUES (?, ?, 1, 'new', ?, ?, ?, ?, ?)
                """,
                (
                    account_id,
                    name,
                    session_file,
                    user_data_dir,
                    json.dumps(["chat", "image", "video", "audio"], ensure_ascii=False),
                    now,
                    now,
                ),
            )
        return self.get(account_id) or {}

    def list_accounts(self) -> list[Dict[str, Any]]:
        with self._lock, self._connection() as conn:
            rows = conn.execute(
                "SELECT * FROM doubao_accounts ORDER BY created_at ASC, id ASC"
            ).fetchall()
        return [self._row_to_dict(row) for row in rows]

    def get(self, account_id: str) -> Optional[Dict[str, Any]]:
        with self._lock, self._connection() as conn:
            row = conn.execute(
                "SELECT * FROM doubao_accounts WHERE id = ?",
                (account_id,),
            ).fetchone()
        return self._row_to_dict(row) if row else None

    def update_account(self, account_id: str, **fields: Any) -> Optional[Dict[str, Any]]:
        allowed = {
            "name",
            "enabled",
            "status",
            "session_file",
            "user_data_dir",
            "proxy_url",
            "tags_json",
            "models_json",
            "quota_json",
            "last_used_at",
            "last_validated_at",
            "last_error",
        }
        assignments: list[str] = []
        values: list[Any] = []
        for key, value in fields.items():
            if key not in allowed:
                continue
            if key == "status" and value not in ACCOUNT_STATUSES:
                continue
            if key == "enabled":
                value = 1 if value else 0
            assignments.append(f"{key} = ?")
            values.append(value)
        if not assignments:
            return self.get(account_id)
        assignments.append("updated_at = ?")
        values.append(_now())
        values.append(account_id)
        with self._lock, self._connection() as conn:
            conn.execute(
                f"UPDATE doubao_accounts SET {', '.join(assignments)} WHERE id = ?",
                values,
            )
        return self.get(account_id)

    def mark_success(self, account_id: str) -> None:
        self.update_account(
            account_id,
            status="ready",
            last_error="",
            last_used_at=_now(),
            last_validated_at=_now(),
        )

    def mark_failure(self, account_id: str, message: str, status: str = "error") -> None:
        self.update_account(
            account_id,
            status=status if status in ACCOUNT_STATUSES else "error",
            last_error=message[:500],
            last_validated_at=_now(),
        )

    def delete_account(self, account_id: str) -> bool:
        with self._lock, self._connection() as conn:
            cur = conn.execute("DELETE FROM doubao_accounts WHERE id = ?", (account_id,))
            return cur.rowcount > 0

    def _row_to_dict(self, row: sqlite3.Row) -> Dict[str, Any]:
        data = dict(row)
        data["enabled"] = bool(data.get("enabled"))
        for key in ("tags_json", "models_json", "quota_json"):
            raw = data.get(key)
            try:
                parsed = json.loads(raw) if raw else ([] if key != "quota_json" else {})
            except json.JSONDecodeError:
                parsed = [] if key != "quota_json" else {}
            data[key.replace("_json", "")] = parsed
        return data


class DoubaoAccountManager:
    def __init__(
        self,
        *,
        headless: bool = True,
        max_hot_accounts: Optional[int] = None,
        idle_ttl_seconds: int = 600,
    ):
        self.store = DoubaoAccountStore()
        self.headless = headless
        self.max_hot_accounts = max_hot_accounts or int(os.environ.get("DOUBAO_MAX_HOT_ACCOUNTS", "2"))
        self.idle_ttl_seconds = idle_ttl_seconds
        self.clients: Dict[str, BrowserClient] = {}
        self.last_touch: Dict[str, float] = {}
        self._locks: Dict[str, asyncio.Lock] = {}
        self.default_account_id = os.environ.get("DOUBAO_DEFAULT_ACCOUNT_ID", "default")

    def _lock_for(self, account_id: str) -> asyncio.Lock:
        if account_id not in self._locks:
            self._locks[account_id] = asyncio.Lock()
        return self._locks[account_id]

    async def start(self) -> None:
        self.store.ensure_default_account()
        if os.environ.get("DOUBAO_AUTOSTART_DEFAULT_ACCOUNT", "true").lower() != "false":
            try:
                await self.ensure_client(self.default_account_id)
            except Exception:
                # Startup should not fail just because the web session needs login.
                pass

    async def stop_all(self) -> None:
        for account_id in list(self.clients):
            await self.stop_client(account_id, update_status=False)

    async def ensure_client(self, account_id: str) -> tuple[Dict[str, Any], BrowserClient]:
        account = self.store.get(account_id)
        if not account:
            raise KeyError(f"Account not found: {account_id}")
        if not account.get("enabled"):
            raise RuntimeError(f"Account disabled: {account_id}")

        async with self._lock_for(account_id):
            client = self.clients.get(account_id)
            if client and client.page and client._context:
                self.last_touch[account_id] = time.time()
                return account, client

            self.store.update_account(account_id, status="starting", last_error="")
            cookie_header = os.environ.get("DOUBAO_COOKIE", "") if account_id == "default" else ""
            client = BrowserClient(
                headless=self.headless,
                user_data_dir=account["user_data_dir"],
                session_file=account["session_file"],
                cookie_header=cookie_header,
            )
            try:
                await client.start()
            except Exception as exc:
                self.store.mark_failure(account_id, str(exc), "error")
                try:
                    await client.stop()
                except Exception:
                    pass
                raise

            self.clients[account_id] = client
            self.last_touch[account_id] = time.time()
            self.store.update_account(
                account_id,
                status="ready" if client.is_ready else "not_logged_in",
                last_error="" if client.is_ready else "未登录",
                last_validated_at=_now(),
            )
            await self.prune_idle(exclude={account_id})
            return self.store.get(account_id) or account, client

    async def get_ready_client(self, preferred_account_id: Optional[str] = None) -> tuple[Dict[str, Any], BrowserClient]:
        if preferred_account_id:
            account, client = await self.ensure_client(preferred_account_id)
            self._ensure_ready(account, client)
            self.last_touch[account["id"]] = time.time()
            return account, client

        accounts = [a for a in self.store.list_accounts() if a.get("enabled")]
        if not accounts:
            raise RuntimeError("No enabled Doubao accounts")

        hot_ready = []
        for account in accounts:
            client = self.clients.get(account["id"])
            if client and client.is_ready and not client.needs_captcha:
                hot_ready.append(account)
        if hot_ready:
            hot_ready.sort(key=lambda a: a.get("last_used_at") or 0)
            account = hot_ready[0]
            client = self.clients[account["id"]]
            self.last_touch[account["id"]] = time.time()
            return account, client

        last_error = ""
        for account in sorted(accounts, key=lambda a: a.get("last_used_at") or 0):
            try:
                account, client = await self.ensure_client(account["id"])
                self._ensure_ready(account, client)
                self.last_touch[account["id"]] = time.time()
                return account, client
            except Exception as exc:
                last_error = str(exc)
                continue
        raise RuntimeError(last_error or "No ready Doubao accounts")

    def _ensure_ready(self, account: Dict[str, Any], client: BrowserClient) -> None:
        if not client.is_ready:
            raise RuntimeError(f"Account {account['id']} is not logged in")
        if client.needs_captcha:
            self.store.update_account(account["id"], status="captcha_required", last_error="Captcha required")
            raise RuntimeError(f"Account {account['id']} requires captcha")

    async def stop_client(self, account_id: str, *, update_status: bool = True) -> None:
        async with self._lock_for(account_id):
            client = self.clients.pop(account_id, None)
            self.last_touch.pop(account_id, None)
            if client:
                await client.stop()
            if update_status and self.store.get(account_id):
                self.store.update_account(account_id, status="stopped")

    async def restart_client(self, account_id: str) -> tuple[Dict[str, Any], BrowserClient]:
        await self.stop_client(account_id, update_status=False)
        return await self.ensure_client(account_id)

    async def prune_idle(self, exclude: Optional[set[str]] = None) -> None:
        exclude = exclude or set()
        if self.max_hot_accounts <= 0:
            return
        hot_ids = list(self.clients)
        if len(hot_ids) <= self.max_hot_accounts:
            return
        candidates = [aid for aid in hot_ids if aid not in exclude]
        candidates.sort(key=lambda aid: self.last_touch.get(aid, 0))
        while len(self.clients) > self.max_hot_accounts and candidates:
            await self.stop_client(candidates.pop(0))

    def list_accounts(self) -> list[Dict[str, Any]]:
        rows = []
        for account in self.store.list_accounts():
            client = self.clients.get(account["id"])
            runtime = {
                "hot": bool(client),
                "ready": bool(client and client.is_ready),
                "needs_captcha": bool(client and client.needs_captcha),
                "consecutive_failures": client.consecutive_failures if client else 0,
                "last_error_code": client.last_error_code if client else 0,
                "page_url": client.page.url if client and client.page else "",
            }
            account["runtime"] = runtime
            rows.append(account)
        return rows

    def counts(self) -> Dict[str, int]:
        counts: Dict[str, int] = {}
        for account in self.list_accounts():
            status = account.get("status") or "unknown"
            counts[status] = counts.get(status, 0) + 1
        return counts

    def mark_success(self, account_id: str) -> None:
        client = self.clients.get(account_id)
        if client:
            client.record_success()
        self.store.mark_success(account_id)

    def mark_failure(self, account_id: str, message: str, error_code: int = 0) -> None:
        client = self.clients.get(account_id)
        status = "error"
        if client:
            client.record_failure(error_code)
            if client.needs_captcha:
                status = "captcha_required"
        self.store.mark_failure(account_id, message, status)

    def pick_account_id_from_request(self, headers: Dict[str, str], body: Optional[Dict[str, Any]] = None) -> Optional[str]:
        body = body or {}
        for key in ("account_id", "doubao_account_id", "account"):
            value = body.get(key)
            if value:
                return str(value)
        for key in ("x-doubao-account-id", "x-account-id"):
            value = headers.get(key) or headers.get(key.title())
            if value:
                return str(value)
        return None

    async def cookies(self, account_id: str) -> list[Dict[str, Any]]:
        _, client = await self.ensure_client(account_id)
        if client._context is None:
            return []
        cookies = await client._context.cookies("https://www.doubao.com")
        return [{"name": c["name"], "value": c["value"], "length": len(c["value"])} for c in cookies]

    async def login_status(self, account_id: str) -> Dict[str, Any]:
        account, client = await self.ensure_client(account_id)
        page_url = client.page.url if client.page else ""
        login_btn_count = 0
        if client.page:
            try:
                login_btn_count = await client.page.locator('button:has-text("登录")').count()
            except Exception:
                pass
        actual_logged_in = client.is_ready and login_btn_count == 0
        status = "ready" if actual_logged_in else "not_logged_in"
        self.store.update_account(account_id, status=status, last_error="" if actual_logged_in else "未登录")
        return {
            "account_id": account_id,
            "account_name": account.get("name", account_id),
            "logged_in": actual_logged_in,
            "is_ready_flag": client.is_ready,
            "login_button_visible": login_btn_count > 0,
            "page_url": page_url,
            "device_id": client._device_id or "",
            "web_id": client._web_id or "",
            "needs_captcha": client.needs_captcha,
            "consecutive_failures": client.consecutive_failures,
            "last_error_code": client.last_error_code,
        }

    def export_public_account(self, account: Dict[str, Any]) -> Dict[str, Any]:
        data = dict(account)
        return data

