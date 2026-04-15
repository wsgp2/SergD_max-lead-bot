"""Хранилище контактов: SQLite + экспорт CSV."""
from __future__ import annotations

import contextlib
import csv
import io
from datetime import datetime, timezone
from pathlib import Path
from typing import AsyncIterator, Optional

import aiosqlite

from config import DB_PATH


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(tzinfo=None).isoformat(timespec="seconds")


def _sheet_safe(val) -> str:
    """Экранирование CSV-инъекций: ячейки, начинающиеся с =,+,-,@,таб,CR
    исполняются в Excel/LibreOffice. Префиксуем апострофом."""
    s = "" if val is None else str(val)
    if s and s[0] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + s
    return s


@contextlib.asynccontextmanager
async def _db() -> AsyncIterator[aiosqlite.Connection]:
    """Соединение с PRAGMA — WAL и busy_timeout для устойчивости под нагрузкой."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("PRAGMA journal_mode=WAL")
        await db.execute("PRAGMA busy_timeout=5000")
        await db.execute("PRAGMA synchronous=NORMAL")
        yield db


_SCHEMA = """
CREATE TABLE IF NOT EXISTS contacts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    chat_id INTEGER,
    branch TEXT NOT NULL,
    name TEXT,
    city TEXT,
    school TEXT,
    phone TEXT,
    username TEXT,
    created_at TEXT NOT NULL,
    UNIQUE(user_id, branch)
);

CREATE TABLE IF NOT EXISTS admins (
    user_id INTEGER PRIMARY KEY,
    chat_id INTEGER,
    name TEXT,
    created_at TEXT NOT NULL
);
"""


async def init_db() -> None:
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    async with _db() as db:
        await db.executescript(_SCHEMA)
        # идемпотентная миграция: старая схема admins без chat_id
        try:
            await db.execute("ALTER TABLE admins ADD COLUMN chat_id INTEGER")
        except Exception:
            pass
        await db.commit()


async def seed_admins(admins: list[dict]) -> None:
    """Засеять постоянных админов из конфига (идемпотентно)."""
    if not admins:
        return
    async with _db() as db:
        for a in admins:
            await db.execute(
                "INSERT INTO admins (user_id, chat_id, name, created_at) "
                "VALUES (?, ?, ?, ?) "
                "ON CONFLICT(user_id) DO UPDATE SET "
                "chat_id=excluded.chat_id, name=excluded.name",
                (a["user_id"], a["chat_id"], a["name"],
                 _utc_now()),
            )
        await db.commit()


async def list_admins() -> list[dict]:
    async with _db() as db:
        async with db.execute(
            "SELECT user_id, chat_id, name FROM admins"
        ) as cur:
            rows = await cur.fetchall()
    return [{"user_id": r[0], "chat_id": r[1], "name": r[2]} for r in rows]


async def save_contact(
    *,
    user_id: int,
    chat_id: Optional[int],
    branch: str,
    name: str,
    city: str,
    school: str,
    phone: str,
    username: Optional[str] = None,
) -> None:
    async with _db() as db:
        await db.execute(
            """
            INSERT INTO contacts
                (user_id, chat_id, branch, name, city, school, phone, username, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(user_id, branch) DO UPDATE SET
                name=excluded.name,
                city=excluded.city,
                school=excluded.school,
                phone=excluded.phone,
                username=excluded.username,
                created_at=excluded.created_at
            """,
            (
                user_id,
                chat_id,
                branch,
                name,
                city,
                school,
                phone,
                username,
                _utc_now(),
            ),
        )
        await db.commit()


async def export_csv() -> bytes:
    async with _db() as db:
        async with db.execute(
            "SELECT created_at, branch, name, city, school, phone, username, user_id "
            "FROM contacts ORDER BY created_at DESC"
        ) as cur:
            rows = await cur.fetchall()

    buf = io.StringIO()
    writer = csv.writer(buf, delimiter=";")
    writer.writerow(["Дата", "Ветка", "ФИО", "Город", "Школа", "Телефон", "username", "user_id"])
    for row in rows:
        writer.writerow([_sheet_safe(c) for c in row])
    # Excel-friendly: UTF-8 with BOM
    return "\ufeff".encode("utf-8") + buf.getvalue().encode("utf-8")


async def stats() -> dict[str, int]:
    async with _db() as db:
        async with db.execute(
            "SELECT branch, COUNT(*) FROM contacts GROUP BY branch"
        ) as cur:
            by_branch = {b: n for b, n in await cur.fetchall()}
        async with db.execute("SELECT COUNT(DISTINCT user_id) FROM contacts") as cur:
            (unique_users,) = await cur.fetchone()
    return {"total_records": sum(by_branch.values()), "unique_users": unique_users, **{f"branch_{k}": v for k, v in by_branch.items()}}


async def add_admin(user_id: int, name: str, chat_id: int | None = None) -> None:
    async with _db() as db:
        await db.execute(
            "INSERT INTO admins (user_id, chat_id, name, created_at) "
            "VALUES (?, ?, ?, ?) "
            "ON CONFLICT(user_id) DO UPDATE SET "
            "chat_id=COALESCE(excluded.chat_id, admins.chat_id), name=excluded.name",
            (user_id, chat_id, name, _utc_now()),
        )
        await db.commit()


async def is_admin(user_id: int) -> bool:
    async with _db() as db:
        async with db.execute(
            "SELECT 1 FROM admins WHERE user_id = ?", (user_id,)
        ) as cur:
            return (await cur.fetchone()) is not None


async def forget_user(user_id: int) -> int:
    """Удаляет все записи пользователя из contacts (152-ФЗ: право на удаление)."""
    async with _db() as db:
        cur = await db.execute("DELETE FROM contacts WHERE user_id = ?", (user_id,))
        await db.commit()
        return cur.rowcount or 0


async def contacts_for_period(start_iso: str, end_iso: str) -> list[dict]:
    """Контакты, созданные в интервале [start, end) (UTC ISO)."""
    async with _db() as db:
        async with db.execute(
            "SELECT created_at, branch, name, city, school, phone FROM contacts "
            "WHERE created_at >= ? AND created_at < ? ORDER BY created_at",
            (start_iso, end_iso),
        ) as cur:
            rows = await cur.fetchall()
    return [
        {"created_at": r[0], "branch": r[1], "name": r[2],
         "city": r[3], "school": r[4], "phone": r[5]}
        for r in rows
    ]
