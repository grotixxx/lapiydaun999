import asyncio
import sqlite3
import os
from typing import Any, Dict, List, Optional

from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart, Command
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder

# ================== НАЛАШТУВАННЯ ==================
ADMIN_BOT_TOKEN = "8572013690:AAHr_0H494MCsKhXy9GNNoh89ezmWk4C_PE"
CLIENT_BOT_TOKEN = "8348906081:AAFdGlSs21FDj757b0TfHM81GV5h_V9Ffps"

ADMIN_IDS = {800055308}

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bot.db")

admin_bot = Bot(token=ADMIN_BOT_TOKEN)
notify_bot = Bot(token=CLIENT_BOT_TOKEN)  # бот, який пише клієнтам
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
    elif not phone.startswith("+") and phone:
        phone = "+" + phone
    return phone

# ================== DB ==================
def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

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

    cur.execute("""
    CREATE TABLE IF NOT EXISTS ClientLinks (
        user_id INTEGER PRIMARY KEY,
        phone TEXT UNIQUE,
        chat_id INTEGER NOT NULL
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

def find_clients_by_code(code: int) -> List[Dict[str, Any]]:
    return fetch_all("SELECT * FROM Table1 WHERE Код=?", (code,))

def find_clients_by_phone(phone: str) -> List[Dict[str, Any]]:
    phone = normalize_phone(phone)
    # пробуємо і нормалізований, і без '+', і 0...
    vars_ = {phone}
    if phone.startswith("+"):
        vars_.add(phone[1:])
    if phone.startswith("+380"):
        vars_.add("0" + phone[4:])
    placeholders = " OR ".join(["Номер=?"] * len(vars_))
    query = f"SELECT * FROM Table1 WHERE {placeholders}"
    return fetch_all(query, tuple(vars_))

def find_client_by_id(row_id: int) -> Optional[Dict[str, Any]]:
    return fetch_one("SELECT * FROM Table1 WHERE ID=?", (row_id,))

def get_all_clients() -> List[Dict[str, Any]]:
    return fetch_all("SELECT * FROM Table1 ORDER BY ID DESC")

def insert_client(data: Dict[str, Any]) -> int:
    phone = normalize_phone(data.get("Номер") or "")
    execute("""
        INSERT INTO Table1 (
            Код, ПІБ_Клієнта, Тип_Послуги, Куплено_Сеансів, Використано_Сеансів,
            Дата_Завершення, Сума_курсу, Номер, Дата_Візиту
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        data.get("Код"),
        data.get("ПІБ_Клієнта"),
        data.get("Тип_Послуги"),
        data.get("Куплено_Сеансів"),
        data.get("Використано_Сеансів"),
        data.get("Дата_Завершення"),
        data.get("Сума_курсу"),
        phone,
        data.get("Дата_Візиту"),
    ))
    row = fetch_one("SELECT ID FROM Table1 ORDER BY ID DESC LIMIT 1")
    return int(row["ID"]) if row else 0

def update_field(row_id: int, field: str, value: Any) -> None:
    allowed = {
        "Код", "ПІБ_Клієнта", "Тип_Послуги", "Куплено_Сеансів", "Використано_Сеансів",
        "Дата_Завершення", "Сума_курсу", "Номер", "Дата_Візиту"
    }
    if field not in allowed:
        raise ValueError("Поле не дозволено")

    if field == "Номер" and value is not None:
        value = normalize_phone(str(value))

    execute(f"UPDATE Table1 SET {field}=? WHERE ID=?", (value, row_id))

def delete_client(row_id: int) -> None:
    execute("DELETE FROM Table1 WHERE ID=?", (row_id,))

def get_chat_id_by_phone(phone: str) -> Optional[int]:
    phone = normalize_phone(phone)
    row = fetch_one("SELECT chat_id FROM ClientLinks WHERE phone=?", (phone,))
    if row:
        return int(row["chat_id"])
    # на всякий — спроба без '+'
    if phone.startswith("+"):
        row2 = fetch_one("SELECT chat_id FROM ClientLinks WHERE phone=?", (phone[1:],))
        return int(row2["chat_id"]) if row2 else None
    return None

