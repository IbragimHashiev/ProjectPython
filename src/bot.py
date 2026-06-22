"""
bot.py — Telegram-бот «Менеджер личных финансов»

Запуск:
  1. pip install python-telegram-bot
  2. Создай файл .env или задай переменную окружения BOT_TOKEN=<твой токен>
  3. python bot.py
"""

import os
import logging
from dotenv import load_dotenv

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ConversationHandler,
    ContextTypes,
    filters,
)

from finance_core import (
    load_data, add_transaction, delete_transaction,
    CATEGORIES, render_balance, render_summary, render_history,
)

load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN", "")

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# ─── Состояния диалогов ──────────────────────────────────────────────────────

# Добавление транзакции
ADD_AMOUNT, ADD_CATEGORY, ADD_NOTE = range(3)

# Удаление
DELETE_ID = 10

# История
HIST_FILTER = 20

# ─── Вспомогательные функции ─────────────────────────────────────────────────

def get_txs(context: ContextTypes.DEFAULT_TYPE) -> list[dict]:
    """Загружаем данные один раз и кешируем в user_data."""
    if "transactions" not in context.user_data:
        context.user_data["transactions"] = load_data()
    return context.user_data["transactions"]


def main_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("➕ Доход",   callback_data="add_income"),
            InlineKeyboardButton("➖ Расход",  callback_data="add_expense"),
        ],
        [
            InlineKeyboardButton("📋 История",  callback_data="history"),
            InlineKeyboardButton("📊 Статистика", callback_data="stats"),
        ],
        [
            InlineKeyboardButton("🗑 Удалить запись", callback_data="delete"),
        ],
    ])


def category_keyboard(kind: str) -> InlineKeyboardMarkup:
    cats = CATEGORIES[kind]
    rows = []
    for i in range(0, len(cats), 2):
        row = [InlineKeyboardButton(cats[i], callback_data=f"cat:{cats[i]}")]
        if i + 1 < len(cats):
            row.append(InlineKeyboardButton(cats[i + 1], callback_data=f"cat:{cats[i + 1]}"))
        rows.append(row)
    rows.append([InlineKeyboardButton("❌ Отмена", callback_data="cancel")])
    return InlineKeyboardMarkup(rows)


def history_filter_keyboard() -> InlineKeyboardMarkup:
    from datetime import datetime
    now = datetime.now()
    this_month = now.strftime("%Y-%m")
    prev = (now.month - 2) % 12 + 1
    prev_year = now.year if now.month > 1 else now.year - 1
    prev_month = f"{prev_year}-{prev:02d}"

    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("Все",          callback_data="hf:all:all"),
            InlineKeyboardButton("Этот месяц",   callback_data=f"hf:{this_month}:all"),
            InlineKeyboardButton("Прошлый месяц",callback_data=f"hf:{prev_month}:all"),
        ],
        [
            InlineKeyboardButton("Только доходы",  callback_data=f"hf:all:income"),
            InlineKeyboardButton("Только расходы", callback_data=f"hf:all:expense"),
        ],
        [InlineKeyboardButton("❌ Отмена", callback_data="cancel")],
    ])


async def send_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str = "") -> None:
    txs = get_txs(context)
    balance_line = render_balance(txs)
    full_text = f"{balance_line}\n\n{text}" if text else balance_line

    if update.callback_query:
        await update.callback_query.edit_message_text(
            full_text, reply_markup=main_keyboard(), parse_mode="HTML"
        )
    elif update.message:
        await update.message.reply_text(
            full_text, reply_markup=main_keyboard(), parse_mode="HTML"
        )


# ─── /start и /menu ──────────────────────────────────────────────────────────

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    name = update.effective_user.first_name or "друг"
    await send_main_menu(
        update, context,
        text=f"👋 Привет, <b>{name}</b>! Я помогу тебе вести учёт финансов.\n"
             f"Выбери действие ниже 👇"
    )


async def cmd_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await send_main_menu(update, context)


# ─── Добавление транзакции (ConversationHandler) ─────────────────────────────

