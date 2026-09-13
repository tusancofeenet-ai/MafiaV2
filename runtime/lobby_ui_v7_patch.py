from __future__ import annotations

import html
import logging
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def install(main):
    """Small compatibility patch for legacy message-handler ordering."""
    dp = main.dp

    async def tag_list(message):
        if message.chat.type not in ("group", "supergroup"):
            return
        if not message.text or message.text.strip() != "تگ لیست":
            return
        if not main.lobby_active and not main.game_running:
            await message.reply("⚠️ بازی فعالی وجود ندارد.")
            return
        active = [uid for uid in main.players if uid not in main.waiting_list]
        if not active:
            await message.reply("👥 هیچ بازیکنی در بازی نیست.")
            return
        tags = []
        for uid in sorted(active, key=lambda x: next((s for s, p in main.player_slots.items() if p == x), 999)):
            try:
                name = main.display_name(uid, main.players.get(uid)) or str(uid)
            except Exception:
                name = main.players.get(uid) or str(uid)
            tags.append(f'<a href="tg://user?id={uid}">{html.escape(str(name))}</a>')
        await message.reply("📢 <b>تگ بازیکنان حاضر:</b>\n" + " ".join(tags), parse_mode="HTML")

    dp.register_message_handler(tag_list, lambda m: bool(m.text) and m.text.strip() == "تگ لیست")
    try:
        handlers = dp.message_handlers.handlers
        # This handler is appended last; put it before the legacy catch-all.
        if handlers and getattr(handlers[-1], "callback", None) is not None:
            handlers.insert(0, handlers.pop())
    except Exception as exc:
        logging.warning("could not prioritize tag-list handler: %s", exc)
