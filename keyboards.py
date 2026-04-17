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


def _ikb(rows: list[list]) -> list[AttachmentButton]:
    """Оборачивает список рядов кнопок в attachment."""
    return [AttachmentButton(type=AttachmentType.INLINE_KEYBOARD, payload=ButtonsPayload(buttons=rows))]


def get_discount_contact() -> list[AttachmentButton]:
    """Главная кнопка воронки: request_contact для мгновенной скидки."""
    return _ikb([
        [RequestContactButton(text=texts.GET_DISCOUNT_BUTTON_TEXT)],
    ])


def main_menu() -> list[AttachmentButton]:
    return _ikb([
        [CallbackButton(text=texts.MENU_BUTTONS["A"], payload="menu:A", intent=Intent.POSITIVE)],
        [CallbackButton(text=texts.MENU_BUTTONS["B"], payload="menu:B", intent=Intent.POSITIVE)],
        [CallbackButton(text=texts.MENU_BUTTONS["C"], payload="menu:C")],
    ])


def branch_c_menu() -> list[AttachmentButton]:
    return _ikb([
        [CallbackButton(text=texts.DISCOUNT_BUTTON_TEXT, payload="menu:A", intent=Intent.POSITIVE)],
        [CallbackButton(text=texts.RECIPE_BUTTON_TEXT, payload="recipe")],
    ])


def after_discount() -> list[AttachmentButton]:
    """После получения скидки: скрипт + канал."""
    return _ikb([
        [ClipboardButton(text=texts.COPY_SCRIPT_BUTTON_TEXT, payload=texts.SCRIPT_CLIPBOARD_CONTENT)],
        [LinkButton(text=texts.CHANNEL_BUTTON_TEXT, url=CHANNEL_URL)],
    ])


def channel_only() -> list[AttachmentButton]:
    return _ikb([[LinkButton(text=texts.CHANNEL_BUTTON_TEXT, url=CHANNEL_URL)]])
