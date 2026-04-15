"""Дебаг-скрипт: прогоняет все внутренние пути кода и проверяет API MAX.

Запуск: .venv/bin/python test_debug.py
"""
from __future__ import annotations

import asyncio
import json
import logging
import sys
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
log = logging.getLogger("debug")

PASS = "\x1b[32m✓\x1b[0m"
FAIL = "\x1b[31m✗\x1b[0m"
WARN = "\x1b[33m!\x1b[0m"

errors: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    mark = PASS if cond else FAIL
    print(f"{mark} {name}" + (f" — {detail}" if detail else ""))
    if not cond:
        errors.append(name)


async def test_api() -> None:
    print("\n=== 1. MAX API connectivity ===")
    from maxapi import Bot
    from config import MAX_BOT_TOKEN

    bot = Bot(MAX_BOT_TOKEN)
    try:
        me = await bot.get_me()
        check("GET /me returns bot info", me is not None, f"id={me.user_id}, name={me.first_name}")
        check("Bot has username", bool(getattr(me, "username", None)), f"@{me.username}")
        check("Bot is marked is_bot", getattr(me, "is_bot", False))

        # Try to fetch updates once with short timeout
        from maxapi.methods.get_updates import GetUpdates
        from maxapi.enums.update import UpdateType

        try:
            resp = await bot.get_updates(limit=1, timeout=1)
            check("GET /updates returns response", resp is not None)
            if resp is not None:
                ups = getattr(resp, "updates", None) or []
                print(f"  {WARN} в очереди {len(ups)} необработанных обновлений")
        except Exception as e:
            check("GET /updates", False, str(e))

        # Subscriptions (should be empty — мы используем long polling)
        try:
            subs = await bot.get_subscriptions()
            subs_list = getattr(subs, "subscriptions", None) or []
            check("GET /subscriptions works", True, f"подписок: {len(subs_list)}")
            if subs_list:
                print(f"  {WARN} есть активные webhook-подписки — они будут конфликтовать с long polling")
                for s in subs_list:
                    print(f"      - {s}")
        except Exception as e:
            check("GET /subscriptions", False, str(e))

    finally:
        await bot.close_session()


async def test_storage() -> None:
    print("\n=== 2. Storage (SQLite) ===")
    import storage

    # Use a temp DB
    from config import DB_PATH
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)

    await storage.init_db()
    check("init_db ok", True)

    await storage.save_contact(
        user_id=999001, chat_id=999001, branch="A",
        name="Тестов Иван Петрович", city="Екатеринбург", school="Гимназия 1",
        phone="+79001234567", username="ivanp",
    )
    check("save_contact A ok", True)

    # upsert — повторная запись той же ветки не дублирует
    await storage.save_contact(
        user_id=999001, chat_id=999001, branch="A",
        name="Тестов Иван Петрович", city="Екатеринбург", school="Гимназия 1 (обновлено)",
        phone="+79001234567", username="ivanp",
    )
    await storage.save_contact(
        user_id=999002, chat_id=999002, branch="B",
        name="Петрова Мария Сергеевна", city="Челябинск", school="Школа 55",
        phone="+79007654321",
    )

    s = await storage.stats()
    check("stats returns total", s["total_records"] >= 2, json.dumps(s, ensure_ascii=False))
    check("stats unique_users correct", s["unique_users"] == 2, f"got {s['unique_users']}")
    check("branch_A has 1 record (upsert worked)", s.get("branch_A") == 1, f"got {s.get('branch_A')}")

    csv_bytes = await storage.export_csv()
    check("export_csv returns bytes", isinstance(csv_bytes, (bytes, bytearray)) and len(csv_bytes) > 50)
    text = csv_bytes.decode("utf-8")
    check("CSV contains headers", "ФИО" in text and "Телефон" in text)
    check("CSV contains test contact", "Тестов Иван Петрович" in text)
    check("CSV has BOM for Excel", csv_bytes.startswith(b"\xef\xbb\xbf"))

    # Admin
    await storage.add_admin(999001, "Иван")
    check("is_admin true for admin", await storage.is_admin(999001))
    check("is_admin false for regular user", not await storage.is_admin(888000))


