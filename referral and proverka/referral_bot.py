import logging
import json
import os
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler, filters,
    ContextTypes, ConversationHandler, CallbackQueryHandler, ChatMemberHandler
)

# ===================== НАСТРОЙКИ =====================
BOT_TOKEN   = "8675604612:AAHyYC7phGuLpCDUyNSHnrsAtwDM0VkcWo8"
CHANNEL_ID   = -1003301686749            # ← ЗАМЕНИ на числовой ID канала (см. инструкцию)
CHANNEL_LINK = "https://t.me/+WD8E6wCz8vA0ZDNi"  # пригласительная ссылка на канал
VERIFY_BOT   = "ne_robot_Sombero_bot"        # ← username бота-верификатора (без @)
ADMIN_IDS   = [8434813604, 8524655218]

WEBSITE_URL     = "https://somberooo.github.io/sayt_sombero/"            # ← замени на свой сайт
HOLD_FAQ_URL    = "https://somberooo.github.io/sayt_sombero/"   # ← страница «что такое холд»
SUPPORT_USERNAME = "@podderzhka_sombero_bot"                       # ← поддержка

USERS_FILE    = "ref_users.json"
WITHDRAW_FILE = "ref_withdrawals.json"
COUNTER_FILE  = "ref_counter.json"
LINKS_FILE    = "ref_links.json"       # uid -> personal invite link url
JOINED_FILE   = "ref_joined.json"      # invite_link_url -> [uid, uid, ...]  (антифрод)

REFERRAL_REWARD  = 1      # ₽ за каждого вступившего
HOLD_HOURS       = 24     # часов до разморозки
MIN_REFERRALS    = 10     # минимум приглашённых для вывода
# =====================================================

logging.basicConfig(level=logging.INFO)
(MAIN, ENTER_REQUISITES, ENTER_BANK, ENTER_NAME, ADMIN_EDIT) = range(5)
ACT_ADD_BALANCE = "add_balance"


# ══════════════════════ ХРАНИЛИЩЕ ══════════════════════

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
            "balance":      0,
            "hold_items":   [],   # [{"amount": 2, "ts": "2024-..."}]
            "referrals":    0,
            "referred_by":  None,
            "joined":       False,
            "username":     None,
            "requisites":   None,   # номер телефона
            "bank":         None,   # банк
            "full_name":    None,   # фамилия имя
            "history":      []
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

def next_id():
    d = load(COUNTER_FILE, {"n": 0})
    d["n"] += 1
    dump(COUNTER_FILE, d)
    return str(d["n"])

def is_admin(uid):
    return uid in ADMIN_IDS

def add_history(user, amount, kind):
    user["history"].append({"amount": amount, "type": kind,
                             "ts": datetime.now().isoformat()})

# ── Авто-разморозка холда (HOLD_HOURS) ──────────────────────────────────────

def release_hold(user):
    """Переводит созревшие hold_items в balance. Изменяет объект на месте."""
    now   = datetime.now()
    ready = []
    still = []
    for item in user.get("hold_items", []):
        age = now - datetime.fromisoformat(item["ts"])
        if age >= timedelta(hours=HOLD_HOURS):
            ready.append(item)
        else:
            still.append(item)
    if ready:
        total = sum(i["amount"] for i in ready)
        user["balance"]    = user.get("balance", 0) + total
        user["hold_items"] = still
        add_history(user, total, "hold_released")
    return user

def hold_total(user):
    return sum(i["amount"] for i in user.get("hold_items", []))


# ══════════════════════ INVITE-ССЫЛКИ ══════════════════════

def get_stored_link(uid):
    return load(LINKS_FILE, {}).get(str(uid))

def store_link(uid, url):
    links = load(LINKS_FILE, {})
    links[str(uid)] = url
    dump(LINKS_FILE, links)

def uid_by_link(url):
    links = load(LINKS_FILE, {})
    for k, v in links.items():
        if v == url:
            return int(k)
    return None

