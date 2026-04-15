#!/usr/bin/env bash
# Smoke-тест после деплоя: проверяем, что бот отвечает на /me.
# Запуск: ./scripts/post_deploy_check.sh
set -e

cd "$(dirname "$0")/.."

if [ ! -f .env ]; then
  echo "✗ .env не найден"
  exit 1
fi

# читаем токен
export MAX_BOT_TOKEN=$(grep -E '^MAX_BOT_TOKEN=' .env | head -1 | cut -d'=' -f2-)

if [ -z "$MAX_BOT_TOKEN" ] || [ "$MAX_BOT_TOKEN" = "replace_me_with_real_token" ]; then
  echo "✗ MAX_BOT_TOKEN не задан в .env"
  exit 2
fi

venv/bin/python - <<'PY'
import asyncio, os
from maxapi import Bot

async def main():
    bot = Bot(os.environ["MAX_BOT_TOKEN"])
    try:
        me = await bot.get_me()
        assert me.is_bot, "Not a bot"
        print(f"✓ Bot: {me.first_name} (@{me.username}, id={me.user_id})")
    finally:
        await bot.close_session()

asyncio.run(main())
PY

# проверяем процесс
if systemctl is-active --quiet pryanik-bot 2>/dev/null; then
  echo "✓ systemd: pryanik-bot active"
else
  echo "! systemd: pryanik-bot НЕ active — проверьте 'systemctl status pryanik-bot'"
fi

# лог
LOG=logs/pryanik-bot.log
if [ -f "$LOG" ]; then
  if tail -50 "$LOG" | grep -q "Bot started"; then
    echo "✓ В логе есть 'Bot started'"
  else
    echo "! В последних 50 строках лога нет 'Bot started' — что-то не так"
  fi
fi

echo "Smoke-тест завершён."
