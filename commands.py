"""Canonical text-command registry for MafiaNights.

This module owns lightweight text commands that are not part of the legacy game
state-machine handlers. It is deliberately registered against the production
``main1.dp`` dispatcher by ``player_runtime_entry.py``; it no longer creates a
separate Dispatcher at import time.
"""
from __future__ import annotations

import html
import logging
from typing import Any, Awaitable, Callable

from aiogram import types
from aiogram.dispatcher.handler import CancelHandler


CommandHandler = Callable[[types.Message], Awaitable[None]]

# Canonical command name -> aliases. Keep aliases here so every spelling maps
# to exactly one implementation.
COMMANDS = {
    "tag_all": {"تگ همه", "tag all"},
    "tag_admins": {"تگ ادمین", "tag admins"},
    "tag_list": {"تگ لیست", "tag list"},
}


def normalize_text(value: str | None) -> str:
    """Normalize Persian/English command text consistently."""
    text = (value or "").strip().replace("‌", " ")
    text = " ".join(text.split())
    if text.startswith("/"):
        text = text[1:]
    return text.casefold()


def resolve_command(value: str | None) -> str | None:
    normalized = normalize_text(value)
    for command, aliases in COMMANDS.items():
        if normalized in {normalize_text(alias) for alias in aliases}:
            return command
    return None


def _group_id(app: Any, message: types.Message) -> int | None:
    """Use the current group when invoked there, otherwise the configured game group."""
    if message.chat.type in {"group", "supergroup"}:
        return message.chat.id
    for key in ("group_chat_id", "ALLOWED_GROUP_ID", "GROUP_ID", "group_id"):
        value = getattr(app, key, None)
        if value:
            try:
                return int(value)
            except (TypeError, ValueError):
                pass
    return None


def _known_players(app: Any, group_id: int | None) -> dict[int, Any]:
    """Return players known to the active game, optionally scoped to the group."""
    players = getattr(app, "players", {}) or {}
    if not isinstance(players, dict):
        return {}
    return {int(uid): value for uid, value in players.items() if str(uid).lstrip("-").isdigit()}


def _display_name(app: Any, uid: int, fallback: Any = "❓") -> str:
    try:
        fn = getattr(app, "display_name", None)
        if callable(fn):
            value = fn(uid, fallback)
            if value:
                return str(value)
    except Exception:
        logging.exception("text command: display_name failed")
    if isinstance(fallback, dict):
        return str(fallback.get("nickname") or fallback.get("full_name") or fallback.get("first_name") or "❓")
    return str(fallback or "❓")


def _mention(uid: int, name: str) -> str:
    return f"<a href='tg://user?id={uid}'>{html.escape(name)}</a>"


async def cmd_tag_all(message: types.Message, app: Any) -> None:
    if message.chat.type not in {"group", "supergroup"}:
        await message.reply("⚠️ این دستور فقط داخل گروه قابل استفاده است.")
        return

    players = _known_players(app, message.chat.id)
    if not players:
        await message.reply("ℹ️ هنوز بازیکنی برای تگ‌کردن ثبت نشده است.")
        return

    mentions = [_mention(uid, _display_name(app, uid, value)) for uid, value in players.items()]
    await message.reply("🔔 <b>تگ بازیکنان شناخته‌شده:</b>\n" + "، ".join(mentions), parse_mode="HTML")


async def cmd_tag_admins(message: types.Message, app: Any) -> None:
    if message.chat.type not in {"group", "supergroup"}:
        await message.reply("⚠️ این دستور فقط داخل گروه قابل استفاده است.")
        return

    try:
        admins = await app.bot.get_chat_administrators(message.chat.id)
    except Exception:
        logging.exception("text command: failed to fetch administrators")
        await message.reply("❌ دریافت لیست مدیران گروه انجام نشد.")
        return

    if not admins:
        await message.reply("ℹ️ مدیر فعالی پیدا نشد.")
        return

    mentions = [_mention(a.user.id, a.user.full_name or str(a.user.id)) for a in admins]
    await message.reply("🛡 <b>مدیران گروه:</b>\n" + "، ".join(mentions), parse_mode="HTML")


async def cmd_tag_players(message: types.Message, app: Any) -> None:
    await cmd_tag_all(message, app)


async def run_command(name: str, message: types.Message, app: Any) -> None:
    handlers = {
        "tag_all": cmd_tag_all,
        "tag_admins": cmd_tag_admins,
        "tag_list": cmd_tag_players,
    }
    handler = handlers.get(name)
    if handler:
        await handler(message, app)


def register_commands(app: Any) -> bool:
    """Register canonical text commands on the application's real Dispatcher."""
    dp = getattr(app, "dp", None)
    if dp is None or getattr(app, "_canonical_text_commands_installed", False):
        return False

    @dp.message_handler(lambda m: bool(resolve_command(getattr(m, "text", None))), state="*")
    async def handle_text_commands(message: types.Message):
        name = resolve_command(message.text)
        if not name:
            return
        await run_command(name, message, app)
        raise CancelHandler()

    app._canonical_text_commands_installed = True
    logging.info("Canonical text-command registry installed")
    return True