async def get_or_create_invite(uid, context) -> str | None:
    existing = get_stored_link(uid)
    if existing:
        return existing
    try:
        obj = await context.bot.create_chat_invite_link(
            chat_id=CHANNEL_ID,
            name=f"ref_{uid}",
        )
        url = obj.invite_link
        store_link(uid, url)
        return url
    except Exception as e:
        logging.error(f"create_chat_invite_link uid={uid}: {e}")
        return None

# ── Антифрод: один пользователь — один раз по одной ссылке ──────────────────

def already_counted(invite_url, new_uid):
    joined = load(JOINED_FILE, {})
    return new_uid in joined.get(invite_url, [])

def mark_joined(invite_url, new_uid):
    joined = load(JOINED_FILE, {})
    joined.setdefault(invite_url, [])
    if new_uid not in joined[invite_url]:
        joined[invite_url].append(new_uid)
    dump(JOINED_FILE, joined)


# ══════════════════════ ПРОВЕРКА ПОДПИСКИ ══════════════════════

async def check_sub(uid, context):
    try:
        m = await context.bot.get_chat_member(CHANNEL_ID, uid)
        return m.status in ("member", "administrator", "creator")
    except:
        return False


# ══════════════════════ РЕФЕРАЛ ══════════════════════

async def do_referral(referrer_id, new_uid, invite_url, context):
    if not referrer_id or referrer_id == new_uid:
        return
    # Антифрод
    if invite_url and already_counted(invite_url, new_uid):
        return
    if invite_url:
        mark_joined(invite_url, new_uid)

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
            f"🎉 Новый участник зарегистрировался по вашей ссылке!\n"
            f"<b>+{REFERRAL_REWARD}₽</b> зачислено — средства разморозятся через {HOLD_HOURS} ч.",
            parse_mode="HTML"
        )
    except:
        pass


# ══════════════════════ ОБРАБОТЧИК ВСТУПЛЕНИЙ В КАНАЛ ══════════════════════

async def on_channel_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    result = update.chat_member
    old    = result.old_chat_member.status
    new    = result.new_chat_member.status

    if not (old in ("left", "kicked") and new in ("member", "administrator", "creator")):
        return

    invite   = result.invite_link
    new_uid  = result.new_chat_member.user.id

    if not invite:
        return

    invite_url   = invite.invite_link
    referrer_uid = uid_by_link(invite_url)

    if referrer_uid:
        await do_referral(referrer_uid, new_uid, invite_url, context)


# ══════════════════════ ВАЛИДАЦИЯ РЕКВИЗИТОВ ══════════════════════

def validate_phone(text: str) -> bool:
    """Принимает номера вида 89XXXXXXXXX или +79XXXXXXXXX (11 цифр)."""
    t = text.strip().replace(" ", "").replace("-", "")
    if t.startswith("+7"):
        t = "8" + t[2:]
    return t.isdigit() and len(t) == 11 and t.startswith("89")

def format_phone(text: str) -> str:
    t = text.strip().replace(" ", "").replace("-", "")
    if t.startswith("+7"):
        t = "8" + t[2:]
    return f"+7 ({t[1:4]}) {t[4:7]}-{t[7:9]}-{t[9:11]}"


# ══════════════════════ КЛАВИАТУРЫ ══════════════════════

def sub_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📢 Подписаться на канал", url=CHANNEL_LINK)],
        [InlineKeyboardButton("✅ Я подписался", callback_data="check_sub")],
    ])

def main_kb(uid):
    kb = [
        [InlineKeyboardButton("👤 Мой профиль", callback_data="profile")],
        [InlineKeyboardButton("⚙️ Настройки",   callback_data="settings"),
         InlineKeyboardButton("🌐 Сайт",         url=WEBSITE_URL),
         InlineKeyboardButton("💬 Поддержка",    url=f"https://t.me/{SUPPORT_USERNAME.lstrip('@')}")],
    ]
    if is_admin(uid):
        kb.append([InlineKeyboardButton("🔧 Администратор", callback_data="admin")])
    return InlineKeyboardMarkup(kb)

