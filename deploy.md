# Деплой бота «Большие пряничники Урала» (MAX)

**Цель**: развернуть бот на Oracle-сервере `168.110.208.184` рядом с остальными продакшен-ботами.

## Базовые факты о сервере

- **Хост**: `168.110.208.184`
- **ОС**: Ubuntu 24.04 LTS (aarch64 / ARM)
- **SSH пользователь**: `ubuntu`
- **SSH ключ**: `/Users/wsgp/Searching projects/telegram_voice_translator/ssh-key-2025-06-05.key`
- **Расположение бота**: `/home/ubuntu/bots/pryanik_bot/`
- **Имя сервиса**: `pryanik-bot.service` (содержит «bot» → bot-monitor подхватит автоматически)
- **Логи**: `/home/ubuntu/bots/pryanik_bot/logs/pryanik-bot.log` (именно `logs/*.log` — мониторит `bot-monitor.service`)
- **venv**: `venv/` (а не `.venv`, как локально)
- **Занятых портов не требуется** — long-polling, только исходящий HTTPS 443

---

## Шаг 1. Копируем файлы на сервер

С рабочей машины (этот Mac):

```bash
SSH_KEY="/Users/wsgp/Searching projects/telegram_voice_translator/ssh-key-2025-06-05.key"
SERVER=ubuntu@168.110.208.184
REMOTE=/home/ubuntu/bots/pryanik_bot

# создать директорию
ssh -i "$SSH_KEY" "$SERVER" "mkdir -p $REMOTE/logs"

# синхронизировать код (без локальных .venv, data, логов)
rsync -av --delete \
  -e "ssh -i \"$SSH_KEY\"" \
  --exclude='.venv' --exclude='__pycache__' --exclude='.env' \
  --exclude='data/' --exclude='bot.log' --exclude='test_debug.py' \
  /Users/wsgp/SergD_Max_Bot/ "$SERVER:$REMOTE/"

# .env копируем отдельно (rsync его исключил)
scp -i "$SSH_KEY" /Users/wsgp/SergD_Max_Bot/.env "$SERVER:$REMOTE/.env"
```

---

## Шаг 2. Системные пакеты (один раз)

```bash
ssh -i "$SSH_KEY" "$SERVER"

# на сервере:
sudo apt update
sudo apt install -y python3 python3-venv python3-pip fonts-dejavu-core sqlite3
```

`fonts-dejavu-core` обязателен — без него `scripts/make_pdfs.py` не рендерит кириллицу.

---

## Шаг 3. Ставим зависимости и генерируем PDF

```bash
cd /home/ubuntu/bots/pryanik_bot
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

# сгенерить плейсхолдер-PDF (можно потом заменить настоящими файлами)
python scripts/make_pdfs.py

# проверить: файлы созданы, кириллица читается
python -c "
from pathlib import Path
for p in ('files/methodichka.pdf','files/dogovor.pdf'):
    s = Path(p).stat().st_size
    head = Path(p).read_bytes()[:4]
    print(p, s, 'bytes,', 'OK' if head==b'%PDF' and s>10000 else 'BAD')
"

chmod 600 .env
```

**Если у заказчика есть настоящие PDF** — положите их в `files/methodichka.pdf` и `files/dogovor.pdf` (имена менять нельзя), перезапустите сервис.

---

## Шаг 4. Systemd-сервис

На сервере:

```bash
cat > /tmp/pryanik-bot.service << 'EOF'
[Unit]
Description=Pryanik MAX bot (большие пряничники Урала)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=ubuntu
Group=ubuntu
WorkingDirectory=/home/ubuntu/bots/pryanik_bot
ExecStart=/home/ubuntu/bots/pryanik_bot/venv/bin/python3 bot.py
Restart=always
RestartSec=10
StandardOutput=append:/home/ubuntu/bots/pryanik_bot/logs/pryanik-bot.log
StandardError=append:/home/ubuntu/bots/pryanik_bot/logs/pryanik-bot.log
Environment=PYTHONPATH=/home/ubuntu/bots/pryanik_bot

[Install]
WantedBy=multi-user.target
EOF

sudo cp /tmp/pryanik-bot.service /etc/systemd/system/pryanik-bot.service
sudo systemctl daemon-reload
sudo systemctl enable pryanik-bot.service
sudo systemctl start pryanik-bot.service
```

Проверка:

```bash
sudo systemctl status pryanik-bot.service
tail -30 /home/ubuntu/bots/pryanik_bot/logs/pryanik-bot.log
```

Ожидаемые строки в логе:

```
INFO bot: Засеяно админов: Елена Маслакова, Алексей Радополк
INFO bot: Bot started: id450205498767_bot (id=259577383)
INFO notifier: Запущен планировщик дайджестов: 08:00 Asia/Yekaterinburg
INFO dispatcher: Зарегистрировано N обработчиков событий
```

