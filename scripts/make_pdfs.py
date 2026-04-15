"""Генерирует плейсхолдер-PDF для методички и договора.

Запускается один раз: python scripts/make_pdfs.py
Потом файлы можно заменить на настоящие — имена сохранить:
  files/methodichka.pdf
  files/dogovor.pdf
"""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

from config import DOGOVOR_PATH, METHODICHKA_PATH, FILES_DIR


# ReportLab по умолчанию не имеет кириллических шрифтов; используем системный DejaVu Sans (есть в macOS/Linux).
FONT_CANDIDATES = [
    "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
    "/Library/Fonts/Arial Unicode.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/TTF/DejaVuSans.ttf",
    "/usr/share/fonts/dejavu/DejaVuSans.ttf",
]


def _register_font() -> str:
    for path in FONT_CANDIDATES:
        if Path(path).exists():
            pdfmetrics.registerFont(TTFont("Body", path))
            return "Body"
    return "Helvetica"


def _styles(font_name: str):
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name="Body2", fontName=font_name, fontSize=11, leading=15))
    styles.add(ParagraphStyle(name="Title2", fontName=font_name, fontSize=18, leading=22, spaceAfter=12))
    styles.add(ParagraphStyle(name="H2", fontName=font_name, fontSize=14, leading=18, spaceAfter=8))
    return styles


def _write(path: Path, title: str, paragraphs: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    font = _register_font()
    styles = _styles(font)
    doc = SimpleDocTemplate(
        str(path), pagesize=A4,
        leftMargin=2 * cm, rightMargin=2 * cm, topMargin=2 * cm, bottomMargin=2 * cm,
    )
    story = [Paragraph(title, styles["Title2"]), Spacer(1, 0.5 * cm)]
    for p in paragraphs:
        if p.startswith("## "):
            story.append(Paragraph(p[3:], styles["H2"]))
        else:
            story.append(Paragraph(p, styles["Body2"]))
            story.append(Spacer(1, 0.3 * cm))
    doc.build(story)
    print(f"✓ {path}")


def make_methodichka() -> None:
    _write(
        METHODICHKA_PATH,
        "5 идей для урока с пряником",
        [
            "Подарок от «Больших пряничников Урала» для педагогов-участников форума.",
            "## 1. Русский язык: рецепт в повелительном наклонении",
            "Дети пишут рецепт пряника, используя только глаголы в повелительном наклонении (возьми, смешай, раскатай). Затем проводят мастер-класс по собственному рецепту — это сразу и орфография, и живая речь.",
            "## 2. История: чаепитие по купеческим традициям",
            "Урок-погружение: самовар, русские костюмы, рассказ о пряничном промысле Урала. Дети узнают, что пряник был валютой, оберегом и подарком на свадьбе.",
            "## 3. Математика: пропорции на 30 человек",
            "Даём рецепт на 4 порции — дети пересчитывают на класс. Работа с дробями и процентами становится прикладной и вкусной.",
            "## 4. ИЗО: роспись козуль",
            "Знакомство с белковой глазурью и традиционными узорами Северного Урала. Каждый ребёнок уносит свою расписанную козулю.",
            "## 5. Окружающий мир: славянские обряды",
            "Коляда, Масленица, Пасха — пряники как часть календарного цикла. Дети не просто слушают — они участвуют в обряде посвящения в пряничники.",
            "## Хотите провести такой урок у себя в школе?",
            "Напишите в наш канал или ответьте боту «Пробую» — мы договоримся о датах и условиях. До встречи на Урале! 🍪",
        ],
    )


def make_dogovor() -> None:
    _write(
        DOGOVOR_PATH,
        "Положение о партнёрстве и пример договора",
        [
            "ПЛЕЙСХОЛДЕР: этот файл будет заменён на настоящий договор до запуска.",
            "## Суть партнёрства",
            "Школа становится партнёром «Больших пряничников Урала». За каждые 3 проведённых в школе мастер-класса школа получает 15% от выручки на свой счёт.",
            "## Что предоставляем мы",
            "Ведущая в русском костюме, волонтёры, все ингредиенты, колпаки и фартуки, оборудование, фотоуслуги, посвящение в пряничники, дипломы.",
            "## Что требуется от школы",
            "Актовый зал или классная комната, согласование даты, информирование родителей, ответственный педагог.",
            "## Пример расчёта",
            "10 мастер-классов × 8 000 руб. = 80 000 руб. выручки. Школа получает 15% = 12 000 руб. на счёт (библиотека, канцелярия, ремонт — на усмотрение школы).",
            "## Как подписать договор",
            "Позвоните по номеру +7 (XXX) XXX-XX-XX или ответьте боту «Пробую» — мы пришлём полную версию договора и подпишем его ЭЦП за 1 день.",
            "## Контакты",
            "Елена Маслакова, «Большие пряничники Урала». Канал в MAX: max.ru/join/...",
        ],
    )


if __name__ == "__main__":
    FILES_DIR.mkdir(parents=True, exist_ok=True)
    make_methodichka()
    make_dogovor()