def profile_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📊 Статистика",      callback_data="stats"),
         InlineKeyboardButton("💸 Вывести средства", callback_data="withdraw")],
        [InlineKeyboardButton("← Назад",            callback_data="back")],
    ])

def settings_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("💳 Изменить реквизиты", callback_data="edit_requisites")],
        [InlineKeyboardButton("← Назад",               callback_data="back")],
    ])

def stats_period_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Сегодня", callback_data="stats_today"),
         InlineKeyboardButton("3 дня",   callback_data="stats_3days")],
        [InlineKeyboardButton("Неделя",  callback_data="stats_week"),
         InlineKeyboardButton("Месяц",   callback_data="stats_month")],
        [InlineKeyboardButton("← Назад", callback_data="profile")],
    ])

def back_kb(to="back"):
    return InlineKeyboardMarkup([[InlineKeyboardButton("← Назад", callback_data=to)]])


# ══════════════════════ ТЕКСТЫ ══════════════════════

def main_text():
    return (
        "💼 <b>Реферальная система</b> — делитесь своей уникальной ссылкой "
        "и получайте вознаграждение за каждого нового участника!\n\n"
        f"Следите за обновлениями в нашем <a href=\"{CHANNEL_LINK}\">официальном канале</a> — "
        "там всегда актуальные новости."
    )

def profile_text(uid):
    user = get_user(uid)
    user = release_hold(user)
    save_user(uid, user)

    available = user.get("balance", 0)
    hold      = hold_total(user)
    refs      = user.get("referrals", 0)
    left      = max(0, MIN_REFERRALS - refs)

    # Реферальная ссылка ведёт на бота верификации
    ref_url   = f"https://t.me/{VERIFY_BOT}?start=ref_{uid}"

    withdraw_hint = (
        f"✅ Вывод средств доступен!"
        if refs >= MIN_REFERRALS else
        f"🔒 До вывода нужно пригласить ещё <b>{left}</b> чел. (минимум {MIN_REFERRALS})"
    )

    return (
        f"👤 <b>Личный кабинет</b>\n\n"
        f"┌ К выплате: <b>{available:.2f} ₽</b>\n"
        f"└ Ожидает разморозки: <b>{hold:.2f} ₽</b>  "
        f"<a href=\"{HOLD_FAQ_URL}\">Что это?</a>\n\n"
        f"👥 Приглашено: <b>{refs}</b> чел.\n"
        f"{withdraw_hint}\n\n"
        f"🔗 <b>Ваша реферальная ссылка:</b>\n"
        f"<code>{ref_url}</code>\n\n"
        f"Отправьте её друзьям — за каждого нового участника вам начислится бонус."
    )

def settings_text(uid):
    user = get_user(uid)
    req  = user.get("requisites")
    bank = user.get("bank")
    name = user.get("full_name")
    if req and bank and name:
        req_line = f"<b>{req}</b> · {bank} · {name}"
    else:
        req_line = "<i>Не указаны</i>"
    return (
        f"⚙️ <b>Настройки</b>\n\n"
        f"Здесь вы можете обновить платёжные данные.\n\n"
        f"📱 Телефон: {req_line}"
    )

def stats_text(uid, period_label, days):
    user    = get_user(uid)
    history = user.get("history", [])
    since   = datetime.now() - timedelta(days=days)
    earned  = sum(
        h["amount"] for h in history
        if h["type"] in ("referral_hold", "referral") and
           datetime.fromisoformat(h["ts"]) >= since
    )
    refs = sum(
        1 for h in history
        if h["type"] in ("referral_hold", "referral") and
           datetime.fromisoformat(h["ts"]) >= since
    )
    total_earned = sum(
        h["amount"] for h in history
        if h["type"] in ("referral_hold", "referral")
    )
    return (
        f"📊 <b>Статистика — {period_label}</b>\n\n"
        f"👥 Привлечено: <b>{refs}</b> чел.\n"
        f"💰 Начислено: <b>{earned:.2f}₽</b>\n\n"
        f"За всё время:\n"
        f"└ Приглашено: <b>{user.get('referrals', 0)}</b> чел. | Начислено: <b>{total_earned:.2f}₽</b>"
    )