# ================== FORMAT ==================
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

def fmt_client(c: Dict[str, Any]) -> str:
    return (
        f"🆔 ID: {c.get('ID')}\n"
        f"🔢 Код: {c.get('Код')}\n"
        f"👤 ПІБ: {c.get('ПІБ_Клієнта')}\n"
        f"📌 Послуга: {c.get('Тип_Послуги')}\n"
        f"🎟 Куплено: {c.get('Куплено_Сеансів')}\n"
        f"✔️ Використано: {c.get('Використано_Сеансів')}\n"
        f"📅 Завершення: {c.get('Дата_Завершення')}\n"
        f"💰 Сума: {format_money(c.get('Сума_курсу'))}\n"
        f"📱 Номер: {c.get('Номер')}\n"
        f"🗓 Візит: {c.get('Дата_Візиту')}\n"
    )

# ================== ACCESS ==================
def is_admin_message(message: types.Message) -> bool:
    return message.from_user and message.from_user.id in ADMIN_IDS

def is_admin_call(call: types.CallbackQuery) -> bool:
    return call.from_user and call.from_user.id in ADMIN_IDS

# ================== NOTIFY ==================
async def notify_client(client_row: Optional[Dict[str, Any]], title: str):
    if not client_row:
        return
    phone = client_row.get("Номер")
    if not phone:
        return
    chat_id = get_chat_id_by_phone(phone)
    if not chat_id:
        return

    try:
        await notify_bot.send_message(
            chat_id,
            f"🔔 {title}\n\n{fmt_client(client_row)}"
        )
    except Exception:
        # клієнт міг заблокувати бота тощо
        pass

# ================== FSM ==================
class AddClient(StatesGroup):
    code = State()
    name = State()
    service = State()
    bought = State()
    used = State()
    end_date = State()
    sum_course = State()
    phone = State()
    visit_date = State()

class SearchClient(StatesGroup):
    query = State()

class EditClient(StatesGroup):
    query = State()
    choose_record = State()
    choose_field = State()
    input_value = State()

class DeleteClientFSM(StatesGroup):
    query = State()
    choose_record = State()
    confirm = State()

# ================== UI ==================
def main_menu_kb() -> types.ReplyKeyboardMarkup:
    kb = ReplyKeyboardBuilder()
    kb.button(text="➕ Додати клієнта")
    kb.button(text="🔎 Знайти клієнта")
    kb.button(text="✏️ Редагувати клієнта")
    kb.button(text="🗑 Видалити клієнта")
    kb.button(text="📋 Список усіх клієнтів")
    kb.button(text="🏠 Меню")
    kb.adjust(2, 2, 2)
    return kb.as_markup(resize_keyboard=True)

def cancel_kb() -> types.ReplyKeyboardMarkup:
    kb = ReplyKeyboardBuilder()
    kb.button(text="❌ Скасувати")
    kb.button(text="🏠 Меню")
    kb.adjust(2)
    return kb.as_markup(resize_keyboard=True)

def service_kb_add() -> types.ReplyKeyboardMarkup:
    kb = ReplyKeyboardBuilder()
    kb.button(text="🎁 Сертифікат")
    kb.button(text="🎓 Курси")
    kb.button(text="🏠 Меню")
    kb.adjust(2, 1)
    return kb.as_markup(resize_keyboard=True)

def records_kb(rows: List[Dict[str, Any]], action: str) -> types.InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for r in rows:
        title = f"ID {r['ID']} | Код {r.get('Код')} | {r.get('ПІБ_Клієнта')}"
        kb.button(text=title, callback_data=f"{action}:{r['ID']}")
    kb.adjust(1)
    return kb.as_markup()

