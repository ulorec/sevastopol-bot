"""
Прототип телеграм-бота "Найдётся компания" — Севастополь
Простой бот для поиска компании по интересам в 6 категориях.

УСТАНОВКА:
1. pip install aiogram==3.4.1
2. Получи токен у @BotFather в Telegram (команда /newbot)
3. Вставь токен в переменную BOT_TOKEN ниже
4. Запусти: python bot.py

Это прототип: все данные хранятся в памяти (в списке Python).
При перезапуске бота все объявления удаляются.
Для постоянного хранения позже можно добавить базу данных (SQLite).
"""

import asyncio
import logging
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command, CommandObject
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage

# ====== НАСТРОЙКИ ======
import os

# На хостинге (Railway) токен и ID задаются через переменные окружения —
# это безопаснее, чем хранить их прямо в коде.
# Для запуска на своём компьютере можно временно вписать значения прямо тут.
BOT_TOKEN = os.environ.get("BOT_TOKEN", "ВСТАВЬ_СЮДА_СВОЙ_ТОКЕН")
ADMIN_ID = int(os.environ.get("ADMIN_ID", "123456789"))  # узнать свой ID у @userinfobot

# Время ежедневной рассылки мероприятий (по 24-часовому формату, час и минута)
BROADCAST_HOUR = 9
BROADCAST_MINUTE = 0

logging.basicConfig(level=logging.INFO)

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

# ====== КАТЕГОРИИ ======
CATEGORIES = {
    "sport": "🏃 Спорт",
    "study": "📚 Учёба",
    "psych": "💬 Психологические встречи",
    "business": "💼 Бизнес и нетворкинг",
    "creative": "🎨 Творчество и хобби",
    "volunteer": "🌱 Волонтёрство и экология",
}

# ====== ХРАНИЛИЩЕ ОБЪЯВЛЕНИЙ (в памяти, для прототипа) ======
# Структура: список словарей
# {"id": int, "user_id": int, "username": str, "category": str, "text": str, "district": str}
listings = []
next_id = 1

# ====== ХРАНИЛИЩЕ МЕРОПРИЯТИЙ ======
# Структура: {"id": int, "text": str, "attendees": [user_id, ...]}
today_events = []
tomorrow_events = []
next_event_id = 1

# ====== ВСЕ ПОЛЬЗОВАТЕЛИ БОТА (для рассылки) ======
known_users = set()


# ====== СОСТОЯНИЯ ДЛЯ СОЗДАНИЯ ОБЪЯВЛЕНИЯ ======
class CreateListing(StatesGroup):
    choosing_category = State()
    entering_district = State()
    entering_text = State()


# ====== СОСТОЯНИЕ ДЛЯ РЕДАКТИРОВАНИЯ ОБЪЯВЛЕНИЯ ======
class EditListing(StatesGroup):
    entering_new_text = State()


# ====== СОСТОЯНИЕ ДЛЯ ОТКЛИКА С СООБЩЕНИЕМ ======
class RespondToListing(StatesGroup):
    entering_message = State()


# ====== КЛАВИАТУРЫ ======
def main_menu_kb():
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Создать объявление", callback_data="create")],
        [InlineKeyboardButton(text="🔍 Смотреть объявления", callback_data="browse")],
        [InlineKeyboardButton(text="📝 Мои объявления", callback_data="my_listings")],
        [InlineKeyboardButton(text="📅 Мероприятия сегодня", callback_data="today_events")],
        [InlineKeyboardButton(text="🗓 Мероприятия завтра", callback_data="tomorrow_events")],
    ])
    return kb


def event_kb(event_id: int):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🙋 Я пойду!", callback_data=f"join_event_{event_id}")]
    ])
    return kb


def my_listing_actions_kb(listing_id: int):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✏️ Редактировать", callback_data=f"edit_{listing_id}")],
        [InlineKeyboardButton(text="🗑 Удалить", callback_data=f"delete_{listing_id}")],
    ])
    return kb


def categories_kb(prefix: str):
    buttons = []
    for key, label in CATEGORIES.items():
        buttons.append([InlineKeyboardButton(text=label, callback_data=f"{prefix}_{key}")])
    buttons.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_menu")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def respond_kb(listing_id: int):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✋ Откликнуться", callback_data=f"respond_{listing_id}")]
    ])
    return kb