# ══════════════════════ /start ══════════════════════

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid      = update.effective_user.id
    username = update.effective_user.username
    args     = context.args

    user = get_user(uid)
    user["username"] = username

    if args and args[0].startswith("ref_"):
        try:
            ref = int(args[0][4:])
            if ref != uid and not user["referred_by"]:
                user["referred_by"] = ref
        except:
            pass

    if not await check_sub(uid, context):
        user["joined"] = False
        save_user(uid, user)
        await update.message.reply_text(
            "👋 Добро пожаловать!\n\nЧтобы начать работу, оформите подписку на наш канал:",
            reply_markup=sub_kb()
        )
        return MAIN

    if not user["joined"]:
        user["joined"] = True
        save_user(uid, user)

    save_user(uid, user)
    await update.message.reply_text(
        main_text(), parse_mode="HTML",
        reply_markup=main_kb(uid),
        disable_web_page_preview=True
    )
    return MAIN


# ══════════════════════ CALLBACKS ══════════════════════

async def cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    uid  = query.from_user.id
    data = query.data

    if data != "check_sub" and not await check_sub(uid, context):
        await query.edit_message_text(
            "Доступ закрыт. Подпишитесь на канал, чтобы продолжить:",
            reply_markup=sub_kb()
        )
        return MAIN

    if data == "check_sub":
        if not await check_sub(uid, context):
            await query.answer("❌ Подписка не найдена. Попробуйте ещё раз.", show_alert=True)
            return MAIN
        user = get_user(uid)
        user["username"] = query.from_user.username
        user["joined"]   = True
        save_user(uid, user)
        await query.edit_message_text(
            main_text(), parse_mode="HTML",
            reply_markup=main_kb(uid),
            disable_web_page_preview=True
        )
        return MAIN

    if data == "back":
        await query.edit_message_text(
            main_text(), parse_mode="HTML",
            reply_markup=main_kb(uid),
            disable_web_page_preview=True
        )

    # ══════════ ПРОФИЛЬ ══════════

    elif data == "profile":
        invite_url = None  # ссылка теперь генерируется в verify_bot
        await query.edit_message_text(
            profile_text(uid),
            parse_mode="HTML",
            reply_markup=profile_kb(),
            disable_web_page_preview=True
        )

    # ══════════ НАСТРОЙКИ ══════════

    elif data == "settings":
        await query.edit_message_text(
            settings_text(uid), parse_mode="HTML",
            reply_markup=settings_kb()
        )

    elif data == "edit_requisites":
        context.user_data["action"] = "set_card"
        await query.edit_message_text(
            "📱 <b>Шаг 1 из 3 — Номер телефона</b>\n\n"
            "Введите номер телефона, привязанного к банку.\n"
            "Формат: <code>89XXXXXXXXX</code> или <code>+79XXXXXXXXX</code>:",
            parse_mode="HTML",
            reply_markup=back_kb("settings")
        )
        return ENTER_REQUISITES

    # ══════════ СТАТИСТИКА ══════════

    elif data == "stats":
        await query.edit_message_text(
            "📊 <b>За какой период показать статистику?</b>",
            parse_mode="HTML",
            reply_markup=stats_period_kb()
        )

    elif data in ("stats_today", "stats_3days", "stats_week", "stats_month"):
        mapping = {
            "stats_today": ("Сегодня", 1),
            "stats_3days": ("3 дня",   3),
            "stats_week":  ("Неделя",  7),
            "stats_month": ("Месяц",   30),
        }
        label, days = mapping[data]
        await query.edit_message_text(
            stats_text(uid, label, days),
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("← К периодам", callback_data="stats")],
                [InlineKeyboardButton("← Профиль",    callback_data="profile")],
            ])
        )

    # ══════════ ВЫВОД СРЕДСТВ ══════════

    elif data == "withdraw":
        user = get_user(uid)
        user = release_hold(user)
        save_user(uid, user)

        refs = user.get("referrals", 0)
        if refs < MIN_REFERRALS:
            await query.edit_message_text(
                f"🔒 <b>Вывод пока недоступен</b>\n\n"
                f"Минимальное условие: пригласить <b>{MIN_REFERRALS}</b> человек.\n"
                f"Вы пригласили: <b>{refs}</b> чел.\n"
                f"Осталось: <b>{MIN_REFERRALS - refs}</b> чел.",
                parse_mode="HTML",
                reply_markup=back_kb("profile")
            )
            return MAIN

        if not user.get("requisites") or not user.get("bank") or not user.get("full_name"):
            await query.edit_message_text(
                "⚠️ <b>Реквизиты не указаны</b>\n\n"
                "Перед выводом укажите карту, банк и имя получателя в настройках.",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("💳 Указать реквизиты", callback_data="edit_requisites")],
                    [InlineKeyboardButton("← Назад",               callback_data="profile")],
                ])
            )
            return MAIN

        available = user.get("balance", 0)
        if available <= 0:
            await query.edit_message_text(
                f"💸 <b>Вывод средств</b>\n\n"
                f"На данный момент свободных средств нет.\n"
                f"Ожидает разморозки: <b>{hold_total(user):.2f}₽</b> (через {HOLD_HOURS} ч.)\n\n"
                f"📱 {user['requisites']} · {user['bank']} · {user['full_name']}",
                parse_mode="HTML",
                reply_markup=back_kb("profile")
            )
            return MAIN

        await query.edit_message_text(
            f"💸 <b>Вывод средств</b>\n\n"
            f"💰 Доступно: <b>{available:.2f}₽</b>\n"
            f"📱 {user['requisites']} · {user['bank']} · {user['full_name']}\n\n"
            f"Вывести <b>{available:.2f}₽</b> на указанные реквизиты?",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ Подтвердить", callback_data="confirm_withdraw")],
                [InlineKeyboardButton("← Отмена",       callback_data="profile")],
            ])
        )

    elif data == "confirm_withdraw":
        user = get_user(uid)
        user = release_hold(user)
        if not user.get("requisites") or user.get("balance", 0) <= 0 or user.get("referrals", 0) < MIN_REFERRALS:
            await query.answer("Средства недоступны или условия не выполнены.", show_alert=True)
            return MAIN
        amount = user["balance"]
        user["balance"] = 0
        add_history(user, -amount, "withdraw")
        save_user(uid, user)

        wid = next_id()
        withdrawals = load(WITHDRAW_FILE, {})
        withdrawals[wid] = {
            "user_id":    uid,
            "username":   query.from_user.username,
            "amount":     amount,
            "requisites": user["requisites"],
            "bank":       user["bank"],
            "full_name":  user["full_name"],
            "status":     "pending",
            "created_at": datetime.now().isoformat(),
        }
        dump(WITHDRAW_FILE, withdrawals)

        for aid in ADMIN_IDS:
            try:
                uname = f"@{query.from_user.username}" if query.from_user.username else f"ID:{uid}"
                await context.bot.send_message(
                    aid,
                    f"💸 <b>ЗАЯВКА НА ВЫВОД #{wid}</b>\n\n"
                    f"Пользователь: {uname} (<code>{uid}</code>)\n"
                    f"Сумма: <b>{amount:.2f}₽</b>\n"
                    f"Телефон: <b>{user['requisites']}</b>\n"
                    f"Банк: <b>{user['bank']}</b>\n"
                    f"Получатель: <b>{user['full_name']}</b>",
                    parse_mode="HTML",
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton("✅ Выплачено",  callback_data=f"wpay_{wid}"),
                        InlineKeyboardButton("❌ Отклонить", callback_data=f"wreject_{wid}"),
                    ]])
                )
            except:
                pass

        await query.edit_message_text(
            f"✅ <b>Заявка #{wid} принята!</b>\n\n"
            f"Сумма: <b>{amount:.2f}₽</b>\n"
            f"Телефон: <b>{user['requisites']}</b>\n"
            f"Банк: <b>{user['bank']}</b>\n\n"
            f"Выплата будет обработана в ближайшее время.",
            parse_mode="HTML",
            reply_markup=back_kb("profile")
        )

    # ══════════ АДМИН ══════════

    elif data == "admin" and is_admin(uid):
        await show_admin(query)

    elif data == "admin_withdrawals" and is_admin(uid):
        withdrawals = load(WITHDRAW_FILE, {})
        pending = [(wid, w) for wid, w in withdrawals.items() if w["status"] == "pending"]
        if not pending:
            await query.edit_message_text(
                "Активных заявок на вывод пока нет.",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("← Назад", callback_data="admin")
                ]])
            )
            return MAIN
        text = "💸 <b>Заявки на вывод:</b>\n\n"
        kb   = []
        for wid, w in sorted(pending):
            uname  = f"@{w['username']}" if w.get("username") else f"ID:{w['user_id']}"
            text  += f"#{wid} | {uname} | {w['amount']:.2f}₽ | {w.get('bank','?')} | {w.get('full_name','?')}\n"
            kb.append([
                InlineKeyboardButton(f"✅ #{wid}", callback_data=f"wpay_{wid}"),
                InlineKeyboardButton(f"❌ #{wid}", callback_data=f"wreject_{wid}"),
            ])
        kb.append([InlineKeyboardButton("← Назад", callback_data="admin")])
        await query.edit_message_text(text, parse_mode="HTML",
                                      reply_markup=InlineKeyboardMarkup(kb))

    elif data.startswith("wpay_") and is_admin(uid):
        wid         = data[5:]
        withdrawals = load(WITHDRAW_FILE, {})
        if wid in withdrawals and withdrawals[wid]["status"] == "pending":
            withdrawals[wid]["status"] = "paid"
            dump(WITHDRAW_FILE, withdrawals)
            w = withdrawals[wid]
            try:
                await context.bot.send_message(
                    w["user_id"],
                    f"💰 Выплата по заявке #{wid} на сумму <b>{w['amount']:.2f}₽</b> проведена!\n"
                    f"Телефон: <b>{w['requisites']}</b>",
                    parse_mode="HTML"
                )
            except:
                pass
            try:
                await query.edit_message_text(
                    query.message.text + f"\n\n✅ #{wid} — выплачено",
                    parse_mode="HTML"
                )
            except:
                pass

    elif data.startswith("wreject_") and is_admin(uid):
        wid         = data[8:]
        withdrawals = load(WITHDRAW_FILE, {})
        if wid in withdrawals and withdrawals[wid]["status"] == "pending":
            w    = withdrawals[wid]
            user = get_user(w["user_id"])
            user["balance"] = user.get("balance", 0) + w["amount"]
            add_history(user, w["amount"], "withdraw_return")
            save_user(w["user_id"], user)
            withdrawals[wid]["status"] = "rejected"
            dump(WITHDRAW_FILE, withdrawals)
            try:
                await context.bot.send_message(
                    w["user_id"],
                    f"❌ Заявка #{wid} была отклонена.\n"
                    f"<b>{w['amount']:.2f}₽</b> возвращены на ваш счёт.",
                    parse_mode="HTML"
                )
            except:
                pass
            try:
                await query.edit_message_text(
                    query.message.text + f"\n\n❌ #{wid} — отклонено",
                    parse_mode="HTML"
                )
            except:
                pass

    elif data == "admin_stats" and is_admin(uid):
        users       = load(USERS_FILE, {})
        withdrawals = load(WITHDRAW_FILE, {})
        total_bal   = sum(u.get("balance", 0) for u in users.values())
        total_hold  = sum(hold_total(u) for u in users.values())
        total_refs  = sum(u.get("referrals", 0) for u in users.values())
        paid        = sum(w["amount"] for w in withdrawals.values() if w["status"] == "paid")
        await query.edit_message_text(
            f"📊 <b>Статистика</b>\n\n"
            f"👥 Пользователей: {len(users)}\n"
            f"🔗 Всего рефералов: {total_refs}\n"
            f"💰 Свободных средств: {total_bal:.2f}₽\n"
            f"⏳ В разморозке: {total_hold:.2f}₽\n"
            f"💸 Выплачено: {paid:.2f}₽",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("← Назад", callback_data="admin")
            ]])
        )

    elif data == "admin_add_balance" and is_admin(uid):
        context.user_data["admin_action"] = ACT_ADD_BALANCE
        await query.edit_message_text(
            "Укажите ID пользователя и сумму через пробел:\n\n"
            "Пример: <code>123456789 50</code>",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("← Отмена", callback_data="admin")
            ]])
        )
        return ADMIN_EDIT

    return MAIN


