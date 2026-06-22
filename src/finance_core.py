"""
finance_core.py — вся бизнес-логика менеджера финансов.
Не зависит от Telegram, можно использовать в любом интерфейсе.
"""

import json
import os
from datetime import datetime
from collections import defaultdict

DATA_FILE = "transactions.json"

CATEGORIES = {
    "income":  ["💼 Зарплата", "💻 Фриланс", "🎁 Подарок", "📈 Инвестиции", "❓ Другое"],
    "expense": ["🍕 Еда", "🚗 Транспорт", "🏠 Жильё", "🎮 Развлечения",
                "💊 Здоровье", "👗 Одежда", "📚 Образование", "❓ Другое"],
}


# ─── Хранилище ───────────────────────────────────────────────────────────────

def load_data() -> list[dict]:
    if not os.path.exists(DATA_FILE):
        return []
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_data(transactions: list[dict]) -> None:
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(transactions, f, ensure_ascii=False, indent=2)


# ─── CRUD ────────────────────────────────────────────────────────────────────

def add_transaction(transactions: list[dict], kind: str, amount: float,
                    category: str, note: str) -> dict:
    # Генерируем уникальный ID (не просто len, чтобы не ломалось после удалений)
    next_id = max((tx["id"] for tx in transactions), default=0) + 1
    tx = {
        "id": next_id,
        "type": kind,
        "amount": round(amount, 2),
        "category": category,
        "note": note,
        "date": datetime.now().strftime("%Y-%m-%d %H:%M"),
    }
    transactions.append(tx)
    save_data(transactions)
    return tx


def delete_transaction(transactions: list[dict], tx_id: int) -> bool:
    for i, tx in enumerate(transactions):
        if tx["id"] == tx_id:
            transactions.pop(i)
            save_data(transactions)
            return True
    return False


# ─── Аналитика ───────────────────────────────────────────────────────────────

def get_balance(transactions: list[dict]) -> float:
    total = sum(
        tx["amount"] if tx["type"] == "income" else -tx["amount"]
        for tx in transactions
    )
    return round(total, 2)


def get_summary(transactions: list[dict]) -> dict:
    total_income  = sum(tx["amount"] for tx in transactions if tx["type"] == "income")
    total_expense = sum(tx["amount"] for tx in transactions if tx["type"] == "expense")

    expense_by_cat: dict[str, float] = defaultdict(float)
    income_by_cat:  dict[str, float] = defaultdict(float)
    for tx in transactions:
        if tx["type"] == "expense":
            expense_by_cat[tx["category"]] += tx["amount"]
        else:
            income_by_cat[tx["category"]] += tx["amount"]

    return {
        "income":          round(total_income, 2),
        "expense":         round(total_expense, 2),
        "balance":         round(total_income - total_expense, 2),
        "expense_by_cat":  dict(expense_by_cat),
        "income_by_cat":   dict(income_by_cat),
    }


def filter_transactions(transactions: list[dict],
                        month: str | None = None,
                        kind:  str | None = None) -> list[dict]:
    result = transactions
    if month:
        result = [tx for tx in result if tx["date"].startswith(month)]
    if kind:
        result = [tx for tx in result if tx["type"] == kind]
    return result


# ─── Текстовые рендеры для Telegram ─────────────────────────────────────────

def render_balance(transactions: list[dict]) -> str:
    balance = get_balance(transactions)
    emoji = "📈" if balance >= 0 else "📉"
    sign  = "+" if balance >= 0 else ""
    return f"{emoji} <b>Текущий баланс:</b> <code>{sign}{balance:,.2f} ₽</code>"


def render_summary(transactions: list[dict]) -> str:
    if not transactions:
        return "📭 Транзакций пока нет. Добавь первую запись!"

    s = get_summary(transactions)

    lines = [
        "📊 <b>Статистика</b>",
        "",
        f"💚 Доходы:   <code>+{s['income']:>10,.2f} ₽</code>",
        f"❤️ Расходы:  <code>-{s['expense']:>10,.2f} ₽</code>",
        f"{'📈' if s['balance'] >= 0 else '📉'} Баланс:   "
        f"<code>{s['balance']:>+10,.2f} ₽</code>",
        "",
    ]

    if s["expense_by_cat"]:
        lines.append("🔴 <b>Расходы по категориям:</b>")
        max_val = max(s["expense_by_cat"].values()) or 1
        for cat, val in sorted(s["expense_by_cat"].items(), key=lambda x: -x[1]):
            bar = "▓" * int(val / max_val * 10)
            pct = val / s["expense"] * 100 if s["expense"] else 0
            lines.append(f"  {cat:<18} {bar:<10} {val:>8,.0f} ₽  ({pct:.0f}%)")
        lines.append("")

    if s["income_by_cat"]:
        lines.append("🟢 <b>Доходы по категориям:</b>")
        max_val = max(s["income_by_cat"].values()) or 1
        for cat, val in sorted(s["income_by_cat"].items(), key=lambda x: -x[1]):
            bar = "▓" * int(val / max_val * 10)
            pct = val / s["income"] * 100 if s["income"] else 0
            lines.append(f"  {cat:<18} {bar:<10} {val:>8,.0f} ₽  ({pct:.0f}%)")

    return "\n".join(lines)


def render_history(transactions: list[dict],
                   month: str | None = None,
                   kind:  str | None = None,
                   limit: int = 15) -> str:
    result = filter_transactions(transactions, month=month, kind=kind)
    if not result:
        return "📭 Транзакций не найдено."

    lines = [f"📋 <b>История</b> (последние {min(limit, len(result))} из {len(result)})\n"]
    for tx in result[-limit:]:
        sign  = "➕" if tx["type"] == "income" else "➖"
        lines.append(
            f"{sign} <code>#{tx['id']:>3}</code>  "
            f"<b>{tx['amount']:,.2f} ₽</b>  "
            f"{tx['category']}\n"
            f"     📅 {tx['date']}  📝 {tx['note']}"
        )
    return "\n".join(lines)
