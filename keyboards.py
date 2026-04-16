"""Фабрики inline-клавиатур."""
from maxapi.types import (
    ButtonsPayload,
    CallbackButton,
    ClipboardButton,
    LinkButton,
    RequestContactButton,
)
from maxapi.types.attachments.buttons.attachment_button import AttachmentButton
from maxapi.enums.attachment import AttachmentType
from maxapi.enums.intent import Intent

import texts
from config import CHANNEL_URL

NEXT_BUTTON_TEXT = "Далее →"


def _ikb(rows: list[list]) -> list[AttachmentButton]:
    """Оборачивает список рядов кнопок в attachment."""
    return [AttachmentButton(type=AttachmentType.INLINE_KEYBOARD, payload=ButtonsPayload(buttons=rows))]


def next_welcome() -> list[AttachmentButton]:
    """Кнопка «Далее →» между первым и вторым экраном приветствия."""
    return _ikb([
        [CallbackButton(text=NEXT_BUTTON_TEXT, payload="next_welcome", intent=Intent.POSITIVE)],
    ])


def main_menu() -> list[AttachmentButton]:
    return _ikb([
        [CallbackButton(text=texts.MENU_BUTTONS["A"], payload="menu:A", intent=Intent.POSITIVE)],
        [CallbackButton(text=texts.MENU_BUTTONS["B"], payload="menu:B", intent=Intent.POSITIVE)],
        [CallbackButton(text=texts.MENU_BUTTONS["C"], payload="menu:C")],
    ])


def start_form(branch: str) -> list[AttachmentButton]:
    label = {
        "A": texts.START_FORM_A_BUTTON_TEXT,
        "B": texts.START_FORM_B_BUTTON_TEXT,
    }[branch]
    return _ikb([
        [CallbackButton(text=label, payload=f"form_start:{branch}", intent=Intent.POSITIVE)],
    ])


def branch_c_menu() -> list[AttachmentButton]:
    return _ikb([
        [CallbackButton(text=texts.DISCOUNT_BUTTON_TEXT, payload="form_start:A", intent=Intent.POSITIVE)],
        [CallbackButton(text=texts.RECIPE_BUTTON_TEXT, payload="recipe")],
    ])


def share_contact() -> list[AttachmentButton]:
    return _ikb([[RequestContactButton(text=texts.SHARE_CONTACT_BUTTON_TEXT)]])


def after_branch_a() -> list[AttachmentButton]:
    return _ikb([
        [CallbackButton(
            text=texts.TO_PARTNERSHIP_BUTTON_TEXT,
            payload="menu:B",
            intent=Intent.POSITIVE,
        )],
        [ClipboardButton(text=texts.COPY_SCRIPT_BUTTON_TEXT, payload=texts.SCRIPT_CLIPBOARD_CONTENT)],
        [LinkButton(text=texts.CHANNEL_BUTTON_TEXT, url=CHANNEL_URL)],
    ])


def after_branch_b() -> list[AttachmentButton]:
    return _ikb([
        [ClipboardButton(text=texts.COPY_SCRIPT_BUTTON_TEXT, payload=texts.SCRIPT_CLIPBOARD_CONTENT)],
        [LinkButton(text=texts.CHANNEL_BUTTON_TEXT, url=CHANNEL_URL)],
    ])


def channel_only() -> list[AttachmentButton]:
    return _ikb([[LinkButton(text=texts.CHANNEL_BUTTON_TEXT, url=CHANNEL_URL)]])