def test_keyboards() -> None:
    print("\n=== 3. Keyboard factories ===")
    import keyboards as kb
    from maxapi.enums.button_type import ButtonType

    for name, fn, expected_types in [
        ("main_menu", kb.main_menu, [ButtonType.CALLBACK] * 3),
        ("start_form(A)", lambda: kb.start_form("A"), [ButtonType.CALLBACK]),
        ("start_form(B)", lambda: kb.start_form("B"), [ButtonType.CALLBACK]),
        ("branch_c_menu", kb.branch_c_menu, [ButtonType.CALLBACK, ButtonType.CALLBACK]),
        ("share_contact", kb.share_contact, [ButtonType.REQUEST_CONTACT]),
        ("after_branch_a", kb.after_branch_a, [ButtonType.CALLBACK, ButtonType.CLIPBOARD, ButtonType.LINK]),
        ("after_branch_b", kb.after_branch_b, [ButtonType.CLIPBOARD, ButtonType.LINK]),
        ("channel_only", kb.channel_only, [ButtonType.LINK]),
    ]:
        kb_obj = fn()
        check(f"{name}: 1 attachment", len(kb_obj) == 1)
        rows = kb_obj[0].payload.buttons
        flat = [b.type for r in rows for b in r]
        check(f"{name}: button types = {[t.value for t in expected_types]}", flat == expected_types, f"got {[t.value for t in flat]}")

        # JSON serialization sanity check
        d = kb_obj[0].model_dump(mode="json")
        check(f"{name}: serializable to JSON", json.dumps(d, ensure_ascii=False) is not None)


def test_phone_parsing() -> None:
    print("\n=== 4. Phone parsing ===")
    from handlers import _extract_phone_from_text

    cases = [
        ("+7 900 123-45-67", "+79001234567"),
        ("8 (900) 123-45-67", "+89001234567"),  # 11 digits starting with 8
        ("9001234567", "+79001234567"),          # 10 digits → assume +7
        ("+79001234567", "+79001234567"),
        ("тел +7-900-123-45-67 звоните", "+79001234567"),
        ("abc", None),
        ("123", None),
    ]
    for inp, expected in cases:
        got = _extract_phone_from_text(inp)
        check(f"parse '{inp}' → {expected}", got == expected, f"got {got}")


def test_vcf_parsing() -> None:
    print("\n=== 5. VCF parsing (request_contact flow) ===")
    from maxapi.utils.vcf import parse_vcf_info
    vcf = """BEGIN:VCARD
VERSION:3.0
FN:Иван Петров
TEL;TYPE=CELL:+79001234567
END:VCARD"""
    info = parse_vcf_info(vcf)
    check("VCF full_name parsed", info.full_name == "Иван Петров", f"got {info.full_name!r}")
    check("VCF phone parsed", info.phone == "+79001234567", f"got {info.phone!r}")


def test_texts() -> None:
    print("\n=== 6. Texts (опечатки, плейсхолдеры, 152-ФЗ) ===")
    import texts

    # Old typos that should be GONE
    bad_markers = ["Фотощона", "ОАЗРАБОТКЕ", "свежетспеченных", "пряничного эгрегор",
                   "ПОМЕНЯЮ", "СМС", "смс"]
    for bad in bad_markers:
        found = []
        for name in dir(texts):
            if name.startswith("_"):
                continue
            val = getattr(texts, name)
            if isinstance(val, str) and bad in val:
                found.append(name)
        check(f"no old typo '{bad}'", not found, f"still in: {found}" if found else "")

    # Required tokens
    for token in ["ПЕДАГОГ20", "ПЕДАГОГ30", "Большие пряничники", "мастер-класс"]:
        present = any(
            token in getattr(texts, n) for n in dir(texts)
            if isinstance(getattr(texts, n, None), str)
        )
        check(f"text contains '{token}'", present)

    # Menu buttons populated
    check("3 menu buttons", set(texts.MENU_BUTTONS) == {"A", "B", "C"})

    # Format-call substitution works
    a = texts.form_done_branch_a("Елена")
    check("form_done_branch_a inserts name", "Елена" in a and "ПЕДАГОГ20" in a)
    b = texts.form_done_branch_b("Мария")
    check("form_done_branch_b inserts name", "Мария" in b)

    # 152-ФЗ consent line in form name prompt
    check("FORM_ASK_NAME contains consent (152-ФЗ)",
          "согласие" in texts.FORM_ASK_NAME.lower() and "персональных данных" in texts.FORM_ASK_NAME.lower())
    check("FORM_ASK_NAME упоминает удаление",
          "удалить" in texts.FORM_ASK_NAME.lower())