def fields_kb() -> types.InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    fields = [
        ("🔢 Код", "Код"),
        ("👤 ПІБ", "ПІБ_Клієнта"),
        ("📌 Послуга", "Тип_Послуги"),
        ("🎟 Куплено", "Куплено_Сеансів"),
        ("✔️ Використано", "Використано_Сеансів"),
        ("📅 Завершення", "Дата_Завершення"),
        ("💰 Сума", "Сума_курсу"),
        ("📱 Номер", "Номер"),
        ("🗓 Візит", "Дата_Візиту"),
    ]
    for title, f in fields:
        kb.button(text=title, callback_data=f"edit_field:{f}")
    kb.button(text="✅ Готово", callback_data="edit_done")
    kb.adjust(3, 3, 3, 1)
    return kb.as_markup()

def yes_no_kb() -> types.InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="✅ Так", callback_data="del_confirm:yes")
    kb.button(text="❌ Ні", callback_data="del_confirm:no")
    kb.adjust(2)
    return kb.as_markup()

def client_actions_kb(row_id: int) -> types.InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="✏️ Редагувати", callback_data=f"edit_select:{row_id}")
    kb.button(text="🗑 Видалити", callback_data=f"del_select:{row_id}")
    kb.adjust(2)
    return kb.as_markup()

def service_inline_kb_edit() -> types.InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="🎁 Сертифікат", callback_data="edit_service:Сертифікат")
    kb.button(text="🎓 Курс", callback_data="edit_service:Курс")
    kb.adjust(2)
    return kb.as_markup()

# ================== GLOBAL MENU ==================
@dp.message(F.text == "🏠 Меню")
async def go_menu(message: types.Message, state: FSMContext):
    if not is_admin_message(message):
        await message.answer("⛔ Доступ заборонено.")
        return
    await state.clear()
    await message.answer("🏠 Головне меню:", reply_markup=main_menu_kb())

@dp.message(CommandStart())
async def start(message: types.Message):
    init_db()
    if not is_admin_message(message):
        await message.answer("⛔ Доступ заборонено.")
        return
    await message.answer("👋 Адмін-панель. Оберіть дію:", reply_markup=main_menu_kb())

@dp.message(Command("cancel"))
@dp.message(F.text == "❌ Скасувати")
async def cancel(message: types.Message, state: FSMContext):
    if not is_admin_message(message):
        return
    await state.clear()
    await message.answer("Скасовано.", reply_markup=main_menu_kb())

# ================== LIST ALL ==================
@dp.message(F.text == "📋 Список усіх клієнтів")
async def list_all_clients(message: types.Message):
    if not is_admin_message(message):
        return
    clients = get_all_clients()
    if not clients:
        await message.answer("📭 База порожня.")
        return
    text = "📋 Усі клієнти:\n\n"
    for c in clients:
        text += fmt_client(c) + "\n━━━━━━━━━━━━━━\n"
    chunk = 3500
    for i in range(0, len(text), chunk):
        await message.answer(text[i:i + chunk])

# ================== SEARCH (VIEW) ==================
@dp.message(F.text == "🔎 Знайти клієнта")
async def search_start(message: types.Message, state: FSMContext):
    if not is_admin_message(message):
        return
    await state.set_state(SearchClient.query)
    await message.answer("Введіть код або номер телефону:", reply_markup=cancel_kb())

@dp.message(SearchClient.query)
async def search_do(message: types.Message, state: FSMContext):
    if not is_admin_message(message):
        return
    q = message.text.strip()
    rows: List[Dict[str, Any]] = []
    if q.isdigit():
        rows = find_clients_by_code(int(q))
    if not rows:
        rows = find_clients_by_phone(q)

    if not rows:
        await message.answer("❌ Не знайдено. Спробуйте ще раз або Скасувати/Меню.")
        return

    await message.answer(
        f"✅ Знайдено записів: {len(rows)}\n"
        "Натисніть ✏️ Редагувати (вводити код вдруге не потрібно).",
        reply_markup=main_menu_kb()
    )
    for r in rows:
        await message.answer(fmt_client(r), reply_markup=client_actions_kb(r["ID"]))
    await state.clear()

# ================== ADD ==================
@dp.message(F.text == "➕ Додати клієнта")
async def add_start(message: types.Message, state: FSMContext):
    if not is_admin_message(message):
        return
    await state.clear()
    await state.set_state(AddClient.code)
    await message.answer("Введіть КОД (число):", reply_markup=cancel_kb())

