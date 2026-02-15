import asyncio
import sqlite3
import os
from typing import Any, Dict, List, Optional
from datetime import datetime, date, time, timedelta

from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove

# ================== НАЛАШТУВАННЯ ==================
TOKEN = "8348906081:AAFdGlSs21FDj757b0TfHM81GV5h_V9Ffps"

# ✅ ОДНА БД (абсолютний шлях)
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bot.db")

# Коли слати щоденні нагадування (за Києвом) — 10:00
DAILY_NOTIFY_HOUR = 10
DAILY_NOTIFY_MINUTE = 0

bot = Bot(token=TOKEN)
dp = Dispatcher()


# ================== PHONE NORMALIZE ==================
def normalize_phone(phone: str) -> str:
    phone = (phone or "").strip()
    for ch in [" ", "-", "(", ")", "\t", "\n"]:
        phone = phone.replace(ch, "")
    if phone.startswith("++"):
        phone = phone[1:]

    if phone.startswith("0"):
        phone = "+38" + phone
    elif phone.startswith("380"):
        phone = "+" + phone
    elif phone and not phone.startswith("+"):
        phone = "+" + phone
    return phone


def phone_variants(phone: str) -> List[str]:
    p = normalize_phone(phone)
    s = {p}
    if p.startswith("+"):
        s.add(p[1:])
    if p.startswith("+380"):
        s.add("0" + p[4:])
    return list(s)


# ================== DATE PARSER (ДД.ММ.РРРР) ==================
def parse_client_date(s: Optional[str]) -> Optional[date]:
    if not s:
        return None
    s = str(s).strip()
    if not s or s == "-":
        return None
    try:
        return datetime.strptime(s, "%d.%m.%Y").date()
    except Exception:
        return None


# ================== DB ==================
def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    # Таблиця клієнтів (ваша)
    cur.execute("""
    CREATE TABLE IF NOT EXISTS Table1 (
        ID INTEGER PRIMARY KEY AUTOINCREMENT,
        Код INTEGER,
        ПІБ_Клієнта TEXT,
        Тип_Послуги TEXT,
        Куплено_Сеансів INTEGER,
        Використано_Сеансів INTEGER,
        Дата_Завершення TEXT,
        Сума_курсу REAL,
        Номер TEXT,
        Дата_Візиту TEXT
    )
    """)

    # Прив'язка: user_id -> phone/chat_id
    cur.execute("""
    CREATE TABLE IF NOT EXISTS ClientLinks (
        user_id INTEGER PRIMARY KEY,
        phone TEXT,
        chat_id INTEGER NOT NULL
    )
    """)

    # ✅ ЛОГ СПОВІЩЕНЬ (щоб не дублювати)
    cur.execute("""
    CREATE TABLE IF NOT EXISTS NotifyLog (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        record_id INTEGER NOT NULL,
        kind TEXT NOT NULL,
        payload TEXT NOT NULL,
        created_at TEXT NOT NULL,
        UNIQUE(record_id, kind, payload)
    )
    """)

    conn.commit()
    conn.close()


def fetch_all(query: str, params: tuple = ()) -> List[Dict[str, Any]]:
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(query, params)
    rows = cur.fetchall()
    conn.close()
    return [dict(r) for r in rows]


def fetch_one(query: str, params: tuple = ()) -> Optional[Dict[str, Any]]:
    rows = fetch_all(query, params)
    return rows[0] if rows else None


def execute(query: str, params: tuple = ()) -> None:
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(query, params)
    conn.commit()
    conn.close()


def upsert_link(user_id: int, phone: str, chat_id: int):
    phone = normalize_phone(phone)
    execute("""
        INSERT INTO ClientLinks(user_id, phone, chat_id)
        VALUES(?, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET phone=excluded.phone, chat_id=excluded.chat_id
    """, (user_id, phone, chat_id))


def get_link_by_user(user_id: int) -> Optional[Dict[str, Any]]:
    return fetch_one("SELECT phone, chat_id FROM ClientLinks WHERE user_id=?", (user_id,))


def get_phone_by_user(user_id: int) -> Optional[str]:
    row = get_link_by_user(user_id)
    return row["phone"] if row and row.get("phone") else None


