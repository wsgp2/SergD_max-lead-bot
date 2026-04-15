import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).parent

MAX_BOT_TOKEN = os.environ["MAX_BOT_TOKEN"]
CHANNEL_URL = os.environ.get("CHANNEL_URL", "https://max.ru/")
PROMO_A = os.environ.get("PROMO_A", "ПЕДАГОГ20")
PROMO_C = os.environ.get("PROMO_C", "ПЕДАГОГ30")

DB_PATH = BASE_DIR / os.environ.get("DB_PATH", "data/contacts.db")
FILES_DIR = BASE_DIR / os.environ.get("FILES_DIR", "files")

METHODICHKA_PATH = FILES_DIR / "methodichka.pdf"
DOGOVOR_PATH = FILES_DIR / "dogovor.pdf"

BRANCH_DISCOUNT = "A"
BRANCH_PARTNERSHIP = "B"
BRANCH_IDEAS = "C"


def _parse_admins(raw: str) -> list[dict]:
    """Parse 'user_id:chat_id:name, user_id:chat_id:name' → list of dicts."""
    admins: list[dict] = []
    for chunk in (raw or "").split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        parts = chunk.split(":", 2)
        try:
            uid = int(parts[0])
        except (ValueError, IndexError):
            continue
        cid = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else uid
        name = parts[2].strip() if len(parts) > 2 else "admin"
        admins.append({"user_id": uid, "chat_id": cid, "name": name})
    return admins


SEED_ADMINS = _parse_admins(os.environ.get("ADMIN_USER_IDS", ""))
SEED_ADMIN_IDS: set[int] = {a["user_id"] for a in SEED_ADMINS}

DIGEST_TZ = os.environ.get("DIGEST_TZ", "Asia/Yekaterinburg")
DIGEST_HOUR = int(os.environ.get("DIGEST_HOUR", "8"))
DIGEST_MINUTE = int(os.environ.get("DIGEST_MINUTE", "0"))