@dp.message(AddClient.code)
async def add_code(message: types.Message, state: FSMContext):
    if not is_admin_message(message):
        return
    t = message.text.strip()
    if not t.isdigit():
        await message.answer("Код має бути числом. Введіть ще раз:")
        return
    await state.update_data(Код=int(t))
    await state.set_state(AddClient.name)
    await message.answer("Введіть ПІБ клієнта:", reply_markup=cancel_kb())

@dp.message(AddClient.name)
async def add_name(message: types.Message, state: FSMContext):
    if not is_admin_message(message):
        return
    await state.update_data(ПІБ_Клієнта=message.text.strip())
    await state.set_state(AddClient.service)
    await message.answer("Оберіть тип послуги:", reply_markup=service_kb_add())

@dp.message(AddClient.service)
async def add_service(message: types.Message, state: FSMContext):
    if not is_admin_message(message):
        return
    text = message.text.strip()
    if text not in ["🎁 Сертифікат", "🎓 Курси"]:
        await message.answer("Будь ласка, оберіть кнопку (або Меню).")
        return
    service_type = "Сертифікат" if "Сертифікат" in text else "Курси"
    await state.update_data(Тип_Послуги=service_type)
    await state.set_state(AddClient.bought)
    await message.answer("Куплено сеансів (число):", reply_markup=cancel_kb())

@dp.message(AddClient.bought)
async def add_bought(message: types.Message, state: FSMContext):
    if not is_admin_message(message):
        return
    t = message.text.strip()
    if not t.isdigit():
        await message.answer("Потрібне число. Введіть ще раз:")
        return
    await state.update_data(Куплено_Сеансів=int(t))
    await state.set_state(AddClient.used)
    await message.answer("Використано сеансів (число):", reply_markup=cancel_kb())

@dp.message(AddClient.used)
async def add_used(message: types.Message, state: FSMContext):
    if not is_admin_message(message):
        return
    t = message.text.strip()
    if not t.isdigit():
        await message.answer("Потрібне число. Введіть ще раз:")
        return
    await state.update_data(Використано_Сеансів=int(t))
    await state.set_state(AddClient.end_date)
    await message.answer("Дата завершення (напр. 01.01.2026) або '-' якщо немає:", reply_markup=cancel_kb())

@dp.message(AddClient.end_date)
async def add_end_date(message: types.Message, state: FSMContext):
    if not is_admin_message(message):
        return
    val = message.text.strip()
    await state.update_data(Дата_Завершення=None if val == "-" else val)
    await state.set_state(AddClient.sum_course)
    await message.answer("Сума курсу (число, можна 0):", reply_markup=cancel_kb())

@dp.message(AddClient.sum_course)
async def add_sum(message: types.Message, state: FSMContext):
    if not is_admin_message(message):
        return
    t = message.text.strip().replace(",", ".")
    try:
        value = float(t)
    except Exception:
        await message.answer("Потрібне число. Введіть ще раз:")
        return
    await state.update_data(Сума_курсу=value)
    await state.set_state(AddClient.phone)
    await message.answer("Номер телефону (напр. +380... або 0...):", reply_markup=cancel_kb())

@dp.message(AddClient.phone)
async def add_phone(message: types.Message, state: FSMContext):
    if not is_admin_message(message):
        return
    phone = normalize_phone(message.text.strip())
    await state.update_data(Номер=phone)
    await state.set_state(AddClient.visit_date)
    await message.answer("Дата візиту (напр. 01.01.2026) або '-' якщо немає:", reply_markup=cancel_kb())

@dp.message(AddClient.visit_date)
async def add_visit(message: types.Message, state: FSMContext):
    if not is_admin_message(message):
        return
    val = message.text.strip()
    await state.update_data(Дата_Візиту=None if val == "-" else val)

    data = await state.get_data()
    new_id = insert_client(data)
    created = find_client_by_id(new_id) if new_id else None

    await notify_client(created, "Ваші дані додано/оновлено адміністратором")

    await state.clear()
    await message.answer("✅ Клієнта додано.", reply_markup=main_menu_kb())

