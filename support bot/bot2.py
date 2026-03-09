import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, CallbackQueryHandler, ContextTypes
import sqlite3
from datetime import datetime
import os

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ID администратора (замените на свой Telegram ID)
ADMIN_ID = 8524655218  # Укажите ваш Telegram ID

# Инициализация базы данных
def init_db():
    conn = sqlite3.connect('support_bot.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS users
                 (user_id INTEGER PRIMARY KEY, 
                  username TEXT, 
                  first_name TEXT,
                  last_name TEXT,
                  first_seen TEXT)''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS messages
                 (message_id INTEGER PRIMARY KEY AUTOINCREMENT,
                  user_id INTEGER,
                  user_message TEXT,
                  admin_response TEXT,
                  timestamp TEXT,
                  status TEXT DEFAULT 'pending')''')
    conn.commit()
    conn.close()

# Команда /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    
    # Сохраняем информацию о пользователе
    conn = sqlite3.connect('support_bot.db')
    c = conn.cursor()
    c.execute('''INSERT OR REPLACE INTO users 
                 (user_id, username, first_name, last_name, first_seen)
                 VALUES (?, ?, ?, ?, ?)''',
              (user.id, user.username, user.first_name, user.last_name, 
               datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
    conn.commit()
    conn.close()
    
    welcome_text = (
        f"👋 Здравствуйте, {user.first_name}!\n\n"
        "Это бот поддержки. Вы можете написать любое сообщение, и администратор ответит вам.\n"
        "Просто отправьте ваш вопрос или сообщение, и ожидайте ответа."
    )
    await update.message.reply_text(welcome_text)

# Обработка сообщений от пользователей
async def handle_user_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    
    # Проверяем, не админ ли это
    if user.id == ADMIN_ID:
        return
    
    # Сохраняем сообщение в базу данных
    conn = sqlite3.connect('support_bot.db')
    c = conn.cursor()
    c.execute('''INSERT INTO messages (user_id, user_message, timestamp, status)
                 VALUES (?, ?, ?, ?)''',
              (user.id, update.message.text, 
               datetime.now().strftime("%Y-%m-%d %H:%M:%S"), 'pending'))
    message_id = c.lastrowid
    conn.commit()
    conn.close()
    
    # Отправляем подтверждение пользователю
    await update.message.reply_text("✅ Ваше сообщение отправлено администратору. Ожидайте ответа.")
    
    # Отправляем сообщение администратору
    user_info = f"От: {user.first_name}"
    if user.username:
        user_info += f" (@{user.username})"
    user_info += f"\nID: {user.id}"
    
    keyboard = [
        [InlineKeyboardButton("📝 Ответить", callback_data=f"reply_{user.id}_{message_id}")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await context.bot.send_message(
        chat_id=ADMIN_ID,
        text=f"📨 Новое сообщение от пользователя:\n\n{user_info}\n\nСообщение: {update.message.text}",
        reply_markup=reply_markup
    )

# Обработка нажатий на кнопки (для администратора)
async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if query.from_user.id != ADMIN_ID:
        await query.edit_message_text("❌ У вас нет прав для этого действия.")
        return
    
    data = query.data.split('_')
    action = data[0]
    
    if action == "reply":
        user_id = int(data[1])
        message_id = int(data[2])
        
        # Сохраняем информацию для ответа
        context.user_data['replying_to'] = {
            'user_id': user_id,
            'message_id': message_id
        }
        
        await query.edit_message_text(
            f"✏️ Введите ваш ответ для пользователя (ID: {user_id}):"
        )

# Обработка ответов администратора
async def handle_admin_response(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    
    # Проверяем, что это админ
    if user.id != ADMIN_ID:
        return
    
    # Проверяем, есть ли информация о том, кому отвечаем
    if 'replying_to' not in context.user_data:
        await update.message.reply_text("❌ Сначала выберите сообщение для ответа через кнопку.")
        return
    
    reply_info = context.user_data['replying_to']
    user_id = reply_info['user_id']
    message_id = reply_info['message_id']
    response_text = update.message.text
    
    # Сохраняем ответ в базу данных
    conn = sqlite3.connect('support_bot.db')
    c = conn.cursor()
    c.execute('''UPDATE messages 
                 SET admin_response = ?, status = 'answered'
                 WHERE message_id = ?''',
              (response_text, message_id))
    conn.commit()
    conn.close()
    
    # Отправляем ответ пользователю
    try:
        await context.bot.send_message(
            chat_id=user_id,
            text=f"📬 Ответ от администратора:\n\n{response_text}"
        )
        await update.message.reply_text("✅ Ответ успешно отправлен пользователю!")
    except Exception as e:
        await update.message.reply_text(f"❌ Не удалось отправить ответ пользователю. Ошибка: {e}")
    
    # Очищаем информацию об ответе
    del context.user_data['replying_to']

# Команда для администратора - просмотр статистики
async def admin_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("❌ У вас нет прав для этой команды.")
        return
    
    conn = sqlite3.connect('support_bot.db')
    c = conn.cursor()
    
    # Общая статистика
    c.execute("SELECT COUNT(*) FROM messages")
    total_messages = c.fetchone()[0]
    
    c.execute("SELECT COUNT(*) FROM messages WHERE status = 'pending'")
    pending_messages = c.fetchone()[0]
    
    c.execute("SELECT COUNT(*) FROM users")
    total_users = c.fetchone()[0]
    
    conn.close()
    
    stats_text = (
        f"📊 Статистика бота:\n\n"
        f"👥 Всего пользователей: {total_users}\n"
        f"📨 Всего сообщений: {total_messages}\n"
        f"⏳ Ожидают ответа: {pending_messages}"
    )
    
    await update.message.reply_text(stats_text)

# Команда для администратора - список пользователей
async def admin_users(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("❌ У вас нет прав для этой команды.")
        return
    
    conn = sqlite3.connect('support_bot.db')
    c = conn.cursor()
    c.execute("SELECT user_id, username, first_name, last_name, first_seen FROM users ORDER BY first_seen DESC LIMIT 10")
    users = c.fetchall()
    conn.close()
    
    if not users:
        await update.message.reply_text("Пользователей пока нет.")
        return
    
    users_text = "📋 Последние пользователи:\n\n"
    for user in users:
        user_id, username, first_name, last_name, first_seen = user
        users_text += f"👤 {first_name} {last_name or ''}\n"
        users_text += f"ID: {user_id}\n"
        if username:
            users_text += f"Username: @{username}\n"
        users_text += f"Дата: {first_seen}\n\n"
    
    await update.message.reply_text(users_text)

def main():
    # Инициализация базы данных
    init_db()
    
    # Токен вашего бота (получите у @BotFather)
    TOKEN = "8051714071:AAEvsdWeSILo5_YXLfTWSABEjvsLPqCaHxM"  # Замените на токен вашего бота
    
    # Создаем приложение
    application = Application.builder().token(TOKEN).build()
    
    # Добавляем обработчики команд
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("stats", admin_stats))
    application.add_handler(CommandHandler("users", admin_users))
    
    # Обработчик callback-запросов (кнопки)
    application.add_handler(CallbackQueryHandler(button_callback))
    
    # Обработчик текстовых сообщений
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_user_message))
    application.add_handler(MessageHandler(filters.TEXT & filters.User(ADMIN_ID), handle_admin_response))
    
    # Запускаем бота
    print("Бот запущен...")
    application.run_polling()

if __name__ == '__main__':
    main()