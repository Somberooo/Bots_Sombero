import logging
import json
import logging
import json
import os
import re
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler, filters,
    ContextTypes, ConversationHandler, CallbackQueryHandler
)

# ===================== НАСТРОЙКИ =====================
BOT_TOKEN = "8701766372:AAErr0PtnGc_FEvUtvbSHTD8n6wXC6SXfU0"
CHANNEL_ID = -1003301686749  # ← вставь числовой ID канала (узнать через @getidsbot)
SUPER_ADMIN_IDS = [8434813604, 8524655218]
OWNER_IDS = [8434813604, 8524655218]
USERS_FILE = "allowed_users.json"
PLATFORMS_FILE = "platforms.json"
TASKS_FILE = "active_tasks.json"
COOLDOWN_FILE = "cooldown.json"          # новый файл для сохранения КД
TASK_COOLDOWN_SECONDS = 30 * 60         # 30 минут

# ── Ссылки для кнопок в канале ────────────────────────────────────────────
URL_HOW_TO     = "https://somberooo.github.io/sayt_sombero/"   # Как брать задания?
URL_PAYMENTS   = "https://t.me/SomberoPay"   # Выплаты
URL_SUPPORT    = "https://t.me/podderzhka_sombero_bot"   # Поддержка
# ─────────────────────────────────────────────────────────────────────────

# Дефолтные платформы с фиксированными ценами
DEFAULT_PLATFORMS = {
    "Я.Карты": "130₽",
    "Я.Браузер": "60₽",
    "2ГИС": "10₽",
    "Гугл Карты": "30₽",
    "Авито": "150₽",
    "ВКонтакте": "10₽",
    "Профи.ру": "60₽",
    "Отзовик": "60₽",
    "Оценка без текста": "15₽",
}
# =====================================================

logging.basicConfig(level=logging.INFO)

(MAIN_MENU, ADD_PLATFORM_NAME, ADD_PLATFORM_PRICE, ADD_ADMIN_INPUT, ADD_ADMIN_DAYS,
 TASK_PLATFORM, TASK_PAYMENT, TASK_DESCRIPTION, TASK_CUSTOM_PLATFORM) = range(9)


# ── Работа с данными ──────────────────────────────────────────────────────