---

## Шаг 5. Smoke-тест

```bash
cd /home/ubuntu/bots/pryanik_bot
./scripts/post_deploy_check.sh
```

Должно показать: `✓ Bot: ... active, Bot started в логе`.

Параллельно — в MAX:
1. Написать боту `/start` → пришло приветствие + 3 кнопки
2. Пройти ветку А до конца → прилетел промокод + PDF
3. Админ (Елена или Алексей) в личке получил уведомление «🆕 Новая анкета»
4. Админ пишет `/stats` — получает цифры, `/digest` — получает дайджест за вчера

---

## Обновление кода (потом)

```bash
SSH_KEY="/Users/wsgp/Searching projects/telegram_voice_translator/ssh-key-2025-06-05.key"

# синхронизировать новые файлы
rsync -av --delete \
  -e "ssh -i \"$SSH_KEY\"" \
  --exclude='.venv' --exclude='__pycache__' --exclude='.env' \
  --exclude='data/' --exclude='bot.log' --exclude='test_debug.py' \
  /Users/wsgp/SergD_Max_Bot/ ubuntu@168.110.208.184:/home/ubuntu/bots/pryanik_bot/

# если зависимости поменялись — обновить; затем рестарт
ssh -i "$SSH_KEY" ubuntu@168.110.208.184 '
  cd /home/ubuntu/bots/pryanik_bot && \
  source venv/bin/activate && \
  pip install -q -r requirements.txt && \
  sudo systemctl restart pryanik-bot.service && \
  sleep 3 && \
  tail -15 logs/pryanik-bot.log
'
```

---

## Бэкап БД (cron)

На живой SQLite `rsync` может скопировать пол-транзакции. Используем `sqlite3 .backup`:

```bash
ssh -i "$SSH_KEY" ubuntu@168.110.208.184

# на сервере:
mkdir -p /home/ubuntu/bots/pryanik_bot/backups
crontab -e
# вписать:
0 */6 * * * /usr/bin/sqlite3 /home/ubuntu/bots/pryanik_bot/data/contacts.db ".backup '/home/ubuntu/bots/pryanik_bot/backups/contacts-$(date +\%Y\%m\%d-\%H).db'" && find /home/ubuntu/bots/pryanik_bot/backups -name 'contacts-*.db' -mtime +14 -delete
```

---

## Откат

```bash
ssh -i "$SSH_KEY" ubuntu@168.110.208.184
sudo systemctl stop pryanik-bot.service
# вернуть код/БД из бэкапа
sudo systemctl start pryanik-bot.service
```

---

## Ручная выгрузка контактов (без бота)

```bash
ssh -i "$SSH_KEY" ubuntu@168.110.208.184 \
  'sqlite3 /home/ubuntu/bots/pryanik_bot/data/contacts.db -header -csv \
   "SELECT created_at, branch, name, city, school, phone FROM contacts ORDER BY created_at DESC"' \
  > contacts_$(date +%Y%m%d).csv
```

Или прямо в чате с ботом — команда `/export` от имени админа.

---

## Что мониторится автоматически

На сервере крутится `bot-monitor.service` — он:
- видит сервисы по pattern-имени (у нас имя содержит `bot` → ок)
- сканит `logs/*.log` на ERROR/CRITICAL каждые 15 минут
- шлёт алерты в Telegram `@SergD_bot_monitor` при ошибках
- делает утренний отчёт в 09:00 Екб

Проверить, что бот виден мониторингу — в Telegram `@SergD_bot_monitor` → `/status` (должен быть `pryanik-bot`).

---

## Чек-лист перед форумом

- [ ] `/start` в MAX — приветствие и 3 кнопки
- [ ] Пройдена анкета А от начала до конца — пришёл промокод + PDF
- [ ] Админ получил DM-уведомление о новой регистрации
- [ ] Настоящие методичка и договор в `files/*.pdf` (заменить плейсхолдеры!)
- [ ] QR-код на стойку сгенерирован из `https://max.ru/<bot_username>` (или deep-link)
- [ ] `.env` на сервере имеет права `600`
- [ ] В `bot-monitor` → `/status` виден `pryanik-bot`
- [ ] Бэкап БД cron настроен

---

## 152-ФЗ / ПДн

- Согласие пользователя на обработку ПДн зашито в текст первой строки формы.
- По фразе «удалить мои данные» бот удаляет все записи пользователя (право на удаление).
- БД живёт локально на российском сервере (Oracle Moscow region), бэкапы — там же.
- Рекомендуется подать уведомление об операторе ПДн в РКН (`reestr.rkn.gov.ru`), если ещё не подано.
