# bot.py
# pip install aiogram==3.13.1 aiosqlite

import asyncio
import logging
import os

import aiosqlite
from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

# ==================== НАСТРОЙКИ ====================

BOT_TOKEN = os.environ["BOT_TOKEN"]
ADMIN_GROUP_ID = int(os.environ["ADMIN_GROUP_ID"])
OWNER_ID = int(os.environ["OWNER_ID"])
DB_PATH = os.environ.get("DB_PATH", "bot.db")

# ==================== ТЕКСТЫ ====================
WELCOME_TEXT = (
    "Здравствуйте!! Решили подать к нам анкету? Замечательно!!\n"
    "Только учтите, что все ответы должны быть подробно расписаны, "
    "иначе ваша кандидатура не будет рассматриваться. Удачи!!\n\n"
    "Прошу Вас перед тем, как заполнять анкету, указать, "
    "на кого вы идёте: проверяющий или интервьюер."
)

INTERVIEWER = [
    "Какого Вы пола (мужской/женский)?",
    "Сколько Вам лет?",
    "Тег, по которому Вы собираетесь работать.",
    "Ваш часовой пояс.",
    "Сколько интервью Вы сможете брать и оформлять (то бишь, выкладывать) в неделю?",
    "Насколько Вы грамотный человек?",
    "Готовы ли Вы будете принимать замечания старшей администрации?",
    "У Вас был опыт в подобной сфере (именно интервью)?",
    "Насколько Вы быстро учитесь новому?",
    "Откуда Вы узнали о нашем проекте?",
    "Сможете ли самостоятельно искать людей, у которых будет взято интервью?",
    "Сможете ли договариваться о взятии интервью?",
    "Ваш юз.",
]

CHECKER = [
    "Какого Вы пола (мужской/женский)?",
    "Сколько Вам лет?",
    "Тег, по которому Вы собираетесь работать.",
    "Ваш часовой пояс.",
    "Сколько ботов Вы сможете проверять и писать для них посты в неделю?",
    "Насколько Вы грамотный человек?",
    "Как относитесь к агрессии?",
    "Готовы ли будете принимать замечания старшей администрации?",
    "У Вас был опыт в подобной сфере (именно проверок)?",
    "Сможете ли Вы расписывать абсолютно все ошибки администраторов и проектов в постах?",
    "Если у Вас начнется конфликт с ботом, снизите ли Вы оценку за это в посте?",
    "Насколько быстро Вы учитесь новому?",
    "Откуда узнали о нашем проекте?",
    "Ваш юз.",
]

# ==================== FSM ====================
class Anketa(StatesGroup):
    choosing_role = State()
    answering = State()

class AdminPanel(StatesGroup):
    waiting_add_id = State()

# ==================== БД ====================
async def db_init():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "CREATE TABLE IF NOT EXISTS admins (user_id INTEGER PRIMARY KEY)"
        )
        # тикеты: последний месседж в группе для пользователя (thread)
        await db.execute(
            "CREATE TABLE IF NOT EXISTS tickets ("
            " user_id INTEGER PRIMARY KEY,"
            " group_msg_id INTEGER NOT NULL"
            ")"
        )
        # карта: id сообщения в группе -> user_id (для реплаев на старые сообщения)
        await db.execute(
            "CREATE TABLE IF NOT EXISTS msg_map ("
            " group_msg_id INTEGER PRIMARY KEY,"
            " user_id INTEGER NOT NULL"
            ")"
        )
        await db.commit()

async def is_admin(user_id: int) -> bool:
    if user_id == OWNER_ID:
        return True
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT 1 FROM admins WHERE user_id = ?", (user_id,))
        return await cur.fetchone() is not None

