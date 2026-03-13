import logging
import sqlite3
from datetime import datetime

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    filters, CallbackQueryHandler, ContextTypes
)

# ─── Логирование ──────────────────────────────────────────────────────────────
logging.basicConfig(
    format='%(asctime)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ─── Настройки ────────────────────────────────────────────────────────────────
TOKEN = "8703905459:AAGWg5AyPasKkggcpy-Ctvc9iaiuqa-9C6s"
ADMIN_IDS = [8434813604, 8524655218]
ADMIN_USERNAME = "@angel_sombero"
CHANNEL_LINK = "https://t.me/+WD8E6wCz8vA0ZDNi"
DEFAULT_PRICE = "Цена уточняется. Напишите администратору."

# Команды, которые НЕ пересылаются владельцам
ADMIN_COMMANDS = {"/start", "/stats", "/users", "/setprice"}


# ─── БД ───────────────────────────────────────────────────────────────────────
def init_db():
    with sqlite3.connect("bot.db") as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id   INTEGER PRIMARY KEY,
                username  TEXT,
                first_name TEXT,
                last_name  TEXT,
                first_seen TEXT
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id    INTEGER,
                text       TEXT,
                response   TEXT,
                ts         TEXT,
                status     TEXT DEFAULT 'pending'
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                key   TEXT PRIMARY KEY,
                value TEXT
            )
        """)
        conn.execute(
            "INSERT OR IGNORE INTO settings (key, value) VALUES ('price', ?)",
            (DEFAULT_PRICE,)
        )
        conn.commit()


def upsert_user(user):
    with sqlite3.connect("bot.db") as conn:
        conn.execute(
            "INSERT OR REPLACE INTO users VALUES (?,?,?,?,?)",
            (user.id, user.username, user.first_name, user.last_name,
             datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        )
        conn.commit()


def insert_message(user_id, text):
    with sqlite3.connect("bot.db") as conn:
        cur = conn.execute(
            "INSERT INTO messages (user_id, text, ts) VALUES (?,?,?)",
            (user_id, text, datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        )
        conn.commit()
        return cur.lastrowid


def answer_message(msg_id, response):
    with sqlite3.connect("bot.db") as conn:
        conn.execute(
            "UPDATE messages SET response=?, status='answered' WHERE id=?",
            (response, msg_id)
        )
        conn.commit()


def get_setting(key):
    with sqlite3.connect("bot.db") as conn:
        row = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return row[0] if row else None


def set_setting(key, value):
    with sqlite3.connect("bot.db") as conn:
        conn.execute("INSERT OR REPLACE INTO settings VALUES (?,?)", (key, value))
        conn.commit()


def get_stats():
    with sqlite3.connect("bot.db") as conn:
        total  = conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
        pending = conn.execute("SELECT COUNT(*) FROM messages WHERE status='pending'").fetchone()[0]
        users  = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        return users, total, pending


def get_last_users(limit=10):
    with sqlite3.connect("bot.db") as conn:
        return conn.execute(
            "SELECT user_id, username, first_name, last_name, first_seen "
            "FROM users ORDER BY first_seen DESC LIMIT ?", (limit,)
        ).fetchall()


# ─── Клавиатура /start ────────────────────────────────────────────────────────
def main_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(" Стоимость адмики ",            callback_data="price")],
        [InlineKeyboardButton(" Позвать оператора ", callback_data="contact")],
        [InlineKeyboardButton(" Стоимость рекламы ",            callback_data="ads")],
        [InlineKeyboardButton(" Наши проекты ",                 url=CHANNEL_LINK)],
    ])


# ─── Хендлеры ─────────────────────────────────────────────────────────────────
async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    upsert_user(update.effective_user)
    await update.message.reply_text(
        f"👋 Привет, {update.effective_user.first_name}!\n\n"
        "Добро пожаловать! Выберите раздел или напишите сообщение — "
        "администратор ответит вам.",
        reply_markup=main_keyboard()
    )


async def cmd_stats(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        return
    u, t, p = get_stats()
    await update.message.reply_text(
        f"📊 Статистика:\n\n👥 Пользователей: {u}\n📨 Сообщений: {t}\n⏳ Без ответа: {p}"
    )


async def cmd_users(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        return
    rows = get_last_users()
    if not rows:
        await update.message.reply_text("Пользователей пока нет.")
        return
    text = "📋 Последние пользователи:\n\n"
    for uid, uname, first, last, seen in rows:
        text += f"👤 {first} {last or ''}  |  ID: {uid}"
        if uname:
            text += f"  |  @{uname}"
        text += f"\n📅 {seen}\n\n"
    await update.message.reply_text(text)


async def cmd_setprice(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        return
    if not ctx.args:
        await update.message.reply_text(
            f"Текущий прайс:\n\n{get_setting('price')}\n\n"
            "Чтобы изменить:\n/setprice Новый текст"
        )
        return
    new_price = " ".join(ctx.args)
    set_setting("price", new_price)
    await update.message.reply_text(f"✅ Прайс обновлён:\n\n{new_price}")


async def on_button(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "price":
        await query.message.reply_text(f"💼 Стоимость адмики:\n\n{get_setting('price')}")

    elif data == "contact":
        await query.message.reply_text(
            "Мы позвали оператора, а пока вы ждете напишите свой вопрос"
        )

    elif data == "ads":
        await query.message.reply_text(
            f"📢 По вопросам рекламы обращайтесь к владельцу:\n\n"
            f"{ADMIN_USERNAME}\n\n💬 Цена обговаривается лично."
        )

    elif data.startswith("reply_"):
        if query.from_user.id not in ADMIN_IDS:
            await query.answer("❌ Нет прав.", show_alert=True)
            return
        _, user_id_str, msg_id_str = data.split("_")
        ctx.user_data["replying_to"] = {
            "user_id": int(user_id_str),
            "msg_id": int(msg_id_str),
        }
        await query.edit_message_text(
            query.message.text + "\n\n✏️ Теперь напишите ответ:"
        )


async def on_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    text = update.message.text

    logger.info(f"Сообщение от {user.id} ({user.first_name}): {text[:60]}")

    # ── АДМИНИСТРАТОР ──
    if user.id in ADMIN_IDS:
        if "replying_to" in ctx.user_data:
            info       = ctx.user_data.pop("replying_to")
            target_id  = info["user_id"]
            msg_id     = info["msg_id"]
            answer_message(msg_id, text)
            try:
                await ctx.bot.send_message(
                    chat_id=target_id,
                    text=f"📬 Ответ от администратора:\n\n{text}"
                )
                await update.message.reply_text("✅ Ответ отправлен!")
                logger.info(f"Админ {user.id} ответил пользователю {target_id}")
            except Exception as e:
                await update.message.reply_text(f"❌ Ошибка: {e}")
                logger.error(f"Ошибка при отправке ответа пользователю {target_id}: {e}")

            # Уведомляем второго админа
            for aid in ADMIN_IDS:
                if aid != user.id:
                    try:
                        await ctx.bot.send_message(
                            chat_id=aid,
                            text=f"ℹ️ {user.first_name} ответил пользователю {target_id}:\n\n{text}"
                        )
                    except Exception:
                        pass
        # Если не в режиме ответа — игнорируем сообщение от админа
        return

    # ── ОБЫЧНЫЙ ПОЛЬЗОВАТЕЛЬ ──
    upsert_user(user)
    msg_id = insert_message(user.id, text)
    logger.info(f"Сохранено сообщение #{msg_id} от пользователя {user.id}")

    await update.message.reply_text(
        "✅ Сообщение получено! Администратор ответит вам как можно быстрее."
    )

    user_label = f"👤 {user.first_name}"
    if user.last_name:
        user_label += f" {user.last_name}"
    if user.username:
        user_label += f" (@{user.username})"
    user_label += f"\n🆔 ID: {user.id}"

    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("📝 Ответить", callback_data=f"reply_{user.id}_{msg_id}")
    ]])

    for aid in ADMIN_IDS:
        try:
            logger.info(f"Отправляю уведомление админу {aid}...")
            await ctx.bot.send_message(
                chat_id=aid,
                text=f"📨 Новое сообщение!\n\n{user_label}\n\n💬 {text}",
                reply_markup=kb
            )
            logger.info(f"✅ Уведомление отправлено админу {aid}")
        except Exception as e:
            logger.error(f"❌ ОШИБКА отправки админу {aid}: {type(e).__name__}: {e}")
            import traceback
            traceback.print_exc()


# ─── main ─────────────────────────────────────────────────────────────────────
def main():
    init_db()
    logger.info("БД инициализирована")

    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start",    cmd_start))
    app.add_handler(CommandHandler("stats",    cmd_stats))
    app.add_handler(CommandHandler("users",    cmd_users))
    app.add_handler(CommandHandler("setprice", cmd_setprice))
    app.add_handler(CallbackQueryHandler(on_button))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))

    logger.info("Бот запущен, жду сообщения...")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