def get_rows_by_phone(phone: str) -> List[Dict[str, Any]]:
    vars_ = phone_variants(phone)
    if not vars_:
        return []
    placeholders = " OR ".join(["Номер=?"] * len(vars_))
    return fetch_all(f"SELECT * FROM Table1 WHERE {placeholders}", tuple(vars_))


def get_all_records() -> List[Dict[str, Any]]:
    return fetch_all("SELECT * FROM Table1")


def get_chat_id_by_phone(phone: str) -> Optional[int]:
    p = normalize_phone(phone)
    row = fetch_one("SELECT chat_id FROM ClientLinks WHERE phone=?", (p,))
    if row:
        return int(row["chat_id"])

    for v in phone_variants(p):
        row2 = fetch_one("SELECT chat_id FROM ClientLinks WHERE phone=?", (v,))
        if row2:
            return int(row2["chat_id"])
    return None


def was_notified(record_id: int, kind: str, payload: str) -> bool:
    row = fetch_one(
        "SELECT 1 FROM NotifyLog WHERE record_id=? AND kind=? AND payload=?",
        (record_id, kind, payload)
    )
    return bool(row)


def mark_notified(record_id: int, kind: str, payload: str):
    execute(
        "INSERT OR IGNORE INTO NotifyLog(record_id, kind, payload, created_at) VALUES(?,?,?,?)",
        (record_id, kind, payload, datetime.now().isoformat(timespec="seconds"))
    )


# ================== FORMAT ==================
def format_date(date_value):
    return date_value if date_value else "не вказано"


def format_money(value):
    if value is None:
        return "0 грн"
    try:
        v = float(value)
    except Exception:
        return f"{value} грн"
    if v.is_integer():
        return f"{int(v)} грн"
    return f"{v:.2f} грн"


def format_client(data: Dict[str, Any]) -> str:
    bought = data.get("Куплено_Сеансів")
    used = data.get("Використано_Сеансів")
    try:
        left = int(bought) - int(used)
    except Exception:
        left = None

    left_str = f"{left}" if left is not None else "?"
    return (
        f"👤 ПІБ: {data.get('ПІБ_Клієнта')}\n"
        f"📌 Послуга: {data.get('Тип_Послуги')}\n"
        f"🎟 Куплено сеансів: {bought}\n"
        f"✔️ Використано сеансів: {used}\n"
        f"🔻 Залишилось сеансів: {left_str}\n"
        f"📅 Завершення: {format_date(data.get('Дата_Завершення'))}\n"
        f"💰 Сума: {format_money(data.get('Сума_курсу'))}\n"
        f"🗓 Візит: {format_date(data.get('Дата_Візиту'))}\n"
        f"━━━━━━━━━━━━━━━━━━\n"
    )


# ================== KEYBOARDS ==================
def phone_request_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="📱 Надіслати мій номер", request_contact=True)]],
        resize_keyboard=True
    )


def menu_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📄 Мої дані")],
            [KeyboardButton(text="🔁 Змінити номер")],
        ],
        resize_keyboard=True
    )


# ================== BOT HANDLERS ==================
@dp.message(CommandStart())
async def start(message: types.Message):
    init_db()
    phone = get_phone_by_user(message.from_user.id)
    if phone:
        await message.answer("✅ Номер уже прив’язано.", reply_markup=menu_kb())
    else:
        await message.answer(
            "Щоб показати ваші сеанси, потрібно підтвердити номер телефону.\n\n"
            "Натисніть кнопку нижче 👇",
            reply_markup=phone_request_kb()
        )