async def add_admin(user_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT OR IGNORE INTO admins (user_id) VALUES (?)", (user_id,))
        await db.commit()

async def remove_admin(user_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM admins WHERE user_id = ?", (user_id,))
        await db.commit()

async def list_admins() -> list[int]:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT user_id FROM admins ORDER BY user_id")
        return [r[0] for r in await cur.fetchall()]

async def set_ticket(user_id: int, group_msg_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO tickets (user_id, group_msg_id) VALUES (?, ?) "
            "ON CONFLICT(user_id) DO UPDATE SET group_msg_id = excluded.group_msg_id",
            (user_id, group_msg_id),
        )
        await db.execute(
            "INSERT OR REPLACE INTO msg_map (group_msg_id, user_id) VALUES (?, ?)",
            (group_msg_id, user_id),
        )
        await db.commit()

async def get_ticket_msg(user_id: int) -> int | None:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT group_msg_id FROM tickets WHERE user_id = ?", (user_id,))
        row = await cur.fetchone()
        return row[0] if row else None

async def get_user_by_msg(group_msg_id: int) -> int | None:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT user_id FROM msg_map WHERE group_msg_id = ?", (group_msg_id,))
        row = await cur.fetchone()
        return row[0] if row else None

# ==================== РОУТЕР ====================
logging.basicConfig(level=logging.INFO)
router = Router()

# ---------- /start ----------
@router.message(CommandStart())
async def start(message: Message, state: FSMContext):
    await state.clear()
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🎤 Интервьюер", callback_data="role:interviewer"),
            InlineKeyboardButton(text="🔍 Проверяющий", callback_data="role:checker"),
        ]
    ])
    await message.answer(WELCOME_TEXT, reply_markup=kb)
    await state.set_state(Anketa.choosing_role)

@router.message(Command("id"))
async def cmd_id(message: Message):
    await message.answer(f"Ваш Telegram ID: <code>{message.from_user.id}</code>")

# ---------- Админ-панель ----------
def admin_panel_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Добавить админа", callback_data="adm:add")],
        [InlineKeyboardButton(text="➖ Удалить админа", callback_data="adm:remove")],
        [InlineKeyboardButton(text="📋 Список админов", callback_data="adm:list")],
    ])

@router.message(Command("admin"))
async def cmd_admin(message: Message, state: FSMContext):
    if not await is_admin(message.from_user.id):
        await message.answer("⛔ У вас нет доступа.")
        return
    await state.clear()
    await message.answer("🛠 <b>Админ-панель</b>", reply_markup=admin_panel_kb())

@router.callback_query(F.data == "adm:list")
async def adm_list(cb: CallbackQuery):
    if not await is_admin(cb.from_user.id):
        await cb.answer("Нет доступа", show_alert=True)
        return
    admins = await list_admins()
    text = f"👑 <b>Овнер:</b> <code>{OWNER_ID}</code>\n\n"
    if admins:
        text += "👥 <b>Администраторы:</b>\n"
        for i, uid in enumerate(admins, 1):
            text += f"{i}. <code>{uid}</code>\n"
    else:
        text += "Администраторов пока нет."
    await cb.message.edit_text(text, reply_markup=admin_panel_kb())
    await cb.answer()

@router.callback_query(F.data == "adm:add")
async def adm_add_start(cb: CallbackQuery, state: FSMContext):
    if not await is_admin(cb.from_user.id):
        await cb.answer("Нет доступа", show_alert=True)
        return
    await state.set_state(AdminPanel.waiting_add_id)
    await cb.message.edit_text(
        "Отправьте <b>Telegram ID</b> нового администратора.\n"
        "Для отмены — /cancel"
    )
    await cb.answer()

@router.callback_query(F.data == "adm:remove")
async def adm_remove_start(cb: CallbackQuery, state: FSMContext):
    if not await is_admin(cb.from_user.id):
        await cb.answer("Нет доступа", show_alert=True)
        return
    admins = await list_admins()
    if not admins:
        await cb.answer("Список пуст", show_alert=True)
        return
    buttons = [[InlineKeyboardButton(text=str(uid), callback_data=f"adm:del:{uid}")]
               for uid in admins]
    buttons.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="adm:refresh")])
    await cb.message.edit_text(
        "Выберите администратора для удаления:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
    )
    await cb.answer()