async def cb_add_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    kind = "income" if query.data == "add_income" else "expense"
    context.user_data["add_kind"] = kind
    label = "дохода" if kind == "income" else "расхода"

    await query.edit_message_text(
        f"{'💰' if kind == 'income' else '💸'} <b>Добавление {label}</b>\n\n"
        f"Введи сумму в рублях (например: <code>1500</code> или <code>2499.90</code>):",
        parse_mode="HTML",
    )
    return ADD_AMOUNT


async def add_get_amount(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    raw = update.message.text.strip().replace(",", ".")
    try:
        amount = float(raw)
        if amount <= 0:
            raise ValueError
    except ValueError:
        await update.message.reply_text(
            "⚠️ Введи корректную сумму (положительное число).\n"
            "Например: <code>1500</code>",
            parse_mode="HTML",
        )
        return ADD_AMOUNT

    context.user_data["add_amount"] = amount
    kind = context.user_data["add_kind"]

    await update.message.reply_text(
        f"✅ Сумма: <b>{amount:,.2f} ₽</b>\n\nВыбери категорию:",
        reply_markup=category_keyboard(kind),
        parse_mode="HTML",
    )
    return ADD_CATEGORY


async def add_get_category(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    if query.data == "cancel":
        await send_main_menu(update, context, text="🚫 Отменено.")
        return ConversationHandler.END

    category = query.data.replace("cat:", "")
    context.user_data["add_category"] = category

    await query.edit_message_text(
        f"✅ Категория: <b>{category}</b>\n\n"
        f"Добавь заметку (или отправь <code>-</code> чтобы пропустить):",
        parse_mode="HTML",
    )
    return ADD_NOTE


async def add_get_note(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    note = update.message.text.strip()
    if note == "-":
        note = "—"

    txs  = get_txs(context)
    kind = context.user_data["add_kind"]
    amt  = context.user_data["add_amount"]
    cat  = context.user_data["add_category"]

    tx = add_transaction(txs, kind, amt, cat, note)

    emoji = "💰" if kind == "income" else "💸"
    confirm = (
        f"{emoji} <b>Записано!</b>\n\n"
        f"Сумма:     <code>{tx['amount']:,.2f} ₽</code>\n"
        f"Категория: {tx['category']}\n"
        f"Заметка:   {tx['note']}\n"
        f"Дата:      {tx['date']}"
    )
    await update.message.reply_text(confirm, parse_mode="HTML")
    await send_main_menu(update, context)
    return ConversationHandler.END


# ─── История ─────────────────────────────────────────────────────────────────

async def cb_history(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    txs = get_txs(context)
    if not txs:
        await query.edit_message_text(
            "📭 Транзакций пока нет.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🔙 Назад", callback_data="back")
            ]])
        )
        return ConversationHandler.END

    await query.edit_message_text(
        "📋 <b>История транзакций</b>\n\nВыбери фильтр:",
        reply_markup=history_filter_keyboard(),
        parse_mode="HTML",
    )
    return HIST_FILTER


async def cb_history_filter(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    if query.data == "cancel":
        await send_main_menu(update, context, text="🚫 Отменено.")
        return ConversationHandler.END

    _, month_raw, kind_raw = query.data.split(":")
    month = None if month_raw == "all" else month_raw
    kind  = None if kind_raw  == "all" else kind_raw

    txs  = get_txs(context)
    text = render_history(txs, month=month, kind=kind)

    await query.edit_message_text(
        text,
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("🔙 Главное меню", callback_data="back")
        ]])
    )
    return ConversationHandler.END


# ─── Статистика ──────────────────────────────────────────────────────────────

async def cb_stats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    txs  = get_txs(context)
    text = render_summary(txs)

    await query.edit_message_text(
        text,
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("🔙 Главное меню", callback_data="back")
        ]])
    )


# ─── Удаление транзакции ─────────────────────────────────────────────────────