def load_users() -> dict:
    if os.path.exists(USERS_FILE):
        with open(USERS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

def save_users(users: dict):
    with open(USERS_FILE, "w", encoding="utf-8") as f:
        json.dump(users, f, indent=2, ensure_ascii=False)

def load_platforms() -> dict:
    """Загружает платформы из файла. Если файла нет — возвращает дефолтные и сохраняет их."""
    if os.path.exists(PLATFORMS_FILE):
        with open(PLATFORMS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, list):
                data = {name: "—" for name in data}
            return data
    # Файла нет — первый запуск, сохраняем дефолтные
    save_platforms(dict(DEFAULT_PLATFORMS))
    return dict(DEFAULT_PLATFORMS)

def save_platforms(platforms: dict):
    with open(PLATFORMS_FILE, "w", encoding="utf-8") as f:
        json.dump(platforms, f, indent=2, ensure_ascii=False)

def load_tasks() -> dict:
    if os.path.exists(TASKS_FILE):
        with open(TASKS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

def save_tasks(tasks: dict):
    with open(TASKS_FILE, "w", encoding="utf-8") as f:
        json.dump(tasks, f, indent=2, ensure_ascii=False)

# ── Работа с кулдауном ────────────────────────────────────────────────────

def load_cooldown() -> datetime | None:
    """Загружает время последнего поста из файла"""
    if os.path.exists(COOLDOWN_FILE):
        try:
            with open(COOLDOWN_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                last_time = data.get("last_post_time")
                if last_time:
                    return datetime.fromisoformat(last_time)
        except:
            pass
    return None

def save_cooldown(time: datetime):
    """Сохраняет время последнего поста в файл"""
    with open(COOLDOWN_FILE, "w", encoding="utf-8") as f:
        json.dump({"last_post_time": time.isoformat()}, f)

def get_cooldown_remaining() -> int:
    """Возвращает секунды до конца глобального КД. 0 — свободно."""
    last_time = load_cooldown()
    if last_time is None:
        return 0
    elapsed = (datetime.now() - last_time).total_seconds()
    remaining = int(TASK_COOLDOWN_SECONDS - elapsed)
    return max(0, remaining)

def set_cooldown():
    """Фиксирует время последнего поста и сохраняет в файл."""
    save_cooldown(datetime.now())

# ── Проверка доступа ──────────────────────────────────────────────────────

def is_allowed(user_id: int) -> bool:
    if user_id in SUPER_ADMIN_IDS:
        return True
    users = load_users()
    uid = str(user_id)
    if uid in users:
        expiry = datetime.fromisoformat(users[uid]["expires"])
        if datetime.now() < expiry:
            return True
        else:
            del users[uid]
            save_users(users)
    return False

def is_owner(user_id: int) -> bool:
    return user_id in OWNER_IDS

def add_user(user_id: int, days: int, added_by: int, username: str = None):
    users = load_users()
    expires = (datetime.now() + timedelta(days=days)).isoformat()
    users[str(user_id)] = {
        "expires": expires,
        "added_by": added_by,
        "added_at": datetime.now().isoformat(),
        "username": username
    }
    save_users(users)

def remove_user(user_id: int):
    users = load_users()
    if str(user_id) in users:
        del users[str(user_id)]
        save_users(users)
        return True
    return False

async def get_user_id_by_username(username: str, context) -> int | None:
    try:
        username = username.replace("@", "").strip()
        chat = await context.bot.get_chat(f"@{username}")
        return chat.id
    except:
        return None


# ── Меню ──────────────────────────────────────────────────────────────────

def build_main_menu_markup(uid: int) -> InlineKeyboardMarkup:
    keyboard = [
        [
            InlineKeyboardButton("Открыть набор", callback_data="create_task"),
            InlineKeyboardButton("Закрыть набор", callback_data="close_task"),
        ],
        [InlineKeyboardButton("Информация", callback_data="show_info")],
    ]
    if is_owner(uid):
        keyboard.append([InlineKeyboardButton("Управление платформами", callback_data="manage_platforms")])
        keyboard.append([InlineKeyboardButton("Управление админами", callback_data="manage_admins")])
    return InlineKeyboardMarkup(keyboard)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    # Обработка кнопки "Не могу написать" из канала
    if context.args and context.args[0] == "cant_write":
        await update.message.reply_text(
            "✅ Ваш отклик принят!\nОжидайте сообщения от администратора"
        )
        return ConversationHandler.END
    context.user_data.clear()
    if not is_allowed(uid):
        await update.message.reply_text(
            "У вас нет доступа к боту.\n\nОбратитесь к @angel_sombero для покупки доступа."
        )
        return ConversationHandler.END
    await update.message.reply_text(
        "🗒 <b>Кабинет Администратора:</b>\n\nИспользуя кнопки ниже,\nвы можете открывать и закрывать наборы",
        reply_markup=build_main_menu_markup(uid),
        parse_mode="HTML"
    )
    return MAIN_MENU


async def back_to_main(query, context):
    context.user_data.clear()
    uid = query.from_user.id
    await query.edit_message_text(
        "🗒 <b>Кабинет Администратора:</b>\n\nИспользуя кнопки ниже,\nвы можете открывать и закрывать наборы",
        reply_markup=build_main_menu_markup(uid),
        parse_mode="HTML"
    )


async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    uid = query.from_user.id

    if not is_allowed(uid):
        await query.edit_message_text("У вас нет доступа.")
        return ConversationHandler.END

    data = query.data

    if data == "back_to_main":
        await back_to_main(query, context)
        return MAIN_MENU
    elif data == "show_info":
        await show_info(query, context)
        return MAIN_MENU
    elif data == "cancel_creation":
        await back_to_main(query, context)
        return MAIN_MENU
    elif data == "create_task":
        return await start_task_creation(query, context)
    elif data == "close_task":
        return await show_tasks_to_close(query, context)
    elif data.startswith("select_platform_") or data.startswith("sp_"):
        return await handle_platform_selection(query, context)
    elif data.startswith("close_task_") or data.startswith("ct_"):
        return await handle_close_task(query, context)
    elif data == "confirm_publish":
        await confirm_task(query, context)
        return MAIN_MENU
    elif data == "manage_platforms" and is_owner(uid):
        await show_platform_management(query, context)
        return MAIN_MENU
    elif data == "add_platform" and is_owner(uid):
        await query.edit_message_text("Введите название новой платформы:")
        return ADD_PLATFORM_NAME
    elif data.startswith("delete_platform_") and is_owner(uid):
        await handle_platform_deletion(query, context)
        return MAIN_MENU
    elif data == "manage_admins" and is_owner(uid):
        await show_admin_management(query, context)
        return MAIN_MENU
    elif data == "add_admin" and is_owner(uid):
        await query.edit_message_text(
            "Введите <b>username</b> или <b>ID</b> пользователя:\n\nПримеры:\n• @username\n• 123456789",
            parse_mode="HTML"
        )
        return ADD_ADMIN_INPUT
    elif data.startswith("delete_admin_") and is_owner(uid):
        admin_id = int(data.replace("delete_admin_", ""))
        if admin_id in OWNER_IDS:
            await query.answer("Нельзя удалить владельца!")
        elif remove_user(admin_id):
            await query.answer("Админ удалён!")
        else:
            await query.answer("Не найден!")
        await show_admin_management(query, context)
        return MAIN_MENU

    return MAIN_MENU


# ── Создание задания ──────────────────────────────────────────────────────

async def start_task_creation(query, context):
    remaining = get_cooldown_remaining()
    if remaining > 0:
        mins = remaining // 60
        secs = remaining % 60
        unlock_time = (datetime.now() + timedelta(seconds=remaining)).strftime("%H:%M")
        
        # Получаем время последнего поста для информации
        last_time = load_cooldown()
        last_post_str = "никогда"
        if last_time:
            last_post_str = last_time.strftime("%d.%m %H:%M")
        
        await query.answer()
        await query.edit_message_text(
            f"⏳ <b>Кулдаун активен</b>\n\n"
            f"Последний пост был: <b>{last_post_str}</b>\n"
            f"Следующий можно выставить через: <b>{mins} мин {secs} сек</b>\n"
            f"Откроется в: <b>{unlock_time}</b>",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Назад", callback_data="back_to_main")]])
        )
        return MAIN_MENU
    
    platforms = load_platforms()
    platform_names = list(platforms.keys())
    # Сохраняем список платформ в user_data чтобы потом достать по индексу
    context.user_data["platform_list"] = platform_names
    keyboard = []
    for i in range(0, len(platform_names) - 1, 2):
        keyboard.append([
            InlineKeyboardButton(platform_names[i], callback_data=f"sp_{i}"),
            InlineKeyboardButton(platform_names[i+1], callback_data=f"sp_{i+1}"),
        ])
    if len(platform_names) % 2 != 0:
        last = len(platform_names) - 1
        keyboard.append([InlineKeyboardButton(platform_names[last], callback_data=f"sp_{last}")])
    keyboard.append([InlineKeyboardButton("Другая платформа", callback_data="sp_custom")])
    keyboard.append([InlineKeyboardButton("Отмена", callback_data="cancel_creation")])
    await query.edit_message_text(
        "Отлично! Выбери платформу!",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )
    return TASK_PLATFORM


async def handle_platform_selection(query, context):
    data = query.data  # "sp_0", "sp_1", ... или "sp_custom"

    if data == "sp_custom":
        await query.edit_message_text(
            "Введите название платформы:",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Отмена", callback_data="cancel_creation")]]),
        )
        return TASK_CUSTOM_PLATFORM

    idx = int(data.replace("sp_", ""))
    platform_list = context.user_data.get("platform_list", [])
    if not platform_list or idx >= len(platform_list):
        await query.edit_message_text("Ошибка: попробуйте заново.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Назад", callback_data="back_to_main")]]))
        return MAIN_MENU

    platform = platform_list[idx]
    platforms = load_platforms()
    price = platforms.get(platform)
    context.user_data["platform"] = platform

    if price:
        context.user_data["payment"] = price
        await query.edit_message_text(
            f"Платформа: <b>{platform}</b>\nОплата: <b>{price}</b>\n\nВведите описание задания:",
            parse_mode="HTML",
        )
        return TASK_DESCRIPTION

    await query.edit_message_text(
        f"Платформа: <b>{platform}</b>\n\nВведите сумму оплаты:",
        parse_mode="HTML",
    )
    return TASK_PAYMENT