@router.callback_query(F.data == "adm:refresh")
async def adm_refresh(cb: CallbackQuery):
    if not await is_admin(cb.from_user.id):
        await cb.answer("Нет доступа", show_alert=True)
        return
    await cb.message.edit_text("🛠 <b>Админ-панель</b>", reply_markup=admin_panel_kb())
    await cb.answer()

@router.callback_query(F.data.startswith("adm:del:"))
async def adm_del(cb: CallbackQuery):
    if not await is_admin(cb.from_user.id):
        await cb.answer("Нет доступа", show_alert=True)
        return
    uid = int(cb.data.split(":")[2])
    if uid == OWNER_ID:
        await cb.answer("Нельзя удалить овнера", show_alert=True)
        return
    await remove_admin(uid)
    await cb.answer(f"Админ {uid} удалён", show_alert=True)
    admins = await list_admins()
    buttons = [[InlineKeyboardButton(text=str(u), callback_data=f"adm:del:{u}")]
               for u in admins]
    buttons.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="adm:refresh")])
    await cb.message.edit_text(
        "Выберите администратора для удаления:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
    )

@router.message(AdminPanel.waiting_add_id)
async def adm_add_finish(message: Message, state: FSMContext, bot: Bot):
    if not await is_admin(message.from_user.id):
        await state.clear()
        return
    try:
        uid = int(message.text.strip())
    except ValueError:
        await message.answer("❌ Это не число. Отправьте Telegram ID.")
        return
    if uid == OWNER_ID:
        await message.answer("Это владелец, он уже есть.")
        await state.clear()
        return
    if await is_admin(uid):
        await message.answer("Пользователь уже админ.")
        await state.clear()
        return
    await add_admin(uid)
    await message.answer(f"✅ Пользователь <code>{uid}</code> назначен администратором.")
    try:
        await bot.send_message(uid, "🎉 Вы назначены администратором!")
    except Exception:
        pass
    await state.clear()

@router.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("Отменено.")

# ---------- Анкета ----------
@router.callback_query(Anketa.choosing_role, F.data.startswith("role:"))
async def choose_role(callback: CallbackQuery, state: FSMContext):
    role = callback.data.split(":")[1]
    if role == "interviewer":
        title, questions = "АНКЕТА НА ИНТЕРВЬЮЕРА", INTERVIEWER
    else:
        title, questions = "АНКЕТА НА ПРОВЕРЯЮЩЕГО", CHECKER

    await state.update_data(role=role, title=title, questions=questions, index=0, answers=[])
    await state.set_state(Anketa.answering)
    await callback.message.edit_text(
        f"📋 <b>{title}</b>\n\n<b>Вопрос 1/{len(questions)}</b>\n{questions[0]}"
    )
    await callback.answer()

@router.message(Anketa.answering, F.text)
async def handle_answer(message: Message, state: FSMContext, bot: Bot):
    data = await state.get_data()
    questions: list[str] = data["questions"]
    index: int = data["index"]
    answers: list[tuple[str, str]] = data["answers"]

    answers.append((questions[index], message.text))
    index += 1

    if index < len(questions):
        await state.update_data(index=index, answers=answers)
        await message.answer(
            f"<b>Вопрос {index + 1}/{len(questions)}</b>\n{questions[index]}"
        )
        return

    await send_anketa(bot, message, data, answers)
    await state.clear()

