from __future__ import annotations

import logging
from functools import wraps

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def _handler(item):
    return getattr(item, "handler", None)


def _find(registry, name):
    for item in registry:
        if getattr(_handler(item), "__name__", "") == name:
            return item
    return None


def install(main):
    registry = getattr(getattr(main.dp, "callback_query_handlers", None), "handlers", None)
    if registry is None:
        logging.error("Seat emoji patch: callback registry unavailable")
        return

    item = _find(registry, "seat_menu")
    if item is None:
        logging.warning("Seat emoji patch: seat_menu handler not found")
        return

    original = _handler(item)
    if getattr(original, "_seat_emoji_patch", False):
        return

    @wraps(original)
    async def seat_menu_chairs(callback, _original=original):
        uid = callback.from_user.id
        if uid not in main.players or uid in main.waiting_list:
            await callback.answer("ابتدا وارد بازی شوید.", show_alert=True)
            return

        kb = InlineKeyboardMarkup(row_width=3)
        occupied = dict(main.player_slots)
        for seat in range(1, int(main.MAX_SEATS or 0) + 1):
            # Empty and self-selected seats use the chair emoji. A locked seat
            # keeps the lock indicator so users can distinguish unavailable seats.
            if seat in occupied and occupied[seat] != uid:
                icon = "🔒"
            else:
                icon = "🪑"
            kb.insert(InlineKeyboardButton(f"{seat:02d} {icon}", callback_data=f"lv6_seat:{seat}"))

        kb.add(InlineKeyboardButton("⬅️ بازگشت", callback_data="lv6_back_lobby"))
        try:
            await callback.message.edit_text("🪑 <b>انتخاب صندلی</b>", reply_markup=kb, parse_mode="HTML")
        except Exception:
            await callback.message.edit_reply_markup(reply_markup=kb)
        await callback.answer()

    seat_menu_chairs._seat_emoji_patch = True
    item.handler = seat_menu_chairs
    try:
        registry.insert(0, registry.pop(registry.index(item)))
    except ValueError:
        pass

    main._seat_emoji_patch = True
    logging.info("Seat emoji patch installed")
