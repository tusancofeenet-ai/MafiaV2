"""Explicit text command for cancelling the current MafiaNights game."""
from __future__ import annotations

import logging
from typing import Any

from aiogram import types


ALIASES = {
    "لغو بازی",
    "/لغو_بازی",
    "/cancel_game",
    "/cancelgame",
}


def install(app: Any) -> bool:
    if getattr(app, "_cancel_command_installed", False):
        return False

    async def cancel_game(message: types.Message):
        gid = int(message.chat.id)
        game = app.runtime.state.active_game(gid)
        if not game:
            await message.reply("ℹ️ بازی فعالی برای لغو وجود ندارد.")
            return

        uid = int(message.from_user.id)
        moderator = int(game.get("moderator_id") or 0)
        allowed = uid == moderator
        if not allowed:
            try:
                member = await app.bot.get_chat_member(gid, uid)
                allowed = member.status in {"creator", "administrator"}
            except Exception:
                allowed = False
        if not allowed:
            await message.reply("⛔ فقط گرداننده یا مدیر گروه می‌تواند بازی را لغو کند.")
            return

        state = dict(game.get("state") or {})
        # Invalidate the durable game first; active_game() will then stop
        # exposing it and the next «بازی جدید» can create a fresh game.
        ok = app.runtime.state.games.update_game(game["id"], status="finished", state={})
        if not ok:
            await message.reply("❌ لغو بازی انجام نشد.")
            return

        try:
            app.runtime.state.games.clear_game_players(game["id"])
        except Exception:
            logging.exception("failed to clear cancelled game players game=%s", game.get("id"))

        for owner, attr in ((getattr(app, "ui", None), "turn_timer_task"), (app, "_voting_task")):
            task = getattr(owner, attr, None) if owner is not None else None
            if task is not None and hasattr(task, "done") and not task.done():
                task.cancel()

        lobby_message_id = state.get("lobby_message_id")
        if lobby_message_id:
            try:
                await app.bot.edit_message_text(
                    "🚫 <b>این بازی لغو شد.</b>",
                    gid,
                    int(lobby_message_id),
                    parse_mode="HTML",
                    reply_markup=None,
                )
            except Exception:
                logging.info("cancelled game message could not be edited game=%s", game.get("id"))

        await message.reply(
            f"🚫 <b>بازی شماره {int(game.get('event_number') or 1)} لغو شد.</b>\n"
            "اکنون می‌توانید «بازی جدید» را ایجاد کنید.",
            parse_mode="HTML",
        )

    app.dp.register_message_handler(
        cancel_game,
        lambda message: (message.text or "").strip().lower() in ALIASES,
        content_types=types.ContentTypes.TEXT,
        state="*",
    )
    app._cancel_command_installed = True
    logging.info("CANCEL_COMMAND installed: لغو بازی, /لغو_بازی, /cancel_game")
    return True
