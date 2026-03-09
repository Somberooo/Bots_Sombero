"""
verify_bot.py — Бот верификации (капча)

Схема работы:
  1. Реферальный бот выдаёт ссылку: t.me/VERIFY_BOT?start=ref_REFERRER_ID
  2. Новый пользователь переходит → видит капчу
  3. Нажимает «Я человек» → бот создаёт одноразовую invite-ссылку в канал
  4. Пользователь вступает → засчитывается рефералу в реферальном боте

Оба бота используют одни и те же JSON-файлы (должны лежать в одной папке).
"""

import logging
import json
import os
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    ContextTypes, ChatMemberHandler
)

# ===================== НАСТРОЙКИ =====================
BOT_TOKEN  = "8641784281:AAHPBxOWV11o-l_40dVt-Ic2LgN_BiGEe5s"
CHANNEL_ID = -1003301686749   # ← числовой ID канала (@getidsbot)

# ── Общие файлы с реферальным ботом (должны быть в одной папке) ──
USERS_FILE  = "ref_users.json"
JOINED_FILE = "ref_joined.json"   # invite_url -> [uid, uid, ...]  антифрод
LINKS_FILE  = "ref_links.json"    # uid_реферера -> invite_url

REFERRAL_REWARD = 1    # должно совпадать с настройкой в referral_bot.py
HOLD_HOURS      = 24
# =====================================================

logging.basicConfig(level=logging.INFO)


# ══════════════════════ ХРАНИЛИЩЕ (дублируем из referral_bot) ══════════════

def load(path, default):
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return default