# ══════════════════════ ВВОД РЕКВИЗИТОВ (3 шага) ══════════════════════

async def enter_card(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid  = update.effective_user.id
    text = update.message.text.strip()

    if not validate_phone(text):
        await update.message.reply_text(
            "❌ Неверный номер телефона.\n\n"
            "Номер должен начинаться с <b>89</b> или <b>+79</b> и содержать 11 цифр.\n"
            "Пример: <code>89161234567</code> или <code>+79161234567</code>",
            parse_mode="HTML"
        )
        return ENTER_REQUISITES

    context.user_data["new_phone"] = format_phone(text)
    context.user_data["action"]   = "set_bank"
    await update.message.reply_text(
        "🏦 <b>Шаг 2 из 3 — Банк</b>\n\n"
        "Введите название банка (например: Сбербанк, Тинькофф, ВТБ):",
        parse_mode="HTML"
    )
    return ENTER_BANK

async def enter_bank(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid  = update.effective_user.id
    text = update.message.text.strip()

    if len(text) < 2 or len(text) > 50 or any(c.isdigit() for c in text):
        await update.message.reply_text(
            "❌ Название банка не должно содержать цифры и должно быть от 2 до 50 символов.\n\n"
            "Введите ещё раз:"
        )
        return ENTER_BANK

    context.user_data["new_bank"] = text
    context.user_data["action"]   = "set_name"
    await update.message.reply_text(
        "👤 <b>Шаг 3 из 3 — Получатель</b>\n\n"
        "Введите фамилию и имя владельца карты (как на карте):\n"
        "Пример: <code>Иванов Иван</code>",
        parse_mode="HTML"
    )
    return ENTER_NAME

async def enter_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid  = update.effective_user.id
    text = update.message.text.strip()

    parts = text.split()
    if len(parts) < 2 or any(c.isdigit() for c in text):
        await update.message.reply_text(
            "❌ Введите фамилию и имя через пробел, без цифр.\n\n"
            "Пример: <code>Иванов Иван</code>",
            parse_mode="HTML"
        )
        return ENTER_NAME

    phone = context.user_data.get("new_phone")
    bank = context.user_data.get("new_bank")
    name = text

    user = get_user(uid)
    user["requisites"] = phone
    user["bank"]       = bank
    user["full_name"]  = name
    save_user(uid, user)

    context.user_data.pop("action",    None)
    context.user_data.pop("new_phone", None)
    context.user_data.pop("new_bank",  None)

    await update.message.reply_text(
        f"✅ <b>Реквизиты сохранены!</b>\n\n"
        f"📱 Телефон: <b>{phone}</b>\n"
        f"🏦 Банк: <b>{bank}</b>\n"
        f"👤 Получатель: <b>{name}</b>",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("← В настройки", callback_data="settings")
        ]])
    )
    return MAIN