def test_security_hardening() -> None:
    print("\n=== 10. Security hardening (после ревью) ===")
    import handlers
    import config
    import storage
    import pathlib

    # ADMIN_SECRET и /admin должны быть убраны
    check("config не содержит ADMIN_SECRET",
          not hasattr(config, "ADMIN_SECRET"))
    check("handlers не имеет cmd_admin",
          not hasattr(handlers, "cmd_admin"))
    check("SEED_ADMIN_IDS — set",
          isinstance(config.SEED_ADMIN_IDS, set))
    # В production .env задаёт реальные ID; в публичном тесте проверяем лишь формат.
    check("SEED_ADMIN_IDS — все int",
          all(isinstance(x, int) for x in config.SEED_ADMIN_IDS))

    # _md_escape экранирует markdown метасимволы
    check("_md_escape: экранирует *",
          handlers._md_escape("Елена*evil*") == r"Елена\*evil\*")
    check("_md_escape: экранирует [ ] ( )",
          "\\[" in handlers._md_escape("[link]"))
    check("_md_escape: пустая строка не падает",
          handlers._md_escape("") == "")

    # CSV injection защита
    check("_sheet_safe: префиксует = apostrofom",
          storage._sheet_safe("=cmd|'/c calc'!A1") == "'=cmd|'/c calc'!A1")
    check("_sheet_safe: + префиксуется",
          storage._sheet_safe("+SUM(1)") == "'+SUM(1)")
    check("_sheet_safe: @ префиксуется",
          storage._sheet_safe("@evil") == "'@evil")
    check("_sheet_safe: обычная строка не трогается",
          storage._sheet_safe("Иван Иванов") == "Иван Иванов")
    check("_sheet_safe: None → ''",
          storage._sheet_safe(None) == "")

    # .env.example не должен содержать длинных строк, похожих на живой токен
    env_example = pathlib.Path(__file__).resolve().parent.joinpath(".env.example").read_text()
    import re as _re
    token_line = [ln for ln in env_example.splitlines() if ln.startswith("MAX_BOT_TOKEN=")]
    check(".env.example: MAX_BOT_TOKEN — плейсхолдер",
          bool(token_line) and "replace" in token_line[0].lower(),
          f"текущая строка: {token_line}")
    check(".env.example: ADMIN_USER_IDS пустой",
          bool(_re.search(r"^ADMIN_USER_IDS=\s*$", env_example, _re.MULTILINE)),
          "ADMIN_USER_IDS должен быть пустым в публичном .env.example")

    # SQLite: _db helper настраивает PRAGMA
    import inspect
    src = inspect.getsource(storage._db)
    check("_db ставит WAL", "journal_mode=WAL" in src)
    check("_db ставит busy_timeout", "busy_timeout" in src)


async def test_forget_user_flow() -> None:
    print("\n=== 11. 152-ФЗ: удаление данных ===")
    import storage
    import re
    import handlers

    # Регулярка должна ловить фразы
    for phrase in ["удалить мои данные", "удали все мои данные", "Удалите мои данные"]:
        check(f"regex ловит '{phrase}'", bool(handlers._FORGET_RE.search(phrase)))

    # forget_user удаляет записи
    await storage.save_contact(
        user_id=777001, chat_id=777001, branch="A",
        name="Временный Пользователь", city="Х", school="Y", phone="+79999999999",
    )
    removed = await storage.forget_user(777001)
    check("forget_user удалил запись", removed == 1, f"removed={removed}")
    removed2 = await storage.forget_user(777001)
    check("forget_user повторно = 0", removed2 == 0)