async def send_anketa(bot: Bot, message: Message, data: dict, answers):
    role_ru = "Интервьюер" if data["role"] == "interviewer" else "Проверяющий"
    header = (
        f"<b>📥 Новая анкета: {role_ru}</b>\n"
        f"👤 От: {message.from_user.full_name} "
        f"(<code>{message.from_user.id}</code>)\n"
        f"🔗 @{message.from_user.username or 'нет'}\n"
        f"➖➖➖➖➖➖➖➖➖➖\n"
    )
    body = ""
    for i, (q, a) in enumerate(answers, start=1):
        body += f"<b>{i}. {q}</b>\n{a}\n\n"

    full = header + body
    chunks = [full[i:i + 4000] for i in range(0, len(full), 4000)]

    last_sent = None
    for chunk in chunks:
        last_sent = await bot.send_message(ADMIN_GROUP_ID, chunk)

    if last_sent:
        await set_ticket(message.from_user.id, last_sent.message_id)

    await message.answer(
        "✅ Ваша анкета отправлена администрации. "
        "Можете задавать вопросы — ответ придёт сюда."
    )

# ---------- Реплай админа в группе ----------
# ВАЖНО: этот хендлер работает ТОЛЬКО в группе и при наличии реплая.
# Мы молча копируем сообщение пользователю, БЕЗ подтверждений.
@router.message(F.chat.id == ADMIN_GROUP_ID, F.reply_to_message)
async def admin_reply(message: Message, bot: Bot):
    if not await is_admin(message.from_user.id):
        return

    # на какое сообщение ответили — по нему ищем пользователя
    target_msg_id = message.reply_to_message.message_id
    user_id = await get_user_by_msg(target_msg_id)

    if not user_id:
        # возможно, ответ на сообщение, которого нет в мапе — пробуем тикет
        # (не сработает без явного сопоставления, но оставим для надёжности)
        return

    try:
        copied = await bot.copy_message(
            chat_id=user_id,
            from_chat_id=message.chat.id,
            message_id=message.message_id,
        )
        # регистрируем новое сообщение в треде — чтобы пользователь мог
        # ответить реплаем и попасть обратно в группу
        await set_ticket(user_id, message.message_id)
        # привязываем скопированное сообщение в ЛС к пользователю —
        # на случай если админ захочет ответить на исходник в группе ещё раз
    except Exception as e:
        logging.warning(f"copy to user failed: {e}")

# ---------- Пользователь пишет боту вне анкеты ----------
# Всё, что не /start, не /admin, не анкета — уходит в группу реплаем на тред
@router.message(F.chat.type == "private")
async def user_message(message: Message, state: FSMContext, bot: Bot):
    current = await state.get_state()
    # если пользователь в процессе анкеты — этот хендлер не должен сработать,
    # но на всякий случай проверим
    if current is not None:
        return

    user_id = message.from_user.id
    thread_msg = await get_ticket_msg(user_id)

    header = (
        f"👤 <b>{message.from_user.full_name}</b> "
        f"(<code>{user_id}</code>, @{message.from_user.username or 'нет'}):"
    )

    if thread_msg:
        # отвечаем реплаем на существующий тред
        try:
            sent = await bot.copy_message(
                chat_id=ADMIN_GROUP_ID,
                from_chat_id=message.chat.id,
                message_id=message.message_id,
                reply_to_message_id=thread_msg,
            )
            await set_ticket(user_id, sent.message_id)
            return
        except Exception:
            # если исходное сообщение удалено — создаём новый тред
            pass

    # новый тред: отправляем текст с заголовком
    text = message.text or message.caption or "<i>(вложение)</i>"
    sent = await bot.send_message(
        ADMIN_GROUP_ID,
        f"{header}\n\n{text}",
    )
    await set_ticket(user_id, sent.message_id)

# ---------- /id в группе по реплаю ----------
@router.message(Command("id"), F.reply_to_message)
async def cmd_id_reply(message: Message):
    target = message.reply_to_message.from_user
    await message.reply(
        f"ID пользователя {target.full_name}: <code>{target.id}</code>"
    )

# ==================== ЗАПУСК ====================
async def main():
    await db_init()
    bot = Bot(BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(router)
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())