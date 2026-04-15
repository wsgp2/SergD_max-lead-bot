"""Обработчики событий бота."""
from __future__ import annotations

import asyncio
import logging
import re
from typing import Optional

from maxapi import Router, F
from maxapi.context import MemoryContext
from maxapi.context.state_machine import State, StatesGroup
from maxapi.filters.command import Command, CommandStart
from maxapi.types import (
    BotStarted,
    MessageCallback,
    MessageCreated,
)
from maxapi.types.attachments.contact import Contact
from maxapi.types.input_media import InputMediaBuffer, InputMedia
from maxapi.enums.parse_mode import TextFormat

import keyboards as kb
import notifier
import storage
import texts
from config import (
    BRANCH_DISCOUNT,
    BRANCH_PARTNERSHIP,
    BRANCH_IDEAS,
    DOGOVOR_PATH,
    METHODICHKA_PATH,
    SEED_ADMIN_IDS,
)

log = logging.getLogger("handlers")
router = Router("pryanik")


class Form(StatesGroup):
    name = State()
    city = State()
    school = State()
    phone = State()


PHONE_RE = re.compile(r"[\d\s\-\+\(\)]{7,}")


def _first_name(full: str) -> str:
    """Из ФИО «Фамилия Имя Отчество» достаём имя, иначе — первое слово."""
    parts = (full or "").split()
    if len(parts) >= 2:
        return parts[1]
    if parts:
        return parts[0]
    return "друг"


_MD_ESCAPE_RE = re.compile(r"([\\*_`\[\]()~>#+\-=|{}.!])")


def _md_escape(s: str) -> str:
    """Экранирует markdown-метасимволы, чтобы пользовательское имя не сломало рендер."""
    return _MD_ESCAPE_RE.sub(r"\\\1", s or "")


def _log_task_result(task: asyncio.Task) -> None:
    """Не даём «Task exception was never retrieved» — логируем ошибку фоновой задачи."""
    if task.cancelled():
        return
    exc = task.exception()
    if exc is not None:
        log.exception("Ошибка в фоновой задаче %s: %r", task.get_name(), exc)


# ---------- Start / welcome ----------


@router.bot_started()
async def on_bot_started(event: BotStarted) -> None:
    await event.bot.send_message(
        chat_id=event.chat_id,
        text=texts.WELCOME,
        attachments=kb.main_menu(),
        format=TextFormat.MARKDOWN,
    )


@router.message_created(CommandStart())
async def on_start(event: MessageCreated, context: MemoryContext) -> None:
    await context.set_state(None)
    await context.set_data({})
    await event.message.answer(
        text=texts.WELCOME,
        attachments=kb.main_menu(),
        format=TextFormat.MARKDOWN,
    )


@router.message_created(Command("menu"))
async def on_menu(event: MessageCreated, context: MemoryContext) -> None:
    await context.set_state(None)
    await event.message.answer(
        text="Выберите, что вам интересно 👇",
        attachments=kb.main_menu(),
    )


# ---------- Menu callbacks ----------


@router.message_callback(F.callback.payload == "menu:A")
async def cb_menu_a(event: MessageCallback, context: MemoryContext) -> None:
    await context.set_state(None)
    await context.update_data(branch=BRANCH_DISCOUNT)
    await event.bot.send_message(
        user_id=event.from_user.user_id,
        text=texts.BRANCH_A_INTRO,
        attachments=kb.start_form(BRANCH_DISCOUNT),
    )


@router.message_callback(F.callback.payload == "menu:B")
async def cb_menu_b(event: MessageCallback, context: MemoryContext) -> None:
    await context.set_state(None)
    await context.update_data(branch=BRANCH_PARTNERSHIP)
    await event.bot.send_message(
        user_id=event.from_user.user_id,
        text=texts.BRANCH_B_INTRO,
        attachments=kb.start_form(BRANCH_PARTNERSHIP),
    )


@router.message_callback(F.callback.payload == "menu:C")
async def cb_menu_c(event: MessageCallback, context: MemoryContext) -> None:
    await context.set_state(None)
    await context.update_data(branch=BRANCH_IDEAS)
    await event.bot.send_message(
        user_id=event.from_user.user_id,
        text=texts.BRANCH_C_TEXT,
        attachments=kb.branch_c_menu(),
    )