async def test_db_under_concurrency() -> None:
    print("\n=== 12. SQLite под параллельной нагрузкой ===")
    import storage

    async def worker(i: int):
        await storage.save_contact(
            user_id=200000 + i, chat_id=200000 + i, branch="A",
            name=f"Тест{i}", city="Город", school="Школа", phone=f"+7900000{i:04d}",
        )

    # 50 параллельных записей — проверяем, что WAL не ломается
    await asyncio.gather(*[worker(i) for i in range(50)])
    s = await storage.stats()
    check("50 параллельных save_contact записались", s["total_records"] >= 50,
          f"total={s['total_records']}")


def test_pdfs() -> None:
    print("\n=== 7. PDF files ===")
    from config import METHODICHKA_PATH, DOGOVOR_PATH
    for p in [METHODICHKA_PATH, DOGOVOR_PATH]:
        check(f"{p.name} exists", p.exists())
        check(f"{p.name} non-empty", p.exists() and p.stat().st_size > 1000, f"size {p.stat().st_size if p.exists() else 0} b")
        if p.exists():
            head = p.read_bytes()[:4]
            check(f"{p.name} is real PDF", head == b"%PDF", f"header {head!r}")


def test_handlers_registered() -> None:
    print("\n=== 8. Handler registration ===")
    import handlers
    from maxapi.enums.update import UpdateType

    by_type: dict = {}
    for h in handlers.router.event_handlers:
        by_type.setdefault(h.update_type, []).append(h.func_event.__name__)

    check("bot_started registered", UpdateType.BOT_STARTED in by_type)
    check("message_created handlers >= 10", len(by_type.get(UpdateType.MESSAGE_CREATED, [])) >= 10,
          f"got {len(by_type.get(UpdateType.MESSAGE_CREATED, []))}")
    check("message_callback handlers >= 4", len(by_type.get(UpdateType.MESSAGE_CALLBACK, [])) >= 4,
          f"got {len(by_type.get(UpdateType.MESSAGE_CALLBACK, []))}")

    # Fallback must be LAST so specific handlers match first
    msg_handlers = by_type.get(UpdateType.MESSAGE_CREATED, [])
    check("fallback is last message handler", msg_handlers and msg_handlers[-1] == "fallback",
          f"order: {msg_handlers}")


async def test_fsm_dry_run() -> None:
    print("\n=== 9. FSM dry-run (state transitions in memory) ===")
    from maxapi.context import MemoryContext
    from handlers import Form, _first_name

    ctx = MemoryContext(chat_id=1, user_id=1)
    await ctx.set_state(Form.name)
    check("state set to Form.name", (await ctx.get_state()) == Form.name)

    await ctx.update_data(name="Маслакова Елена Ивановна", branch="A")
    data = await ctx.get_data()
    check("data stored", data == {"name": "Маслакова Елена Ивановна", "branch": "A"}, str(data))

    check("_first_name extracts имя", _first_name("Маслакова Елена Ивановна") == "Елена")
    check("_first_name handles single word", _first_name("Елена") == "Елена")
    check("_first_name handles empty", _first_name("") == "друг")

    await ctx.set_state(None)
    check("state cleared", (await ctx.get_state()) is None)


async def main() -> None:
    print("🔧 Полный дебаг-прогон бота «Большие пряничники»\n")

    test_keyboards()
    test_phone_parsing()
    test_vcf_parsing()
    test_texts()
    test_pdfs()
    test_handlers_registered()
    await test_fsm_dry_run()
    await test_storage()
    test_security_hardening()
    await test_forget_user_flow()
    await test_db_under_concurrency()
    await test_api()

    print("\n" + "=" * 50)
    if errors:
        print(f"{FAIL} Ошибок: {len(errors)}")
        for e in errors:
            print(f"  - {e}")
        sys.exit(1)
    else:
        print(f"{PASS} Все проверки прошли")


if __name__ == "__main__":
    asyncio.run(main())