@dp.message(F.contact)
async def got_contact(message: types.Message):
    init_db()

    if not message.contact:
        await message.answer("❌ Контакт не отримано. Спробуйте ще раз.", reply_markup=phone_request_kb())
        return

    if message.contact.user_id is not None and message.contact.user_id != message.from_user.id:
        await message.answer("❌ Надішліть саме ВАШ номер через кнопку 👇", reply_markup=phone_request_kb())
        return

    new_phone = normalize_phone(message.contact.phone_number)

    old = get_link_by_user(message.from_user.id)
    old_phone = normalize_phone(old["phone"]) if old and old.get("phone") else None

    if old_phone and old_phone == new_phone:
        await message.answer(f"✅ Номер уже прив’язано: {new_phone}", reply_markup=ReplyKeyboardRemove())
        await message.answer("Меню:", reply_markup=menu_kb())
        return

    upsert_link(message.from_user.id, new_phone, message.chat.id)

    if old_phone and old_phone != new_phone:
        await message.answer(f"✅ Ваш номер оновлено: {new_phone}", reply_markup=ReplyKeyboardRemove())
    else:
        await message.answer(f"✅ Ваш номер збережено: {new_phone}", reply_markup=ReplyKeyboardRemove())

    await message.answer("Меню:", reply_markup=menu_kb())


@dp.message(F.text == "📄 Мої дані")
async def my_data(message: types.Message):
    init_db()
    phone = get_phone_by_user(message.from_user.id)
    if not phone:
        await message.answer("Спочатку підтвердьте номер телефону 👇", reply_markup=phone_request_kb())
        return
    await send_my_info(message.chat.id, phone)


@dp.message(F.text == "🔁 Змінити номер")
async def change_phone(message: types.Message):
    await message.answer("Ок. Надішліть ваш номер ще раз через кнопку 👇", reply_markup=phone_request_kb())


@dp.message(F.text)
async def any_text(message: types.Message):
    await message.answer("Натисніть «📄 Мої дані» або «🔁 Змінити номер».", reply_markup=menu_kb())


async def send_my_info(chat_id: int, phone: str):
    rows = get_rows_by_phone(phone)
    if not rows:
        await bot.send_message(chat_id, "❌ За вашим номером записів не знайдено.")
        return

    text = "✅ Ваші дані:\n\n"
    for r in rows:
        text += format_client(r)

    await bot.send_message(chat_id, text)


# ================== NOTIFICATIONS ==================
async def run_notification_check():
    init_db()
    today = date.today()

    records = get_all_records()
    for r in records:
        record_id = r.get("ID")
        phone = r.get("Номер")
        if not record_id or not phone:
            continue

        chat_id = get_chat_id_by_phone(phone)
        if not chat_id:
            continue  # клієнт ще не прив'язав номер у боті

        # --- До дати завершення (10, 5, 0 днів) ---
        end_dt = parse_client_date(r.get("Дата_Завершення"))
        if end_dt:
            days_left = (end_dt - today).days
            if days_left in (10, 5, 0):
                payload = f"days_left={days_left}"
                if not was_notified(record_id, "end_date", payload):
                    if days_left == 0:
                        msg = "⏰ Сьогодні *останній день* вашої послуги (дата завершення сьогодні)."
                    else:
                        msg = f"⏰ До завершення послуги залишилось *{days_left}* дн."
                    await bot.send_message(chat_id, msg + "\n\n" + format_client(r), parse_mode="Markdown")
                    mark_notified(record_id, "end_date", payload)

        # --- Залишився 1 сеанс ---
        try:
            bought = int(r.get("Куплено_Сеансів") or 0)
            used = int(r.get("Використано_Сеансів") or 0)
            sessions_left = bought - used
        except Exception:
            sessions_left = None

        if sessions_left == 1:
            payload = "sessions_left=1"
            if not was_notified(record_id, "sessions", payload):
                await bot.send_message(
                    chat_id,
                    "🎟 У вас залишився *1* сеанс.\n\n" + format_client(r),
                    parse_mode="Markdown"
                )
                mark_notified(record_id, "sessions", payload)


async def notification_scheduler():
    while True:
        now = datetime.now()
        target = datetime.combine(now.date(), time(DAILY_NOTIFY_HOUR, DAILY_NOTIFY_MINUTE))
        if now >= target:
            target = target + timedelta(days=1)

        sleep_seconds = (target - now).total_seconds()
        await asyncio.sleep(sleep_seconds)

        try:
            await run_notification_check()
        except Exception:
            pass


# ================== RUN ==================
async def main():
    init_db()

    # ✅ разова перевірка при старті
    try:
        await run_notification_check()
    except Exception:
        pass

    # ✅ щоденний scheduler
    asyncio.create_task(notification_scheduler())

    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
