from __future__ import annotations

import html
from aiogram.dispatcher.handler import CancelHandler
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from repositories.scenario_repository import ScenarioRepository


def install(app):
    dp = app.dp
    reg = getattr(getattr(dp, "callback_query_handlers", None), "handlers", None)
    if reg is None or getattr(app, "_game_info_security_v2", False):
        return False
    app._game_info_security_v2 = True
    scenarios = ScenarioRepository()

    def name(row):
        return str(row.get("nickname") or row.get("first_name") or row.get("username") or row.get("player_id") or "👤")

    async def allowed_moderator(callback, game):
        return callback.message.chat.type == "private" and int(callback.from_user.id) == int(game.get("moderator_id") or -1)

    async def info(callback):
        parts = str(callback.data or "").split(":")
        if len(parts) != 3 or parts[0] != "game_info":
            return
        game = app.runtime.state.games.get_game(int(parts[1]))
        if not game:
            await callback.answer("❌ بازی پیدا نشد.", show_alert=True)
            raise CancelHandler()
        rows = app.runtime.state.games.list_players(int(game["id"]))
        state = dict(game.get("state") or {})
        scenario_name = state.get("scenario_name")
        if not scenario_name:
            sid = game.get("scenario_id")
            try:
                scenario_name = (scenarios.get_by_id(int(sid)) or {}).get("name")
            except Exception:
                scenario_name = None
        scenario_name = scenario_name or "---"
        action = parts[2]
        if action == "players":
            private_roles = await allowed_moderator(callback, game)
            # Active-game roles are strictly private/moderator-only. Public lists never contain roles.
            lines = [f"👥 <b>لیست بازیکنان بازی {int(game.get('event_number') or 1)}</b>", ""]
            for row in sorted(rows, key=lambda r: int(r.get("seat") or 999)):
                seat = int(row.get("seat") or 0)
                text = f"{seat:02d}. <b>{html.escape(name(row))}</b>"
                if private_roles:
                    text += f" — نقش: <b>{html.escape(str(row.get('role') or '---'))}</b>"
                lines.append(text)
            if not private_roles and str(game.get("status") or "") in {"lobby", "running", "paused"}:
                lines.append("\n🔒 نقش‌های بازی فعال فقط در پیوی برای گرداننده قابل مشاهده است.")
            kb = InlineKeyboardMarkup(row_width=2).add(
                InlineKeyboardButton("📊 آمار بازی", callback_data=f"game_info:{game['id']}:stats"),
                InlineKeyboardButton("ℹ️ اطلاعات کلی", callback_data=f"game_info:{game['id']}:overview"),
            )
            await callback.message.edit_text("\n".join(lines), parse_mode="HTML", reply_markup=kb)
            await callback.answer()
            raise CancelHandler()
        if action == "overview":
            start = game.get("started_at") or game.get("created_at") or "---"
            await callback.message.edit_text(
                f"🎮 <b>اطلاعات بازی {int(game.get('event_number') or 1)}</b>\n\n"
                f"📌 وضعیت: <b>{html.escape(str(game.get('status') or '---'))}</b>\n"
                f"🎭 سناریو: <b>{html.escape(str(scenario_name))}</b>\n"
                f"👥 بازیکنان: <b>{len(rows)}</b>\n"
                f"▶️ شروع: <b>{html.escape(str(start))}</b>",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup(row_width=2).add(
                    InlineKeyboardButton("👥 لیست بازی", callback_data=f"game_info:{game['id']}:players"),
                    InlineKeyboardButton("📊 آمار بازی", callback_data=f"game_info:{game['id']}:stats"),
                ),
            )
            await callback.answer()
            raise CancelHandler()
        # Keep stats/events public-safe by delegating to the existing archive owner for those views.
        return

    dp.register_callback_query_handler(info, lambda c: str(c.data or "").startswith("game_info:"), state="*")
    for i, item in enumerate(reg):
        if getattr(item, "callback", None) is info:
            reg.insert(0, reg.pop(i))
            break
    return True