@router.message_callback(F.callback.payload == "recipe")
async def cb_recipe(event: MessageCallback) -> None:
    await event.bot.send_message(
        user_id=event.from_user.user_id,
        text=texts.KOZULI_RECIPE,
        attachments=kb.channel_only(),
    )


# ---------- Form flow ----------


@router.message_callback(F.callback.payload.startswith("form_start:"))
async def cb_form_start(event: MessageCallback, context: MemoryContext) -> None:
    branch = event.callback.payload.split(":", 1)[1]
    await context.update_data(branch=branch)
    await context.set_state(Form.name)
    await event.bot.send_message(
        user_id=event.from_user.user_id,
        text=texts.FORM_ASK_NAME,
    )


@router.message_created(states=[Form.name])
async def form_name(event: MessageCreated, context: MemoryContext) -> None:
    text = (event.message.body.text or "").strip()
    if len(text) < 2:
        await event.message.answer("Пожалуйста, напишите ФИО текстом.")
        return
    await context.update_data(name=text)
    await context.set_state(Form.city)
    await event.message.answer(texts.FORM_ASK_CITY.format(name=_first_name(text)))


@router.message_created(states=[Form.city])
async def form_city(event: MessageCreated, context: MemoryContext) -> None:
    text = (event.message.body.text or "").strip()
    if len(text) < 2:
        await event.message.answer("Напишите город текстом, пожалуйста.")
        return
    await context.update_data(city=text)
    await context.set_state(Form.school)
    await event.message.answer(texts.FORM_ASK_SCHOOL)


@router.message_created(states=[Form.school])
async def form_school(event: MessageCreated, context: MemoryContext) -> None:
    text = (event.message.body.text or "").strip()
    if len(text) < 2:
        await event.message.answer("Напишите название или номер школы.")
        return
    await context.update_data(school=text)
    await context.set_state(Form.phone)
    await event.message.answer(
        text=texts.FORM_ASK_PHONE,
        attachments=kb.share_contact(),
    )


def _extract_phone_from_contact(event: MessageCreated) -> Optional[str]:
    atts = event.message.body.attachments or []
    for a in atts:
        if isinstance(a, Contact):
            phone = a.payload.vcf.phone if a.payload else None
            if phone:
                return phone
    return None


def _extract_phone_from_text(text: str) -> Optional[str]:
    m = PHONE_RE.search(text or "")
    if not m:
        return None
    raw = re.sub(r"\D", "", m.group(0))
    if len(raw) < 10:
        return None
    if len(raw) == 10:
        raw = "7" + raw
    return "+" + raw


@router.message_created(states=[Form.phone])
async def form_phone(event: MessageCreated, context: MemoryContext) -> None:
    phone = _extract_phone_from_contact(event)
    if not phone:
        phone = _extract_phone_from_text(event.message.body.text or "")
    if not phone:
        await event.message.answer(
            text=texts.FORM_INVALID_PHONE,
            attachments=kb.share_contact(),
        )
        return

    data = await context.get_data()
    branch = data.get("branch", BRANCH_DISCOUNT)
    sender = event.message.sender
    chat_id = event.message.recipient.chat_id if event.message.recipient else None
    contact = {
        "user_id": sender.user_id,
        "chat_id": chat_id,
        "branch": branch,
        "name": data.get("name", ""),
        "city": data.get("city", ""),
        "school": data.get("school", ""),
        "phone": phone,
        "username": getattr(sender, "username", None),
    }
    await storage.save_contact(**contact)
    await context.set_state(None)

    # Уведомляем админов о новой анкете (не ждём — параллельно основному ответу).
    notify_task = asyncio.create_task(
        notifier.notify_new_contact(event.bot, contact),
        name=f"notify_admins:{sender.user_id}",
    )
    notify_task.add_done_callback(_log_task_result)

    first_name = _md_escape(_first_name(data.get("name", "")))

    if branch == BRANCH_PARTNERSHIP:
        await event.message.answer(texts.form_done_branch_b(first_name), format=TextFormat.MARKDOWN)
        await _send_file_safely(event, DOGOVOR_PATH, caption=None)
        await event.message.answer(
            text=texts.SCRIPT_FOR_DIRECTOR,
            attachments=kb.after_branch_b(),
        )
        await event.message.answer(
            text=texts.FINAL_CHANNEL_INVITE,
            attachments=kb.channel_only(),
        )
    else:
        # BRANCH_DISCOUNT (A) — и любой fallback
        await event.message.answer(texts.form_done_branch_a(first_name), format=TextFormat.MARKDOWN)
        await _send_file_safely(event, METHODICHKA_PATH, caption=None)
        await event.message.answer(
            text=texts.SCRIPT_FOR_DIRECTOR,
            attachments=kb.after_branch_a(),
        )
        await event.message.answer(
            text=texts.FINAL_CHANNEL_INVITE,
            attachments=kb.channel_only(),
        )


