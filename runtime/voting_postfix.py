"""Post-voting callbacks that must remain available after the voting handler cutover."""
from __future__ import annotations

from aiogram.dispatcher.handler import CancelHandler

from runtime import voting_runtime


def install(main):
    dp = getattr(main, "dp", None)
    if dp is None or getattr(main, "_voting_postfix_installed", False):
        return False

    async def only_mod(c):
        if int(c.from_user.id) != int(getattr(main, "moderator_id", -1) or -1):
            await c.answer("⛔ فقط گرداننده دسترسی دارد.", show_alert=True)
            raise CancelHandler()

    async def night(c):
        await only_mod(c)
        rt = getattr(main, "runtime", None)
        gid = voting_runtime._gid(main)
        if rt and gid:
            rt.days.start_night(gid)
        await c.answer("🌙 فاز شب شروع شد.")
        raise CancelHandler()

    dp.register_callback_query_handler(night, lambda c: c.data == "start_night", state="*")
    main._voting_postfix_installed = True
    return True