async def cb_delete_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    txs = get_txs(context)
    if not txs:
        await send_main_menu(update, context, text="📭 Нечего удалять — транзакций нет.")
        return ConversationHandler.END

    # Показываем последние 10 для удобства
    recent = txs[-10:]
    lines = ["🗑 <b>Удаление записи</b>\n\nПоследние транзакции:\n"]
    for tx in reversed(recent):
        sign = "➕" if tx["type"] == "income" else "➖"
        lines.append(f"{sign} <code>#{tx['id']}</code>  {tx['amount']:,.2f} ₽  {tx['category']}  ({tx['date']})")
    lines.append("\nВведи <b>ID</b> записи для удаления:")

    await query.edit_message_text(
        "\n".join(lines),
        parse_mode="HTML",
    )
    return DELETE_ID


async def delete_get_id(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    raw = update.message.text.strip()
    if not raw.isdigit():
        await update.message.reply_text("⚠️ Введи числовой ID транзакции.")
        return DELETE_ID

    txs = get_txs(context)
    ok  = delete_transaction(txs, int(raw))

    if ok:
        await update.message.reply_text(f"✅ Транзакция #{raw} удалена.")
    else:
        await update.message.reply_text(f"❌ Транзакция с ID #{raw} не найдена.")

    await send_main_menu(update, context)
    return ConversationHandler.END


# ─── Кнопка «Назад» / общий cancel ──────────────────────────────────────────

async def cb_back(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await send_main_menu(update, context)


async def cb_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    if query:
        await query.answer()
    await send_main_menu(update, context, text="🚫 Действие отменено.")
    return ConversationHandler.END


async def msg_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text(
        "🚫 Отменено.",
        reply_markup=ReplyKeyboardRemove(),
    )
    await send_main_menu(update, context)
    return ConversationHandler.END


# ─── Сборка приложения ───────────────────────────────────────────────────────

def build_app() -> Application:
    app = Application.builder().token(BOT_TOKEN).build()

    # /start, /menu
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("menu",  cmd_menu))

    # ── Добавление транзакции ──
    add_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(cb_add_start, pattern=r"^add_(income|expense)$")],
        states={
            ADD_AMOUNT:   [MessageHandler(filters.TEXT & ~filters.COMMAND, add_get_amount)],
            ADD_CATEGORY: [CallbackQueryHandler(add_get_category, pattern=r"^(cat:.+|cancel)$")],
            ADD_NOTE:     [MessageHandler(filters.TEXT & ~filters.COMMAND, add_get_note)],
        },
        fallbacks=[
            CommandHandler("cancel", msg_cancel),
            CallbackQueryHandler(cb_cancel, pattern="^cancel$"),
        ],
        per_message=False,
    )

    # ── История ──
    history_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(cb_history, pattern="^history$")],
        states={
            HIST_FILTER: [CallbackQueryHandler(cb_history_filter, pattern=r"^(hf:.+|cancel)$")],
        },
        fallbacks=[
            CommandHandler("cancel", msg_cancel),
            CallbackQueryHandler(cb_cancel, pattern="^cancel$"),
        ],
        per_message=False,
    )

    # ── Удаление ──
    delete_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(cb_delete_start, pattern="^delete$")],
        states={
            DELETE_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, delete_get_id)],
        },
        fallbacks=[
            CommandHandler("cancel", msg_cancel),
            CallbackQueryHandler(cb_cancel, pattern="^cancel$"),
        ],
        per_message=False,
    )

    app.add_handler(add_conv)
    app.add_handler(history_conv)
    app.add_handler(delete_conv)

    # Статистика и «назад» — простые callback-хендлеры
    app.add_handler(CallbackQueryHandler(cb_stats, pattern="^stats$"))
    app.add_handler(CallbackQueryHandler(cb_back,  pattern="^back$"))

    return app


def main() -> None:
    if not BOT_TOKEN:
        print("❌ Не задан BOT_TOKEN!\n"
              "Создай файл .env со строкой BOT_TOKEN=<токен> или\n"
              "задай переменную окружения: export BOT_TOKEN=<токен>")
        return

    app = build_app()
    logger.info("Бот запущен. Нажми Ctrl+C для остановки.")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