# ================== EDIT ==================
@dp.message(F.text == "✏️ Редагувати клієнта")
async def edit_start(message: types.Message, state: FSMContext):
    if not is_admin_message(message):
        return
    await state.clear()
    await state.set_state(EditClient.query)
    await message.answer("Введіть код або телефон для пошуку клієнта:", reply_markup=cancel_kb())

@dp.message(EditClient.query)
async def edit_search(message: types.Message, state: FSMContext):
    if not is_admin_message(message):
        return
    q = message.text.strip()
    rows: List[Dict[str, Any]] = []
    if q.isdigit():
        rows = find_clients_by_code(int(q))
    if not rows:
        rows = find_clients_by_phone(q)

    if not rows:
        await message.answer("❌ Не знайдено. Спробуйте ще раз або Меню.")
        return

    await state.set_state(EditClient.choose_record)
    await message.answer("Оберіть запис для редагування:", reply_markup=records_kb(rows, "edit_select"))

@dp.callback_query(F.data.startswith("edit_select:"))
async def edit_select_record(call: types.CallbackQuery, state: FSMContext):
    if not is_admin_call(call):
        await call.answer("⛔ Немає доступу", show_alert=True)
        return
    row_id = int(call.data.split(":")[1])
    c = find_client_by_id(row_id)
    if not c:
        await call.message.edit_text("Запис не знайдено.")
        await call.answer()
        return
    await state.update_data(row_id=row_id)
    await state.set_state(EditClient.choose_field)
    await call.message.edit_text(
        "Поточні дані:\n\n"
        f"{fmt_client(c)}\n"
        "Оберіть поле для зміни:",
        reply_markup=fields_kb()
    )
    await call.answer()

@dp.callback_query(F.data.startswith("edit_field:"))
async def edit_choose_field(call: types.CallbackQuery, state: FSMContext):
    if not is_admin_call(call):
        await call.answer("⛔ Немає доступу", show_alert=True)
        return

    field = call.data.split(":", 1)[1]
    await state.update_data(field=field)

    # послуга — кнопки
    if field == "Тип_Послуги":
        await state.set_state(EditClient.choose_field)
        await call.message.edit_text("Оберіть нову послугу:", reply_markup=service_inline_kb_edit())
        await call.answer()
        return

    await state.set_state(EditClient.input_value)
    await call.message.edit_text(
        f"Введіть нове значення для поля: {field}\n"
        "Підказка: для чисел введіть число, для порожнього значення введіть '-'"
    )
    await call.answer()

@dp.callback_query(F.data.startswith("edit_service:"))
async def edit_service_apply(call: types.CallbackQuery, state: FSMContext):
    if not is_admin_call(call):
        await call.answer("⛔ Немає доступу", show_alert=True)
        return
    service_value = call.data.split(":", 1)[1]
    data = await state.get_data()
    row_id = data.get("row_id")
    if not row_id:
        await call.message.answer("Клієнта не обрано. Почніть заново.", reply_markup=main_menu_kb())
        await state.clear()
        await call.answer()
        return

    update_field(row_id, "Тип_Послуги", service_value)
    c = find_client_by_id(row_id)
    await notify_client(c, "Ваші дані оновлено адміністратором")

    await state.set_state(EditClient.choose_field)
    await call.message.edit_text(
        "✅ Оновлено.\n\n"
        "Поточні дані:\n\n"
        + (fmt_client(c) if c else "Запис не знайдено.")
        + "\nОберіть наступне поле (або ✅ Готово):",
        reply_markup=fields_kb()
    )
    await call.answer("Оновлено")

@dp.callback_query(F.data == "edit_done")
async def edit_done(call: types.CallbackQuery, state: FSMContext):
    if not is_admin_call(call):
        await call.answer("⛔ Немає доступу", show_alert=True)
        return
    await state.clear()
    await call.message.answer("✅ Готово. Повертаю в меню:", reply_markup=main_menu_kb())
    await call.answer()

