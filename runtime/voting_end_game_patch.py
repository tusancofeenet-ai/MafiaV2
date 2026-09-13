"""Expose the manual game-completion action after every voting session."""
from __future__ import annotations

from aiogram.dispatcher.handler import CancelHandler
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from runtime import voting_runtime


def install(main):
    dp = getattr(main, "dp", None)
    if dp is None or getattr(main, "_voting_end_game_patch_installed", False):
        return False

    async def end_voting(c):
        if int(c.from_user.id) != int(getattr(main, "moderator_id", -1) or -1):
            await c.answer("⛔ فقط گرداننده دسترسی دارد.", show_alert=True)
            raise CancelHandler()

        game = voting_runtime._game(main)
        gid = voting_runtime._gid(main)
        if not game or not gid:
            await c.answer("❌ بازی فعالی وجود ندارد.", show_alert=True)
            raise CancelHandler()

        voting = voting_runtime._v(main)
        voting["phase"], voting["deadline"] = "finished", None
        voting_runtime._put(main, voting)

        game_id = int(game["id"])
        markup = InlineKeyboardMarkup(row_width=1).add(
            InlineKeyboardButton("🏁 اتمام بازی", callback_data="end_game"),
            InlineKeyboardButton("🌙 شروع فاز شب", callback_data="start_night"),
        )
        await c.message.edit_text(
            "🏁 <b>رای‌گیری به پایان رسید.</b>\n\n"
            "اکنون می‌توانید بازی را به‌صورت دستی نهایی کنید یا وارد فاز شب شوید.",
            parse_mode="HTML",
            reply_markup=markup,
        )
        await c.answer()
        raise CancelHandler()

    dp.register_callback_query_handler(end_voting, lambda c: c.data == "vote:end", state="*")
    main._voting_end_game_patch_installed = True
    return True