async def handle_custom_platform(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Пользователь ввёл название кастомной платформы — просим цену."""
    uid = update.effective_user.id
    if not is_allowed(uid):
        return ConversationHandler.END
    text = update.message.text.strip()
    context.user_data["platform"] = text
    await update.message.reply_text(
        f"Платформа: <b>{text}</b>\n\nВведите сумму оплаты:",
        parse_mode="HTML",
    )
    return TASK_PAYMENT


async def confirm_task(query, context):
    d = context.user_data
    if "platform" not in d or "payment" not in d or "description" not in d:
        await query.edit_message_text("Ошибка: данные задания не найдены!")
        await back_to_main(query, context)
        return

    task_id = datetime.now().strftime("%Y%m%d%H%M%S")
    platform = d["platform"]
    payment = d["payment"]
    description = d["description"]
    admin_id = query.from_user.id
    admin_username = query.from_user.username

    post_text = (
        f"<b>НОВОЕ ЗАДАНИЕ!</b>\n\n"
        f"<b>Платформа:</b> {platform}\n"
        f"<b>Оплата:</b> {payment}\n"
        f"<b>Описание:</b> {description}"
    )

    from urllib.parse import quote
    prefill = quote(f"Здравствуйте! я из канала Sombero по поводу задания на {platform}")

    if admin_username:
        respond_url = f"https://t.me/{admin_username}?text={prefill}"
    else:
        bot_info = await context.bot.get_me()
        respond_url = f"https://t.me/{bot_info.username}?start=apply_{task_id}"

    # Только две кнопки пока набор открыт
    buttons = [
        [
            InlineKeyboardButton("Откликнуться", url=respond_url),
            InlineKeyboardButton("Не могу написать", callback_data=f"cant_write_{task_id}"),
        ],
    ]
    reply_markup = InlineKeyboardMarkup(buttons)

    try:
        sent = await context.bot.send_message(CHANNEL_ID, post_text, parse_mode="HTML", reply_markup=reply_markup)
        tasks = load_tasks()
        tasks[task_id] = {
            "platform": platform,
            "description": description,
            "payment": payment,
            "created_by": admin_id,
            "created_by_username": admin_username,
            "created_at": datetime.now().isoformat(),
            "message_id": sent.message_id,
            "closed": False,
        }
        save_tasks(tasks)
        set_cooldown()  # Устанавливаем кулдаун после публикации
        context.user_data.clear()
        await query.edit_message_text("✅ Задание опубликовано в канале!")
    except Exception as e:
        context.user_data.clear()
        await query.edit_message_text(f"❌ Ошибка при публикации: {e}")

    await back_to_main(query, context)


# ── Закрытие набора ───────────────────────────────────────────────────────

async def show_tasks_to_close(query, context):
    try:
        tasks = load_tasks()
        uid = query.from_user.id
        user_tasks = {}
        for tid, t in tasks.items():
            try:
                if int(t["created_by"]) == uid and not t.get("closed", False):
                    user_tasks[tid] = t
            except Exception:
                pass
        if not user_tasks:
            await query.edit_message_text(
                "У вас нет активных заданий.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Назад", callback_data="back_to_main")]]),
            )
            return MAIN_MENU
        keyboard = []
        for tid, t in user_tasks.items():
            created_at = datetime.fromisoformat(t["created_at"]).strftime("%d.%m %H:%M")
            label = f"{t['platform']} | {t['payment']} | {created_at}"
            keyboard.append([InlineKeyboardButton(label, callback_data=f"ct_{tid}")])
        keyboard.append([InlineKeyboardButton("Назад", callback_data="back_to_main")])
        await query.edit_message_text(
            "<b>ЗАКРЫТИЕ НАБОРА</b>\n\nВыберите задание:",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
    except Exception as e:
        await query.edit_message_text(
            f"Ошибка при загрузке заданий: {e}",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Назад", callback_data="back_to_main")]]),
        )
    return MAIN_MENU


async def handle_close_task(query, context):
    data = query.data
    if data.startswith("ct_"):
        task_id = data[len("ct_"):]
    else:
        task_id = data[len("close_task_"):]

    try:
        tasks = load_tasks()
        if task_id not in tasks:
            await query.edit_message_text(
                "Задание не найдено!",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Назад", callback_data="back_to_main")]]),
            )
            return MAIN_MENU

        task = tasks[task_id]
        task["closed"] = True
        task["closed_at"] = datetime.now().isoformat()
        task["closed_by"] = query.from_user.id

        closed_text = (
            "🔒 <b>Задание закончилось!</b>\n"
            "Дождитесь нового поста, чтобы откликнуться\n\n"
            "Не успеваете брать задания? Включите уведомления и получайте их первыми!"
        )

        closed_markup_buttons = []
        if URL_HOW_TO and URL_HOW_TO != "https://ВАШ_ЛИНК":
            closed_markup_buttons.append([InlineKeyboardButton("Как брать задания?", url=URL_HOW_TO)])
        if URL_PAYMENTS and URL_PAYMENTS != "https://ВАШ_ЛИНК" and URL_SUPPORT and URL_SUPPORT != "https://ВАШ_ЛИНК":
            closed_markup_buttons.append([
                InlineKeyboardButton("Выплаты", url=URL_PAYMENTS),
                InlineKeyboardButton("Поддержка", url=URL_SUPPORT),
            ])
        closed_markup = InlineKeyboardMarkup(closed_markup_buttons) if closed_markup_buttons else None

        try:
            await context.bot.edit_message_text(
                chat_id=CHANNEL_ID,
                message_id=task["message_id"],
                text=closed_text,
                parse_mode="HTML",
                reply_markup=closed_markup,
            )
        except Exception as e:
            logging.error(f"Ошибка при редактировании сообщения в канале: {e}")

        # Помечаем закрытым
        save_tasks(tasks)

        await query.edit_message_text(
            "✅ Задание закрыто!",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("В меню", callback_data="back_to_main")]]),
        )
    except Exception as e:
        await query.edit_message_text(
            f"Ошибка: {e}",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Назад", callback_data="back_to_main")]]),
        )
    return MAIN_MENU


# ── Информация ────────────────────────────────────────────────────────────

async def show_info(query, context):
    uid = query.from_user.id
    users = load_users()
    now = datetime.now()
    active_users = sum(1 for u in users.values() if now < datetime.fromisoformat(u["expires"]))
    platforms = load_platforms()
    tasks = load_tasks()
    active_tasks = len([t for t in tasks.values() if not t.get("closed", False)])
    
    # Информация о кулдауне
    remaining = get_cooldown_remaining()
    cooldown_status = "✅ Активен" if remaining > 0 else "✅ Свободно"
    if remaining > 0:
        mins = remaining // 60
        secs = remaining % 60
        cooldown_status = f"⏳ Активен (осталось {mins} мин {secs} сек)"
    
    text = (
        f"<b>ИНФОРМАЦИЯ</b>\n\n"
        f"Ваш ID: <code>{uid}</code>\n"
        f"Статус: {'👑 Владелец' if is_owner(uid) else '👤 Админ'}\n"
        f"Кулдаун: {cooldown_status}\n\n"
        f"Всего админов: {len(users)}\n"
        f"Активных: {active_users}\n"
        f"Платформ: {len(platforms)}\n"
        f"Активных заданий: {active_tasks}\n"
    )
    if platforms:
        text += "\n<b>Платформы:</b>\n"
        for name, price in platforms.items():
            text += f"  • {name} — {price}\n"
    await query.edit_message_text(
        text, parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Назад", callback_data="back_to_main")]]),
    )


# ── Управление платформами ────────────────────────────────────────────────

async def show_platform_management(query, context):
    platforms = load_platforms()
    text = "<b>УПРАВЛЕНИЕ ПЛАТФОРМАМИ</b>\n\n"
    if platforms:
        for i, (name, price) in enumerate(platforms.items(), 1):
            text += f"{i}. {name} — {price}\n"
    else:
        text += "Платформы не добавлены"
    keyboard = [[InlineKeyboardButton("➕ Добавить платформу", callback_data="add_platform")]]
    for i, name in enumerate(platforms.keys(), 1):
        keyboard.append([InlineKeyboardButton(f"❌ Удалить {name}", callback_data=f"delete_platform_{i}")])
    keyboard.append([InlineKeyboardButton("🔙 Назад", callback_data="back_to_main")])
    try:
        await query.edit_message_text(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(keyboard))
    except Exception:
        pass


async def handle_platform_deletion(query, context):
    num = int(query.data.replace("delete_platform_", ""))
    platforms = load_platforms()
    keys = list(platforms.keys())
    if 1 <= num <= len(keys):
        deleted = keys[num - 1]
        del platforms[deleted]
        save_platforms(platforms)
        await query.answer(f"✅ Платформа '{deleted}' удалена!")
    else:
        await query.answer("❌ Ошибка удаления!")
    await show_platform_management(query, context)


# ── Управление админами ───────────────────────────────────────────────────

async def show_admin_management(query, context):
    users = load_users()
    now = datetime.now()
    text = "<b>УПРАВЛЕНИЕ АДМИНАМИ</b>\n\n"
    for uid, info in users.items():
        expiry = datetime.fromisoformat(info["expires"])
        status = "✅ активен" if now < expiry else "❌ истёк"
        uname = info.get("username", "")
        exp_str = expiry.strftime("%d.%m.%Y")
        text += f"{'@' + uname if uname else 'ID: ' + uid} — до {exp_str} ({status})\n"
    if not users:
        text += "Список пуст\n"
    for sid in SUPER_ADMIN_IDS[1:]:
        text += f"ID: {sid} — 👑 суперадмин (постоянный)\n"
    keyboard = [[InlineKeyboardButton("➕ Добавить админа", callback_data="add_admin")]]
    for uid in users:
        keyboard.append([InlineKeyboardButton(f"❌ Удалить {uid}", callback_data=f"delete_admin_{uid}")])
    keyboard.append([InlineKeyboardButton("🔙 Назад", callback_data="back_to_main")])
    await query.edit_message_text(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(keyboard))


# ── Обработчики текста ────────────────────────────────────────────────────

async def handle_add_platform_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Шаг 1: получаем название новой платформы."""
    uid = update.effective_user.id
    if not is_allowed(uid):
        return ConversationHandler.END
    text = update.message.text.strip()
    platforms = load_platforms()
    if text in platforms:
        await update.message.reply_text(f"❌ Платформа «{text}» уже существует!\n\nВведите другое название:")
        return ADD_PLATFORM_NAME
    context.user_data["new_platform_name"] = text
    await update.message.reply_text(
        f"Платформа: <b>{text}</b>\n\nВведите цену для этой платформы (например: 50₽):",
        parse_mode="HTML"
    )
    return ADD_PLATFORM_PRICE


async def handle_add_platform_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Шаг 2: получаем цену и сохраняем платформу."""
    uid = update.effective_user.id
    if not is_allowed(uid):
        return ConversationHandler.END
    price = update.message.text.strip()
    name = context.user_data.get("new_platform_name")
    if not name:
        await update.message.reply_text("❌ Ошибка: начните заново.")
        context.user_data.clear()
        await update.message.reply_text(
            "🗒 <b>Кабинет Администратора:</b>\n\nИспользуя кнопки ниже,\nвы можете открывать и закрывать наборы",
            reply_markup=build_main_menu_markup(uid), parse_mode="HTML"
        )
        return MAIN_MENU
    platforms = load_platforms()
    platforms[name] = price
    save_platforms(platforms)
    context.user_data.clear()
    await update.message.reply_text(
        f"✅ Платформа <b>{name}</b> — <b>{price}</b> добавлена!",
        parse_mode="HTML"
    )
    await update.message.reply_text(
        "🗒 <b>Кабинет Администратора:</b>\n\nИспользуя кнопки ниже,\nвы можете открывать и закрывать наборы",
        reply_markup=build_main_menu_markup(uid), parse_mode="HTML"
    )
    return MAIN_MENU


async def handle_admin_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not is_allowed(uid):
        return ConversationHandler.END
    text = update.message.text.strip()

    user_id = None
    username = None

    if text.lstrip("-").isdigit():
        user_id = int(text)
    else:
        match = re.search(r"@?(\w+)", text)
        if match:
            username = match.group(1)
            user_id = await get_user_id_by_username(username, context)

    if not user_id:
        await update.message.reply_text(
            "❌ Пользователь не найден!\n\nЕсли вводите username — попросите его сначала написать /start этому боту.\nЛибо введите числовой ID."
        )
        return ADD_ADMIN_INPUT

    if user_id in OWNER_IDS:
        await update.message.reply_text("❌ Нельзя изменить права владельца!")
        context.user_data.clear()
        await update.message.reply_text(
            "🗒 <b>Кабинет Администратора:</b>\n\nИспользуя кнопки ниже,\nвы можете открывать и закрывать наборы",
            reply_markup=build_main_menu_markup(uid), parse_mode="HTML"
        )
        return MAIN_MENU

    users = load_users()
    if str(user_id) in users:
        await update.message.reply_text("❌ Этот пользователь уже добавлен как админ!")
        context.user_data.clear()
        await update.message.reply_text(
            "🗒 <b>Кабинет Администратора:</b>\n\nИспользуя кнопки ниже,\nвы можете открывать и закрывать наборы",
            reply_markup=build_main_menu_markup(uid), parse_mode="HTML"
        )
        return MAIN_MENU

    context.user_data["new_admin_id"] = user_id
    context.user_data["new_admin_username"] = username
    display = f"@{username}" if username else f"ID: {user_id}"
    await update.message.reply_text(f"✅ Найден: {display}\n\nНа сколько дней выдать доступ?")
    return ADD_ADMIN_DAYS


async def handle_admin_days(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not is_allowed(uid):
        return ConversationHandler.END
    text = update.message.text.strip()
    try:
        days = int(text)
        if days <= 0:
            await update.message.reply_text("❌ Введите положительное число дней!")
            return ADD_ADMIN_DAYS
            
        admin_id = context.user_data.get("new_admin_id")
        username = context.user_data.get("new_admin_username")
        if not admin_id:
            await update.message.reply_text("❌ Ошибка: начните заново.")
            context.user_data.clear()
            await update.message.reply_text(
                "🗒 <b>Кабинет Администратора:</b>\n\nИспользуя кнопки ниже,\nвы можете открывать и закрывать наборы",
                reply_markup=build_main_menu_markup(uid), parse_mode="HTML"
            )
            return MAIN_MENU
        add_user(admin_id, days, uid, username)
        expires = (datetime.now() + timedelta(days=days)).strftime("%d.%m.%Y")
        display = f"@{username}" if username else f"ID: {admin_id}"
        await update.message.reply_text(
            f"✅ <b>Админ добавлен!</b>\n\nПользователь: {display}\nДоступ до: {expires}",
            parse_mode="HTML"
        )
        context.user_data.clear()
        await update.message.reply_text(
            "🗒 <b>Кабинет Администратора:</b>\n\nИспользуя кнопки ниже,\nвы можете открывать и закрывать наборы",
            reply_markup=build_main_menu_markup(uid), parse_mode="HTML"
        )
        return MAIN_MENU
    except ValueError:
        await update.message.reply_text("❌ Введите корректное число дней!")
        return ADD_ADMIN_DAYS


async def handle_payment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not is_allowed(uid):
        return ConversationHandler.END
    text = update.message.text.strip()
    context.user_data["payment"] = text
    await update.message.reply_text(
        f"Оплата: <b>{text}</b>\n\nВведите описание задания:",
        parse_mode="HTML"
    )
    return TASK_DESCRIPTION


async def handle_description(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not is_allowed(uid):
        return ConversationHandler.END
    text = update.message.text.strip()
    ud = context.user_data
    ud["description"] = text
    preview = (
        f"<b>ПРЕВЬЮ ЗАДАНИЯ</b>\n\n"
        f"Платформа: <b>{ud['platform']}</b>\n"
        f"Оплата: <b>{ud['payment']}</b>\n"
        f"Описание: {text}\n\n"
        f"Опубликовать задание?"
    )
    keyboard = [
        [InlineKeyboardButton("✅ Опубликовать", callback_data="confirm_publish")],
        [InlineKeyboardButton("❌ Отмена", callback_data="cancel_creation")],
    ]
    await update.message.reply_text(preview, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(keyboard))
    return MAIN_MENU


# ── Команда для проверки кулдауна ─────────────────────────────────────────

async def check_cooldown(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда для проверки статуса кулдауна"""
    uid = update.effective_user.id
    if not is_allowed(uid):
        await update.message.reply_text("У вас нет доступа к этой команде.")
        return
    
    remaining = get_cooldown_remaining()
    last_time = load_cooldown()
    
    if remaining > 0:
        mins = remaining // 60
        secs = remaining % 60
        last_post_str = last_time.strftime("%d.%m %H:%M") if last_time else "неизвестно"
        unlock_time = (datetime.now() + timedelta(seconds=remaining)).strftime("%H:%M")
        await update.message.reply_text(
            f"⏳ <b>Кулдаун активен</b>\n\n"
            f"Последний пост: {last_post_str}\n"
            f"Осталось: {mins} мин {secs} сек\n"
            f"Откроется в: {unlock_time}",
            parse_mode="HTML"
        )
    else:
        await update.message.reply_text("✅ Кулдаун не активен, можно создавать задания!")


# ── Обработчик кнопки "Не могу написать" ──────────────────────────────────

async def cant_write_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer(
        "✅ Ваш отклик принят!\nОжидайте сообщения от администратора",
        show_alert=True
    )
    # Уведомляем админа который выставил набор
    task_id = query.data.replace("cant_write_", "")
    tasks = load_tasks()
    if task_id in tasks:
        task = tasks[task_id]
        admin_id = task.get("created_by")
        if admin_id:
            user = query.from_user
            user_link = f"@{user.username}" if user.username else f"<a href='tg://user?id={user.id}'>{user.full_name}</a>"
            platform = task.get("platform", "—")
            try:
                await context.bot.send_message(
                    chat_id=admin_id,
                    text=(
                        f"⚠️ <b>Пользователь не может написать</b>\n\n"
                        f"Пользователь: {user_link}\n"
                        f"Задание: <b>{platform}</b>\n\n"
                        f"Напишите ему первым!"
                    ),
                    parse_mode="HTML"
                )
            except Exception as e:
                logging.error(f"Ошибка при уведомлении админа: {e}")


# ── Запуск ────────────────────────────────────────────────────────────────

def main():
    app = Application.builder().token(BOT_TOKEN).build()

    conv = ConversationHandler(
        entry_points=[
            CommandHandler("start", start),
            CallbackQueryHandler(button_callback, pattern="^(?!cant_write_)"),
        ],
        states={
            MAIN_MENU:          [CallbackQueryHandler(button_callback, pattern="^(?!cant_write_)")],
            ADD_PLATFORM_NAME:  [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_add_platform_name)],
            ADD_PLATFORM_PRICE: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_add_platform_price)],
            ADD_ADMIN_INPUT:    [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_admin_input)],
            ADD_ADMIN_DAYS:     [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_admin_days)],
            TASK_PLATFORM:      [CallbackQueryHandler(button_callback, pattern="^(?!cant_write_)")],
            TASK_CUSTOM_PLATFORM: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_custom_platform)],
            TASK_PAYMENT:       [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_payment)],
            TASK_DESCRIPTION:   [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_description)],
        },
        fallbacks=[CommandHandler("start", start)],
        allow_reentry=True,
    )

    app.add_handler(conv)
    app.add_handler(CallbackQueryHandler(cant_write_callback, pattern="^cant_write_"))
    app.add_handler(CommandHandler("cooldown", check_cooldown))  # Добавляем команду для проверки КД
    
    print("🚀 Бот запущен...")
    print(f"📁 Файлы данных:")
    print(f"  • {USERS_FILE} - список админов")
    print(f"  • {PLATFORMS_FILE} - платформы")
    print(f"  • {TASKS_FILE} - задания")
    print(f"  • {COOLDOWN_FILE} - кулдаун")
    print(f"⏱ Кулдаун установлен: {TASK_COOLDOWN_SECONDS // 60} минут")
    app.run_polling()


if __name__ == "__main__":
    main()