@dp.message(EditClient.input_value)
async def edit_apply(message: types.Message, state: FSMContext):
    if not is_admin_message(message):
        return
    data = await state.get_data()
    row_id = data.get("row_id")
    field = data.get("field")
    if not row_id or not field:
        await message.answer("Щось пішло не так. Почніть заново.", reply_markup=main_menu_kb())
        await state.clear()
        return

    raw = message.text.strip()
    value: Any = None if raw == "-" else raw

    if field in {"Код", "Куплено_Сеансів", "Використано_Сеансів"} and value is not None:
        if not str(value).isdigit():
            await message.answer("Потрібне ціле число. Введіть ще раз:")
            return
        value = int(value)

    if field == "Сума_курсу" and value is not None:
        try:
            value = float(str(value).replace(",", "."))
        except Exception:
            await message.answer("Потрібне число (напр. 1500 або 1500.50). Введіть ще раз:")
            return

    if field == "Номер" and value is not None:
        value = normalize_phone(str(value))

    update_field(row_id, field, value)
    c = find_client_by_id(row_id)
    await notify_client(c, "Ваші дані оновлено адміністратором")

    await state.set_state(EditClient.choose_field)
    await message.answer(
        "✅ Оновлено.\n\n"
        "Поточні дані:\n\n"
        + (fmt_client(c) if c else "Запис не знайдено.")
        + "\nОберіть наступне поле (або ✅ Готово):"
    )
    await message.answer("Поля:", reply_markup=fields_kb())

# ================== DELETE ==================
@dp.message(F.text == "🗑 Видалити клієнта")
async def del_start(message: types.Message, state: FSMContext):
    if not is_admin_message(message):
        return
    await state.clear()
    await state.set_state(DeleteClientFSM.query)
    await message.answer("Введіть код або телефон для пошуку клієнта на видалення:", reply_markup=cancel_kb())

@dp.message(DeleteClientFSM.query)
async def del_search(message: types.Message, state: FSMContext):
    if not is_admin_message(message):
        return

    q = message.text.strip()
    rows: List[Dict[str, Any]] = []
    if q.isdigit():
        rows = find_clients_by_code(int(q))
    if not rows:
        rows = find_clients_by_phone(q)

    if not rows:
        await message.answer("❌ Не знайдено. Спробуйте ще раз або Меню.")
        return

    await state.set_state(DeleteClientFSM.choose_record)
    await message.answer("Оберіть запис для видалення:", reply_markup=records_kb(rows, "del_select"))

@dp.callback_query(F.data.startswith("del_select:"))
async def del_select(call: types.CallbackQuery, state: FSMContext):
    if not is_admin_call(call):
        await call.answer("⛔ Немає доступу", show_alert=True)
        return

    row_id = int(call.data.split(":")[1])
    c = find_client_by_id(row_id)
    if not c:
        await call.message.edit_text("Запис не знайдено.")
        await call.answer()
        return

    await state.update_data(row_id=row_id)
    await state.set_state(DeleteClientFSM.confirm)
    await call.message.edit_text(
        "⚠️ Ви впевнені, що хочете видалити?\n\n" + fmt_client(c),
        reply_markup=yes_no_kb()
    )
    await call.answer()

@dp.callback_query(F.data.startswith("del_confirm:"))
async def del_confirm(call: types.CallbackQuery, state: FSMContext):
    if not is_admin_call(call):
        await call.answer("⛔ Немає доступу", show_alert=True)
        return

    choice = call.data.split(":", 1)[1]
    data = await state.get_data()
    row_id = data.get("row_id")

    client_before = find_client_by_id(row_id) if row_id else None

    if choice == "yes" and row_id:
        delete_client(row_id)
        await call.message.edit_text("✅ Видалено.")
        await notify_client(client_before, "Ваш запис видалено адміністратором")
    else:
        await call.message.edit_text("❎ Скасовано.")

    await state.clear()
    await call.message.answer("Меню:", reply_markup=main_menu_kb())
    await call.answer()

# ================== RUN ==================
async def main():
    init_db()
    await dp.start_polling(admin_bot)

if __name__ == "__main__":
    asyncio.run(main())