def dump(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

def get_user(uid):
    users = load(USERS_FILE, {})
    k = str(uid)
    if k not in users:
        users[k] = {
            "balance": 0, "hold_items": [], "referrals": 0,
            "referred_by": None, "joined": False, "username": None,
            "requisites": None, "bank": None, "full_name": None, "history": []
        }
        dump(USERS_FILE, users)
    u = users[k]
    for f_, d_ in [("hold_items", []), ("bank", None), ("full_name", None), ("history", [])]:
        if f_ not in u:
            u[f_] = d_
    return u

def save_user(uid, data):
    users = load(USERS_FILE, {})
    users[str(uid)] = data
    dump(USERS_FILE, users)

def add_history(user, amount, kind):
    user["history"].append({"amount": amount, "type": kind,
                             "ts": datetime.now().isoformat()})

# ── Антифрод ─────────────────────────────────────────────────────────────────

def already_counted(invite_url, new_uid):
    joined = load(JOINED_FILE, {})
    return new_uid in joined.get(invite_url, [])

def mark_joined(invite_url, new_uid):
    joined = load(JOINED_FILE, {})
    joined.setdefault(invite_url, [])
    if new_uid not in joined[invite_url]:
        joined[invite_url].append(new_uid)
    dump(JOINED_FILE, joined)

def uid_by_link(url):
    """Возвращает uid реферера по invite-ссылке."""
    links = load(LINKS_FILE, {})
    for k, v in links.items():
        if v == url:
            return int(k)
    return None

def store_link(referrer_uid, url):
    links = load(LINKS_FILE, {})
    links[str(referrer_uid)] = url
    dump(LINKS_FILE, links)


# ══════════════════════ НАЧИСЛЕНИЕ РЕФЕРАЛА ══════════════════════

async def do_referral(referrer_id, new_uid, context):
    if not referrer_id or referrer_id == new_uid:
        return
    referrer = get_user(referrer_id)
    referrer["hold_items"].append({
        "amount": REFERRAL_REWARD,
        "ts":     datetime.now().isoformat()
    })
    referrer["referrals"] = referrer.get("referrals", 0) + 1
    add_history(referrer, REFERRAL_REWARD, "referral_hold")
    save_user(referrer_id, referrer)
    try:
        await context.bot.send_message(
            referrer_id,
            f"🎉 Новый участник вступил по вашей ссылке!\n"
            f"<b>+{REFERRAL_REWARD}₽</b> зачислено — разморозится через {HOLD_HOURS} ч.",
            parse_mode="HTML"
        )
    except:
        pass


# ══════════════════════ ОБРАБОТЧИК ВСТУПЛЕНИЙ В КАНАЛ ══════════════════════

async def on_channel_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отслеживает вступления через наши invite-ссылки и начисляет реферал."""
    result = update.chat_member
    old    = result.old_chat_member.status
    new    = result.new_chat_member.status

    if not (old in ("left", "kicked") and new in ("member", "administrator", "creator")):
        return

    invite  = result.invite_link
    new_uid = result.new_chat_member.user.id

    if not invite:
        return

    invite_url   = invite.invite_link
    referrer_uid = uid_by_link(invite_url)

    if not referrer_uid:
        return

    # Антифрод: один человек = один раз
    if already_counted(invite_url, new_uid):
        return

    mark_joined(invite_url, new_uid)
    await do_referral(referrer_uid, new_uid, context)


# ══════════════════════ /start ══════════════════════

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid      = update.effective_user.id
    username = update.effective_user.username
    args     = context.args

    # Сохраняем реферера из параметра ссылки
    referrer_id = None
    if args and args[0].startswith("ref_"):
        try:
            referrer_id = int(args[0][4:])
            if referrer_id == uid:
                referrer_id = None
        except:
            pass

    # Проверяем — вдруг уже в канале
    try:
        member = await context.bot.get_chat_member(CHANNEL_ID, uid)
        if member.status in ("member", "administrator", "creator"):
            await update.message.reply_text("✅ Вы уже состоите в канале!")
            return
    except:
        pass

    # Запоминаем реферера во временных данных
    if referrer_id:
        context.user_data["referrer_id"] = referrer_id

    # Сохраняем referred_by в профиле (нужно для записи)
    user = get_user(uid)
    user["username"] = username
    if referrer_id and not user.get("referred_by"):
        user["referred_by"] = referrer_id
    save_user(uid, user)

    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Я человек, пропустите меня!", callback_data="verify")
    ]])

    await update.message.reply_text(
        "👋 Привет!\n\n"
        "Прежде чем войти в канал, нам нужно убедиться что вы не бот.\n\n"
        "Нажмите кнопку ниже:",
        reply_markup=kb
    )


# ══════════════════════ ВЕРИФИКАЦИЯ ══════════════════════

async def on_verify(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    uid = query.from_user.id

    # Снова проверяем — вдруг уже в канале
    try:
        member = await context.bot.get_chat_member(CHANNEL_ID, uid)
        if member.status in ("member", "administrator", "creator"):
            await query.edit_message_text("✅ Вы уже состоите в канале!")
            return
    except:
        pass

    # Создаём одноразовую invite-ссылку (1 человек, 10 минут)
    try:
        invite = await context.bot.create_chat_invite_link(
            chat_id=CHANNEL_ID,
            member_limit=1,
            expire_date=datetime.now() + timedelta(minutes=10),
            name=f"verify_{uid}"
        )
        invite_url = invite.invite_link

        # Привязываем ссылку к рефереру чтобы on_channel_member мог начислить
        referrer_id = context.user_data.get("referrer_id")
        if referrer_id:
            # Сохраняем ссылку как ссылку реферера
            # (используем временный ключ чтобы не затереть основную ссылку реферера)
            links = load(LINKS_FILE, {})
            # Ключ: отдельная запись для этой одноразовой ссылки
            links[f"__verify_{uid}"] = invite_url
            dump(LINKS_FILE, links)
            # Перезаписываем uid_by_link чтобы нашёлся referrer_id
            # Сохраняем отдельно в verify_map
            vmap = load("ref_verify_map.json", {})
            vmap[invite_url] = referrer_id
            dump("ref_verify_map.json", vmap)

        await query.edit_message_text(
            "✅ <b>Верификация пройдена!</b>\n\n"
            "Ваша персональная ссылка для входа в канал:\n"
            f"👉 {invite_url}\n\n"
            "⏳ Ссылка действует <b>10 минут</b>.",
            parse_mode="HTML"
        )

    except Exception as e:
        logging.error(f"Ошибка создания invite для {uid}: {e}")
        await query.edit_message_text(
            "❌ Не удалось создать ссылку.\n\n"
            "Убедитесь что бот является администратором канала с правом «Добавление участников»."
        )


# ══════════════════════ MAIN ══════════════════════

def main():
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(on_verify, pattern="^verify$"))
    app.add_handler(ChatMemberHandler(on_channel_member, ChatMemberHandler.CHAT_MEMBER))

    print("Бот верификации запущен...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