# ══════════════════════ ВВОД ADMIN ══════════════════════

async def admin_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid    = update.effective_user.id
    if not is_admin(uid):
        return MAIN
    action = context.user_data.get("admin_action")

    if action == ACT_ADD_BALANCE:
        parts = update.message.text.strip().split()
        if len(parts) != 2:
            await update.message.reply_text("❌ Неверный формат. Нужно: ID пробел сумма")
            return ADMIN_EDIT
        try:
            tid, amount = int(parts[0]), float(parts[1])
        except:
            await update.message.reply_text("❌ ID и сумма должны быть числами.")
            return ADMIN_EDIT
        user = get_user(tid)
        user["balance"] = user.get("balance", 0) + amount
        add_history(user, amount, "admin_add")
        save_user(tid, user)
        try:
            await context.bot.send_message(
                tid,
                f"💰 Вам начислено <b>{amount:.2f}₽</b>.\n"
                f"Текущий баланс: <b>{user['balance']:.2f}₽</b>",
                parse_mode="HTML"
            )
        except:
            pass
        context.user_data.pop("admin_action", None)
        await update.message.reply_text(
            f"✅ Начислено {amount:.2f}₽ → ID {tid}",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("← В панель", callback_data="admin")
            ]])
        )
        return MAIN
    return MAIN