# ====== ХЕНДЛЕРЫ ======

@dp.message(Command("start"))
async def cmd_start(message: Message):
    known_users.add(message.from_user.id)
    text = (
        "👋 Привет! Это бот «Найдётся компания» для жителей Севастополя.\n\n"
        "Здесь можно найти людей со схожими интересами в разных сферах жизни: "
        "спорт, учёба, психологическая поддержка, бизнес, творчество, волонтёрство.\n\n"
        "Выбери, что хочешь сделать:"
    )
    await message.answer(text, reply_markup=main_menu_kb())


@dp.callback_query(F.data == "back_to_menu")
async def back_to_menu(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text("Выбери, что хочешь сделать:", reply_markup=main_menu_kb())


# ----- Создание объявления -----

@dp.callback_query(F.data == "create")
async def start_create(callback: CallbackQuery, state: FSMContext):
    await state.set_state(CreateListing.choosing_category)
    await callback.message.edit_text(
        "В каком разделе создать объявление?",
        reply_markup=categories_kb("cat")
    )


@dp.callback_query(F.data.startswith("cat_"), CreateListing.choosing_category)
async def category_chosen(callback: CallbackQuery, state: FSMContext):
    category_key = callback.data.replace("cat_", "")
    await state.update_data(category=category_key)
    await state.set_state(CreateListing.entering_district)
    await callback.message.edit_text(
        f"Раздел: {CATEGORIES[category_key]}\n\n"
        "В каком районе/части города удобно встретиться? "
        "(например: центр, Гагаринский район, Балаклава)\n"
        "Напиши текстом:"
    )


@dp.message(CreateListing.entering_district)
async def district_entered(message: Message, state: FSMContext):
    await state.update_data(district=message.text)
    await state.set_state(CreateListing.entering_text)
    await message.answer(
        "Теперь опиши, что именно ищешь — например:\n"
        "«Ищу партнёра для утренних пробежек по набережной, 3 раза в неделю»\n\n"
        "Напиши текстом:"
    )


@dp.message(CreateListing.entering_text)
async def text_entered(message: Message, state: FSMContext):
    global next_id
    data = await state.get_data()
    listing = {
        "id": next_id,
        "user_id": message.from_user.id,
        "username": message.from_user.username or message.from_user.first_name,
        "category": data["category"],
        "district": data["district"],
        "text": message.text,
    }
    listings.append(listing)
    next_id += 1

    await state.clear()
    await message.answer(
        f"✅ Объявление создано в разделе {CATEGORIES[listing['category']]}!\n\n"
        "Другие жители города теперь смогут его увидеть и откликнуться.",
        reply_markup=main_menu_kb()
    )


# ----- Мои объявления (просмотр, редактирование, удаление) -----

@dp.callback_query(F.data == "my_listings")
async def show_my_listings(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    user_listings = [l for l in listings if l["user_id"] == callback.from_user.id]

    if not user_listings:
        await callback.message.edit_text(
            "У тебя пока нет объявлений.",
            reply_markup=main_menu_kb()
        )
        return

    await callback.message.edit_text("Твои объявления:")

    for listing in user_listings:
        text = (
            f"{CATEGORIES[listing['category']]}\n"
            f"📍 Район: {listing['district']}\n"
            f"📝 {listing['text']}"
        )
        await callback.message.answer(text, reply_markup=my_listing_actions_kb(listing["id"]))

    await callback.message.answer("⬆️ Это все твои объявления.", reply_markup=main_menu_kb())


@dp.callback_query(F.data.startswith("delete_"))
async def delete_listing(callback: CallbackQuery):
    listing_id = int(callback.data.replace("delete_", ""))
    listing = next((l for l in listings if l["id"] == listing_id), None)

    if not listing or listing["user_id"] != callback.from_user.id:
        await callback.answer("Не получилось удалить это объявление.", show_alert=True)
        return

    listings.remove(listing)
    await callback.message.edit_text("🗑 Объявление удалено.")
    await callback.message.answer("Выбери, что хочешь сделать:", reply_markup=main_menu_kb())


@dp.callback_query(F.data.startswith("edit_"))
async def start_edit_listing(callback: CallbackQuery, state: FSMContext):
    listing_id = int(callback.data.replace("edit_", ""))
    listing = next((l for l in listings if l["id"] == listing_id), None)

    if not listing or listing["user_id"] != callback.from_user.id:
        await callback.answer("Не получилось отредактировать это объявление.", show_alert=True)
        return

    await state.set_state(EditListing.entering_new_text)
    await state.update_data(listing_id=listing_id)
    await callback.message.answer(
        "Напиши новый текст объявления (район менять не нужно, можно повторить старый текст с изменениями):"
    )


@dp.message(EditListing.entering_new_text)
async def finish_edit_listing(message: Message, state: FSMContext):
    data = await state.get_data()
    listing = next((l for l in listings if l["id"] == data["listing_id"]), None)

    if listing:
        listing["text"] = message.text
        await message.answer("✅ Объявление обновлено!", reply_markup=main_menu_kb())
    else:
        await message.answer("Не получилось найти объявление для обновления.", reply_markup=main_menu_kb())

    await state.clear()


# ----- Мероприятия: добавление админом -----

@dp.message(Command("add_today"))
async def add_today_event(message: Message, command: CommandObject):
    global next_event_id
    if message.from_user.id != ADMIN_ID:
        await message.answer("Эта команда доступна только администратору.")
        return
    if not command.args:
        await message.answer("Использование: /add_today текст мероприятия")
        return

    today_events.append({"id": next_event_id, "text": command.args, "attendees": []})
    next_event_id += 1
    await message.answer("✅ Мероприятие добавлено на сегодня.")


@dp.message(Command("add_tomorrow"))
async def add_tomorrow_event(message: Message, command: CommandObject):
    global next_event_id
    if message.from_user.id != ADMIN_ID:
        await message.answer("Эта команда доступна только администратору.")
        return
    if not command.args:
        await message.answer("Использование: /add_tomorrow текст мероприятия")
        return

    tomorrow_events.append({"id": next_event_id, "text": command.args, "attendees": []})
    next_event_id += 1
    await message.answer("✅ Мероприятие добавлено на завтра.")


# ----- Мероприятия: просмотр -----

def event_text(event: dict) -> str:
    count = len(event["attendees"])
    going = f"\n\n🙋 Уже идут: {count} чел." if count else "\n\nПока никто не отметился — будь первым!"
    return f"📌 {event['text']}{going}"


@dp.callback_query(F.data == "today_events")
async def show_today_events(callback: CallbackQuery):
    if not today_events:
        await callback.message.edit_text(
            "Сегодня мероприятий пока нет.",
            reply_markup=main_menu_kb()
        )
        return

    await callback.message.edit_text("📅 Мероприятия сегодня:")
    for event in today_events:
        await callback.message.answer(event_text(event), reply_markup=event_kb(event["id"]))
    await callback.message.answer("⬆️ Это все мероприятия на сегодня.", reply_markup=main_menu_kb())


@dp.callback_query(F.data == "tomorrow_events")
async def show_tomorrow_events(callback: CallbackQuery):
    if not tomorrow_events:
        await callback.message.edit_text(
            "На завтра мероприятий пока не добавлено.",
            reply_markup=main_menu_kb()
        )
        return

    await callback.message.edit_text("🗓 Мероприятия завтра:")
    for event in tomorrow_events:
        await callback.message.answer(event_text(event), reply_markup=event_kb(event["id"]))
    await callback.message.answer("⬆️ Это все мероприятия на завтра.", reply_markup=main_menu_kb())


@dp.callback_query(F.data.startswith("join_event_"))
async def join_event(callback: CallbackQuery):
    event_id = int(callback.data.replace("join_event_", ""))
    event = next((e for e in today_events + tomorrow_events if e["id"] == event_id), None)

    if not event:
        await callback.answer("Это мероприятие уже неактуально.", show_alert=True)
        return

    user_id = callback.from_user.id
    if user_id in event["attendees"]:
        await callback.answer("Ты уже отметился на это мероприятие!", show_alert=True)
        return

    event["attendees"].append(user_id)
    await callback.answer("🙋 Отлично, ты в списке!", show_alert=True)
    await callback.message.edit_text(event_text(event), reply_markup=event_kb(event_id))


# ----- Ежедневная фоновая рассылка -----

async def daily_broadcast_loop():
    """Каждый день в заданное время: переносит 'завтрашние' события в 'сегодняшние'
    и рассылает их всем известным пользователям бота."""
    global today_events, tomorrow_events
    while True:
        now = datetime.now()
        target = now.replace(hour=BROADCAST_HOUR, minute=BROADCAST_MINUTE, second=0, microsecond=0)
        if target <= now:
            target = target + timedelta(days=1)
        wait_seconds = (target - now).total_seconds()
        await asyncio.sleep(wait_seconds)

        # переносим вчерашние "завтрашние" события в "сегодняшние"
        today_events = tomorrow_events
        tomorrow_events = []

        if today_events:
            for user_id in list(known_users):
                try:
                    text = "📅 Мероприятия в Севастополе на сегодня:\n\n" + "\n\n".join(
                        f"📌 {e['text']}" for e in today_events
                    )
                    await bot.send_message(user_id, text, reply_markup=main_menu_kb())
                except Exception:
                    pass  # пользователь мог заблокировать бота


# ----- Просмотр объявлений -----

@dp.callback_query(F.data == "browse")
async def browse_categories(callback: CallbackQuery):
    await callback.message.edit_text(
        "Какой раздел посмотреть?",
        reply_markup=categories_kb("browse")
    )


@dp.callback_query(F.data.startswith("browse_"))
async def browse_listings(callback: CallbackQuery):
    category_key = callback.data.replace("browse_", "")
    category_listings = [l for l in listings if l["category"] == category_key]

    if not category_listings:
        await callback.message.edit_text(
            f"В разделе {CATEGORIES[category_key]} пока нет объявлений.\n"
            "Будь первым — создай своё!",
            reply_markup=main_menu_kb()
        )
        return

    await callback.message.edit_text(f"Объявления в разделе {CATEGORIES[category_key]}:")

    for listing in category_listings[-10:]:  # последние 10
        if listing["user_id"] == callback.from_user.id:
            continue  # не показываем человеку его же объявление
        text = (
            f"📍 Район: {listing['district']}\n"
            f"📝 {listing['text']}"
        )
        await callback.message.answer(text, reply_markup=respond_kb(listing["id"]))

    await callback.message.answer("Готово ⬆️ Это все актуальные объявления.", reply_markup=main_menu_kb())


# ----- Отклик на объявление (с сообщением) -----

@dp.callback_query(F.data.startswith("respond_"))
async def respond_to_listing(callback: CallbackQuery, state: FSMContext):
    listing_id = int(callback.data.replace("respond_", ""))
    listing = next((l for l in listings if l["id"] == listing_id), None)

    if not listing:
        await callback.answer("Это объявление уже неактуально.", show_alert=True)
        return

    await state.set_state(RespondToListing.entering_message)
    await state.update_data(listing_id=listing_id)
    await callback.message.answer(
        "Напиши сообщение, которое отправится автору объявления "
        "(например: «Привет! Тоже бегаю по утрам, давай вместе»):"
    )


@dp.message(RespondToListing.entering_message)
async def send_response_message(message: Message, state: FSMContext):
    data = await state.get_data()
    listing = next((l for l in listings if l["id"] == data["listing_id"]), None)

    await state.clear()

    if not listing:
        await message.answer("Это объявление уже неактуально.", reply_markup=main_menu_kb())
        return

    responder = message.from_user
    responder_name = f"@{responder.username}" if responder.username else responder.first_name

    try:
        await bot.send_message(
            listing["user_id"],
            f"✋ На твоё объявление в разделе {CATEGORIES[listing['category']]} откликнулся {responder_name}!\n\n"
            f"Сообщение от него:\n«{message.text}»\n\n"
            f"Чтобы ответить, напиши ему первым."
        )
        await message.answer("✅ Сообщение отправлено автору объявления!", reply_markup=main_menu_kb())
    except Exception:
        await message.answer(
            "Не получилось отправить сообщение (возможно, автор заблокировал бота).",
            reply_markup=main_menu_kb()
        )


# ====== ЗАПУСК ======
async def main():
    asyncio.create_task(daily_broadcast_loop())
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
