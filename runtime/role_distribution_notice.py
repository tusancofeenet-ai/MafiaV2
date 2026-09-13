"""Audit notice after successful role distribution."""
from __future__ import annotations

import html
import logging


def install(app):
    if getattr(app, "_role_distribution_notice_installed", False):
        return False
    handlers = getattr(getattr(app.dp, "callback_query_handlers", None), "handlers", None)
    if handlers is None:
        return False
    for item in handlers:
        fn = getattr(item, "handler", None)
        name = getattr(fn, "__name__", "")
        if "distribute_roles" not in name or getattr(fn, "_role_distribution_notice_wrapped", False):
            continue
        original = fn

        async def audited(callback):
            result = await original(callback)
            try:
                gid = int(getattr(app, "group_chat_id", 0) or 0)
                if gid:
                    moderator = getattr(app, "moderator_id", None)
                    mod_name = app.display_name(moderator, None) if moderator else "—"
                    await app.bot.send_message(
                        gid,
                        f"🎭 <b>اطلاع‌رسانی امنیتی</b>\nنقش‌ها توسط گرداننده ({html.escape(str(mod_name or '—'))}) پخش شد.",
                        parse_mode="HTML",
                    )
            except Exception as exc:
                logging.warning("role distribution notice failed: %s", exc)
            return result

        audited.__name__ = name
        audited._role_distribution_notice_wrapped = True
        item.handler = audited
        app._role_distribution_notice_installed = True
        logging.info("Role distribution audit notice installed on %s", name)
        return True
    logging.warning("Role distribution notice: handler not found")
    return False