async def _send_file_safely(event: MessageCreated, path, caption: str | None) -> None:
    try:
        if not path.exists():
            log.warning("File %s missing, skipping send", path)
            return
        await event.message.answer(
            text=caption,
            attachments=[InputMedia(path=str(path))],
        )
    except Exception as e:
        log.exception("Failed to send file %s: %s", path, e)


# ---------- Admin ----------


def _is_admin(event: MessageCreated) -> bool:
    """Админ — только те, кто в ADMIN_USER_IDS. Никаких /admin <secret>."""
    return event.message.sender.user_id in SEED_ADMIN_IDS


@router.message_created(Command("export"))
async def cmd_export(event: MessageCreated) -> None:
    if not _is_admin(event):
        await event.message.answer(texts.NOT_ADMIN)
        return
    data = await storage.export_csv()
    buf = InputMediaBuffer(buffer=data, filename="contacts.csv")
    await event.message.answer(text="Выгрузка контактов", attachments=[buf])


@router.message_created(Command("stats"))
async def cmd_stats(event: MessageCreated) -> None:
    if not _is_admin(event):
        await event.message.answer(texts.NOT_ADMIN)
        return
    s = await storage.stats()
    lines = [f"{k}: {v}" for k, v in s.items()]
    await event.message.answer("📊 Статистика\n" + "\n".join(lines))


@router.message_created(Command("digest"))
async def cmd_digest(event: MessageCreated) -> None:
    """Ручной запуск дайджеста за вчера (для админов)."""
    if not _is_admin(event):
        await event.message.answer(texts.NOT_ADMIN)
        return
    await event.message.answer("Отправляю дайджест…")
    await notifier.send_digest_now(event.bot)


@router.message_created(Command("help"))
async def cmd_help(event: MessageCreated) -> None:
    if _is_admin(event):
        await event.message.answer(texts.ADMIN_HELP)
    else:
        await event.message.answer("Напишите /start чтобы начать заново.")


# ---------- Fallback ----------


_FORGET_RE = re.compile(
    r"удал[ияеть]+\s+(?:все\s+|всю\s+|мо[ияе]+\s+|полностью\s+){0,3}данны[ех]",
    re.IGNORECASE,
)


@router.message_created()
async def fallback(event: MessageCreated, context: MemoryContext) -> None:
    """Если пользователь пишет что-то вне FSM — обрабатываем 'удалить мои данные' или показываем меню."""
    text = (event.message.body.text or "").strip()

    # 152-ФЗ: право пользователя на удаление своих данных из бота.
    if _FORGET_RE.search(text):
        removed = await storage.forget_user(event.message.sender.user_id)
        await context.set_state(None)
        await context.set_data({})
        if removed:
            await event.message.answer(
                f"✅ Удалил все ваши данные из системы ({removed} записей).\n"
                "Если захотите вернуться — напишите /start."
            )
        else:
            await event.message.answer(
                "У меня нет ваших данных — вы ещё не заполняли анкету. "
                "Напишите /start, чтобы посмотреть, чем мы полезны."
            )
        return

    state = await context.get_state()
    if state is not None:
        return  # уже обрабатывается FSM-хендлером выше
    await event.message.answer(
        text="Выберите, что вам интересно 👇",
        attachments=kb.main_menu(),
    )