# ══════════════════════ ПАНЕЛЬ АДМИНА ══════════════════════

async def show_admin(query):
    users       = load(USERS_FILE, {})
    withdrawals = load(WITHDRAW_FILE, {})
    pending     = sum(1 for w in withdrawals.values() if w["status"] == "pending")
    await query.edit_message_text(
        f"🔧 <b>Администратор</b>\n\n"
        f"👥 Пользователей: {len(users)}\n"
        f"💸 Заявок на вывод: {pending}",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton(f"💸 Заявки ({pending})", callback_data="admin_withdrawals")],
            [InlineKeyboardButton("📊 Статистика",          callback_data="admin_stats")],
            [InlineKeyboardButton("💰 Начислить баланс",    callback_data="admin_add_balance")],
            [InlineKeyboardButton("← Главное меню",         callback_data="back")],
        ])
    )

async def admin_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not is_admin(uid):
        await update.message.reply_text("У вас нет прав для этого действия.")
        return MAIN
    users       = load(USERS_FILE, {})
    withdrawals = load(WITHDRAW_FILE, {})
    pending     = sum(1 for w in withdrawals.values() if w["status"] == "pending")
    await update.message.reply_text(
        f"🔧 <b>Администратор</b>\n\n"
        f"👥 Пользователей: {len(users)}\n"
        f"💸 Заявок на вывод: {pending}",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton(f"💸 Заявки ({pending})", callback_data="admin_withdrawals")],
            [InlineKeyboardButton("📊 Статистика",          callback_data="admin_stats")],
            [InlineKeyboardButton("💰 Начислить баланс",    callback_data="admin_add_balance")],
        ])
    )
    return MAIN


# ══════════════════════ MAIN ══════════════════════

def main():
    app = Application.builder().token(BOT_TOKEN).build()

    conv = ConversationHandler(
        entry_points=[
            CommandHandler("start", start),
            CommandHandler("admin", admin_cmd),
        ],
        states={
            MAIN: [CallbackQueryHandler(cb)],
            ENTER_REQUISITES: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, enter_card),
                CallbackQueryHandler(cb),
            ],
            ENTER_BANK: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, enter_bank),
                CallbackQueryHandler(cb),
            ],
            ENTER_NAME: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, enter_name),
                CallbackQueryHandler(cb),
            ],
            ADMIN_EDIT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, admin_text),
                CallbackQueryHandler(cb),
            ],
        },
        fallbacks=[
            CommandHandler("start", start),
            CommandHandler("admin", admin_cmd),
        ],
    )
    app.add_handler(conv)

    # Слушаем вступления в канал (для начисления рефералов)
    # Вступления в канал отслеживает verify_bot.py
    app.run_polling()

if __name__ == "__main__":
    main()
