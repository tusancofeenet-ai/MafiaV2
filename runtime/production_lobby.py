```python
"""Canonical production lobby.

There is exactly one Telegram Lobby owner.

Lifecycle:
    new game -> scenario -> moderator -> public lobby -> gameplay

All mutating callbacks carry the durable game id so stale Telegram buttons
cannot mutate a newer game in the same group.
"""

from __future__ import annotations

import html
import logging
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from aiogram import types
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from repositories.scenario_repository import ScenarioRepository


logger = logging.getLogger(__name__)


# Handler names belonging to previous Lobby implementations.
#
# Keep this list intentionally broad. The canonical Lobby must be the only
# owner of Lobby callbacks in production.
LEGACY_HANDLER_NAMES = {
    "new_game",
    "join",
    "leave",
    "choose_scenario",
    "scenario_selected",
    "moderator_selected",
    "slot",
    "seat",
    "reserve",
    "change_scenario",
    "change_moderator",
    "cancel_game",
    "management",
    "event_number_menu",
    "event_number_adjust",
    "event_menu",
    "event_adjust",
    "refresh_lobby",
    "refresh",
    "back_lobby",
    "back",
    "legacy_join",
    "legacy_leave",
    "waiting_join",
    "waiting_leave",
    "toggle_join",
    "distribute",
}


def _remove_legacy_handlers(dp) -> int:
    """Remove known legacy Lobby handlers before installing the canonical one.

    aiogram 2 stores callback handlers in ``callback_query_handlers.handlers``.
    We deliberately preserve handlers that do not belong to the known legacy
    Lobby implementation.
    """

    manager = getattr(dp, "callback_query_handlers", None)
    table = getattr(manager, "handlers", None)

    if table is None:
        logger.warning(
            "CANONICAL_LOBBY_HANDLER_TABLE_NOT_FOUND"
        )
        return 0

    kept = []
    removed = 0

    for item in list(table):
        callback = getattr(item, "callback", None)
        name = getattr(callback, "__name__", "")

        if name in LEGACY_HANDLER_NAMES:
            removed += 1
            continue

        kept.append(item)

    table[:] = kept

    return removed


def _is_message_not_modified(exc: Exception) -> bool:
    return "message is not modified" in str(exc).lower()


def install(app: Any) -> bool:
    """Install the single canonical production Lobby."""

    if getattr(app, "_canonical_production_lobby_installed", False):
        logger.info("CANONICAL_PRODUCTION_LOBBY_ALREADY_ACTIVE")
        return False

    dp = app.dp
    bot = app.bot
    scenario_repo = ScenarioRepository()

    removed = _remove_legacy_handlers(dp)

    logger.info(
        "CANONICAL_LOBBY_INSTALL removed_legacy_handlers=%d",
        removed,
    )

    # Prevent duplicate installation from this module.
    app._canonical_production_lobby_installed = True

    if not hasattr(app, "_lobby_render_locks"):
        app._lobby_render_locks = {}

    def group_id(callback: types.CallbackQuery) -> int:
        if callback.message is None:
            raise RuntimeError("CallbackQuery has no message")

        return int(callback.message.chat.id)

    def current_game(gid: int) -> dict[str, Any] | None:
        return app.runtime.state.active_game(int(gid))

    def snapshot(gid: int) -> dict[str, Any]:
        return app.runtime.lobby_snapshot(int(gid))

    def scenario_info(
        scenario_id: Any,
    ) -> dict[str, Any] | None:
        if scenario_id is None:
            return None

        try:
            return scenario_repo.get_by_id(int(scenario_id))
        except (TypeError, ValueError):
            return scenario_repo.get_by_name(str(scenario_id))

    def scenario_name(scenario_id: Any) -> str:
        row = scenario_info(scenario_id)
        return str(
            (row or {}).get("name")
            or scenario_id
            or "---"
        )

    def capacity(game: dict[str, Any]) -> int:
        row = scenario_info(game.get("scenario_id"))
        roles = (row or {}).get("roles") or []
        return len(roles)

    def player_name(row: dict[str, Any]) -> str:
        return str(
            row.get("nickname")
            or row.get("first_name")
            or row.get("username")
            or row.get("player_id")
            or "👤"
        )

    def mention(
        uid: int,
        label: str | None = None,
    ) -> str:
        return (
            f'<a href="tg://user?id={int(uid)}">'
            f"<b>{html.escape(str(label or uid))}</b>"
            "</a>"
        )

    async def is_manager(
        callback: types.CallbackQuery,
        game: dict[str, Any] | None = None,
    ) -> bool:
        gid = group_id(callback)
        uid = int(callback.from_user.id)

        game = game or current_game(gid)

        moderator_id = int(
            (game or {}).get("moderator_id") or 0
        )

        if uid == moderator_id:
            return True

        try:
            member = await bot.get_chat_member(gid, uid)

            return member.status in {
                "creator",
                "administrator",
            }

        except Exception:
            logger.exception(
                "manager_check_failed group=%s user=%s",
                gid,
                uid,
            )
            return False

    def require_game(
        callback: types.CallbackQuery,
        expected_id: int | None = None,
        *,
        lobby_only: bool = True,
    ):
        gid = group_id(callback)
        game = current_game(gid)

        if not game:
            return None, "❌ بازی فعالی وجود ندارد."

        current_id = int(game.get("id") or 0)

        if (
            expected_id is not None
            and current_id != int(expected_id)
        ):
            return None, "⚠️ این دکمه مربوط به بازی قبلی است."

        if (
            lobby_only
            and str(game.get("status") or "") != "lobby"
        ):
            return None, "❌ لابی فعال نیست."

        return game, None

    def parse_callback(
        callback: types.CallbackQuery,
        prefix: str,
        parts: int,
    ) -> list[str] | None:
        values = str(callback.data or "").split(":")

        if len(values) != parts:
            return None

        if values[0] != prefix:
            return None

        return values

    def lobby_state(
        game: dict[str, Any],
    ) -> dict[str, Any]:
        return dict(game.get("state") or {})

    def save_lobby_state(
        game: dict[str, Any],
        **changes: Any,
    ) -> bool:
        state = lobby_state(game)
        state.update(changes)

        return bool(
            app.runtime.state.games.update_game(
                game["id"],
                state=state,
            )
        )

    def scenario_keyboard(
        game_id: int,
    ) -> InlineKeyboardMarkup:
        kb = InlineKeyboardMarkup(row_width=1)

        for row in scenario_repo.list_active():
            sid = int(row["id"])
            name = str(row.get("name") or sid)
            roles = row.get("roles") or []

            kb.add(
                InlineKeyboardButton(
                    f"📝 {name} ({len(roles)})",
                    callback_data=(
                        f"lobby:{game_id}:scenario:{sid}"
                    ),
                )
            )

        return kb

    async def render(
        gid: int,
        game: dict[str, Any] | None = None,
    ) -> bool:
        """Render the canonical lobby message."""

        game = game or current_game(gid)

        if not game:
            return False

        if str(game.get("status") or "") != "lobby":
            return False

        if (
            not game.get("scenario_id")
            or not game.get("moderator_id")
        ):
            return False

        data = snapshot(gid)

        game = data.get("game") or game

        cap = capacity(game)
        rows = data.get("players") or []

        active = [
            row
            for row in rows
            if (
                row.get("seat") is not None
                and str(row.get("status") or "active")
                not in {"removed", "dead", "finished"}
            )
        ]

        waiting = [
            row
            for row in rows
            if (
                row.get("seat") is None
                and str(row.get("status") or "waiting")
                == "waiting"
            )
        ]

        active.sort(
            key=lambda row: int(
                row.get("seat") or 999
            )
        )

        occupied = {
            int(row["seat"]): row
            for row in active
        }

        moderator_id = int(game["moderator_id"])

        moderator_row = next(
            (
                row
                for row in rows
                if int(row.get("player_id") or 0)
                == moderator_id
            ),
            None,
        )

        moderator_name = (
            player_name(moderator_row)
            if moderator_row
            else None
        )

        if (
            not moderator_name
            or moderator_name == str(moderator_id)
        ):
            try:
                member = await bot.get_chat_member(
                    gid,
                    moderator_id,
                )

                moderator_name = (
                    member.user.full_name
                    or member.user.username
                    or str(moderator_id)
                )

            except Exception:
                logger.exception(
                    "moderator_lookup_failed group=%s user=%s",
                    gid,
                    moderator_id,
                )
                moderator_name = str(moderator_id)

        lines = [
            "༄ <b>لیست بازی Mafia Nights</b>",
            "",
            (
                "📅 <b>تاریخ:</b> "
                f"{datetime.now(ZoneInfo('Asia/Tehran')).strftime('%Y/%m/%d')}"
            ),
            (
                "🎭 <b>سناریو:</b> "
                f"{html.escape(scenario_name(game.get('scenario_id')))}"
            ),
            (
                "🔢 <b>شماره بازی:</b> "
                f"{int(game.get('event_number') or 1)}"
            ),
            (
                "🎩 <b>گرداننده:</b> "
                f"{mention(moderator_id, moderator_name)}"
            ),
            "",
            "━━━━━━━━━━━━━━━━━━",
            f"👥 <b>بازیکنان:</b> {len(active)}/{cap}",
            "",
            "🪑 <b>لیست صندلی‌ها</b>",
        ]

        for seat_no in range(1, cap + 1):
            row = occupied.get(seat_no)

            if row:
                label = mention(
                    int(row["player_id"]),
                    player_name(row),
                )
            else:
                label = "⬜ آزاد"

            lines.append(
                f"{seat_no:02d}. {label}"
            )

        if waiting:
            lines.extend(
                [
                    "",
                    "🎟 <b>لیست رزرو</b>",
                ]
            )

            for index, row in enumerate(
                waiting,
                1,
            ):
                lines.append(
                    f"{index}. "
                    f"{mention(int(row['player_id']), player_name(row))}"
                )

        lines.extend(
            [
                "",
                "━━━━━━━━━━━━━━━━━━",
                "༄",
            ]
        )

        keyboard = InlineKeyboardMarkup(
            row_width=3
        )

        for seat_no in range(1, cap + 1):
            row = occupied.get(seat_no)

            label = (
                f"{seat_no:02d} "
                f"{player_name(row)[:10]}"
                if row
                else f"{seat_no:02d} ⬜"
            )

            keyboard.insert(
                InlineKeyboardButton(
                    label,
                    callback_data=(
                        f"lobby:{int(game['id'])}:seat:{seat_no}"
                    ),
                )
            )

        keyboard.row(
            InlineKeyboardButton(
                "🚪 ورود / خروج",
                callback_data=(
                    f"lobby:{int(game['id'])}:toggle"
                ),
            )
        )

        if len(active) >= cap > 0:
            keyboard.row(
                InlineKeyboardButton(
                    "🎟 رزرو / لغو رزرو",
                    callback_data=(
                        f"lobby:{int(game['id'])}:reserve"
                    ),
                )
            )

            keyboard.row(
                InlineKeyboardButton(
                    "🎭 پخش نقش",
                    callback_data=(
                        f"lobby:{int(game['id'])}:distribute"
                    ),
                )
            )

        keyboard.row(
            InlineKeyboardButton(
                "⚙️ مدیریت بازی",
                callback_data=(
                    f"lobby:{int(game['id'])}:management"
                ),
            )
        )

        keyboard.row(
            InlineKeyboardButton(
                "🚫 لغو بازی",
                callback_data=(
                    f"lobby:{int(game['id'])}:cancel"
                ),
            )
        )

        state = lobby_state(game)
        message_id = state.get("lobby_message_id")

        text_body = "\n".join(lines)

        try:
            if message_id:
                await bot.edit_message_text(
                    text_body,
                    gid,
                    int(message_id),
                    parse_mode="HTML",
                    reply_markup=keyboard,
                )

                return True

            message = await bot.send_message(
                gid,
                text_body,
                parse_mode="HTML",
                reply_markup=keyboard,
            )

            save_lobby_state(
                game,
                lobby_message_id=int(
                    message.message_id
                ),
            )

            return True

        except Exception as exc:
            if _is_message_not_modified(exc):
                return True

            logger.warning(
                "lobby_render_failed game=%s group=%s: %s",
                game.get("id"),
                gid,
                exc,
            )

            # Only replace the message if an existing message was known
            # but Telegram rejected the edit. If there was no message ID,
            # the original send failed and a retry is appropriate.
            try:
                message = await bot.send_message(
                    gid,
                    text_body,
                    parse_mode="HTML",
                    reply_markup=keyboard,
                )

                save_lobby_state(
                    game,
                    lobby_message_id=int(
                        message.message_id
                    ),
                )

                return True

            except Exception:
                logger.exception(
                    "lobby_replacement_send_failed "
                    "game=%s group=%s",
                    game.get("id"),
                    gid,
                )

                return False

    app._render_production_lobby = render
    app._production_lobby_render = render
    app._production_lobby_game_id = current_game

    async def new_game(callback: types.CallbackQuery):
        gid = group_id(callback)

        if not await is_manager(callback):
            await callback.answer(
                "⛔ فقط گرداننده یا مدیر گروه می‌تواند بازی جدید ایجاد کند.",
                show_alert=True,
            )
            return

        try:
            game = app.runtime.lobby.start_new(gid)

            message = callback.message

            if message is None:
                await callback.answer(
                    "❌ پیام ایجاد بازی معتبر نیست.",
                    show_alert=True,
                )
                return

            await message.edit_text(
                "📝 <b>انتخاب سناریو</b>\n\n"
                "سناریوی بازی را انتخاب کنید:",
                parse_mode="HTML",
                reply_markup=scenario_keyboard(
                    int(game["id"])
                ),
            )

            save_lobby_state(
                game,
                selection_message_id=int(
                    message.message_id
                ),
                lobby_message_id=int(
                    message.message_id
                ),
            )

            app.ui.group_chat_id = gid

            await callback.answer(
                "🎮 بازی جدید ایجاد شد؛ سناریو را انتخاب کنید."
            )

        except RuntimeError as exc:
            await callback.answer(
                str(exc),
                show_alert=True,
            )

        except Exception:
            logger.exception(
                "new_game_failed group=%s",
                gid,
            )

            await callback.answer(
                "❌ ایجاد بازی انجام نشد.",
                show_alert=True,
            )

    async def scenario_selected(
        callback: types.CallbackQuery,
    ):
        parts = parse_callback(
            callback,
            "lobby",
            4,
        )

        if not parts or parts[2] != "scenario":
            await callback.answer(
                "⚠️ درخواست نامعتبر.",
                show_alert=True,
            )
            return

        gid = group_id(callback)
        game_id = int(parts[1])
        scenario_id = int(parts[3])

        game, error = require_game(
            callback,
            game_id,
        )

        if error:
            await callback.answer(
                error,
                show_alert=True,
            )
            return

        if not await is_manager(
            callback,
            game,
        ):
            await callback.answer(
                "⛔ فقط گرداننده یا مدیر گروه.",
                show_alert=True,
            )
            return

        row = scenario_info(scenario_id)

        if not row or not row.get(
            "is_active",
            True,
        ):
            await callback.answer(
                "❌ سناریو معتبر نیست.",
                show_alert=True,
            )
            return

        if not app.runtime.state.lobby.set_scenario(
            game_id,
            str(scenario_id),
        ):
            await callback.answer(
                "❌ ذخیره سناریو انجام نشد.",
                show_alert=True,
            )
            return

        await callback.answer(
            "✅ سناریو انتخاب شد؛ گرداننده را انتخاب کنید."
        )

        admins = await bot.get_chat_administrators(
            gid
        )

        keyboard = InlineKeyboardMarkup(
            row_width=1
        )

        for admin in admins:
            uid = int(admin.user.id)

            keyboard.add(
                InlineKeyboardButton(
                    admin.user.full_name,
                    callback_data=(
                        f"lobby:{game_id}:moderator:{uid}"
                    ),
                )
            )

        await callback.message.edit_text(
            "🎩 <b>انتخاب گرداننده</b>\n\n"
            "یکی از مدیران گروه را انتخاب کنید:",
            parse_mode="HTML",
            reply_markup=keyboard,
        )

    async def moderator_selected(
        callback: types.CallbackQuery,
    ):
        parts = parse_callback(
            callback,
            "lobby",
            4,
        )

        if not parts or parts[2] != "moderator":
            await callback.answer(
                "⚠️ درخواست نامعتبر.",
                show_alert=True,
            )
            return

        gid = group_id(callback)
        game_id = int(parts[1])
        moderator_id = int(parts[3])

        game, error = require_game(
            callback,
            game_id,
        )

        if error:
            await callback.answer(
                error,
                show_alert=True,
            )
            return

        if not await is_manager(
            callback,
            game,
        ):
            await callback.answer(
                "⛔ فقط مدیر گروه می‌تواند گرداننده را تعیین کند.",
                show_alert=True,
            )
            return

        admins = await bot.get_chat_administrators(
            gid
        )

        admin_ids = {
            int(admin.user.id)
            for admin in admins
        }

        if moderator_id not in admin_ids:
            await callback.answer(
                "❌ این کاربر دیگر مدیر گروه نیست.",
                show_alert=True,
            )
            return

        if not app.runtime.state.lobby.set_moderator(
            game_id,
            moderator_id,
        ):
            await callback.answer(
                "❌ ذخیره گرداننده انجام نشد.",
                show_alert=True,
            )
            return

        await callback.answer(
            "✅ گرداننده ثبت شد."
        )

        await render(
            gid,
            current_game(gid),
        )

    async def toggle_join(
        callback: types.CallbackQuery,
    ):
        parts = parse_callback(
            callback,
            "lobby",
            3,
        )

        if not parts or parts[2] != "toggle":
            await callback.answer(
                "⚠️ درخواست نامعتبر.",
                show_alert=True,
            )
            return

        gid = group_id(callback)
        game_id = int(parts[1])

        game, error = require_game(
            callback,
            game_id,
        )

        if error:
            await callback.answer(
                error,
                show_alert=True,
            )
            return

        uid = int(callback.from_user.id)

        await app._ensure_player(
            callback.from_user
        )

        rows = snapshot(gid).get("players") or []

        current = next(
            (
                row
                for row in rows
                if int(row["player_id"]) == uid
                and str(row.get("status") or "")
                not in {"removed", "finished"}
            ),
            None,
        )

        cap = capacity(game)

        occupied = {
            int(row["seat"])
            for row in rows
            if (
                row.get("seat") is not None
                and str(row.get("status") or "")
                not in {
                    "removed",
                    "dead",
                    "finished",
                }
            )
        }

        if current:
            old_seat = current.get("seat")

            if not app.runtime.state.lobby.leave(
                game_id,
                uid,
            ):
                await callback.answer(
                    "❌ خروج انجام نشد.",
                    show_alert=True,
                )
                return

            if old_seat is not None:
                app.runtime.state.lobby.promote_waiting(
                    game_id,
                    int(old_seat),
                )

            await callback.answer(
                "✅ از بازی خارج شدید."
            )

        else:
            seat = next(
                (
                    number
                    for number in range(
                        1,
                        cap + 1,
                    )
                    if number not in occupied
                ),
                None,
            )

            try:
                app.runtime.state.lobby.join(
                    game_id,
                    uid,
                    seat,
                    is_substitute=seat is None,
                )

            except Exception:
                logger.exception(
                    "lobby_join_rejected game=%s user=%s",
                    game_id,
                    uid,
                )

                await callback.answer(
                    "❌ ورود به بازی انجام نشد؛ احتمالاً ظرفیت تغییر کرده است.",
                    show_alert=True,
                )
                return

            await callback.answer(
                (
                    f"✅ صندلی {seat} برای شما ثبت شد."
                    if seat
                    else "🎟 به لیست رزرو اضافه شدید."
                )
            )

        await render(
            gid,
            current_game(gid),
        )

    async def seat(
        callback: types.CallbackQuery,
    ):
        parts = parse_callback(
            callback,
            "lobby",
            4,
        )

        if not parts or parts[2] != "seat":
            await callback.answer(
                "⚠️ درخواست نامعتبر.",
                show_alert=True,
            )
            return

        gid = group_id(callback)
        game_id = int(parts[1])
        target = int(parts[3])

        game, error = require_game(
            callback,
            game_id,
        )

        if error:
            await callback.answer(
                error,
                show_alert=True,
            )
            return

        cap = capacity(game)

        if target < 1 or target > cap:
            await callback.answer(
                "❌ شماره صندلی نامعتبر است.",
                show_alert=True,
            )
            return

        uid = int(callback.from_user.id)
        rows = snapshot(gid).get("players") or []

        current = next(
            (
                row
                for row in rows
                if int(row["player_id"]) == uid
                and str(row.get("status") or "")
                not in {"removed", "finished"}
            ),
            None,
        )

        if not current:
            await callback.answer(
                "ابتدا وارد بازی شوید.",
                show_alert=True,
            )
            return

        occupied = {
            int(row["seat"]): int(row["player_id"])
            for row in rows
            if row.get("seat") is not None
        }

        if (
            target in occupied
            and occupied[target] != uid
        ):
            await callback.answer(
                "❌ این صندلی قبلاً گرفته شده است.",
                show_alert=True,
            )
            return

        if not app.runtime.state.lobby.assign_seat(
            game_id,
            uid,
            target,
        ):
            await callback.answer(
                "❌ تغییر صندلی انجام نشد.",
                show_alert=True,
            )
            return

        await callback.answer(
            f"✅ صندلی {target} ثبت شد."
        )

        await render(
            gid,
            current_game(gid),
        )

    async def reserve(
        callback: types.CallbackQuery,
    ):
        parts = parse_callback(
            callback,
            "lobby",
            3,
        )

        if not parts or parts[2] != "reserve":
            await callback.answer(
                "⚠️ درخواست نامعتبر.",
                show_alert=True,
            )
            return

        gid = group_id(callback)
        game_id = int(parts[1])

        game, error = require_game(
            callback,
            game_id,
        )

        if error:
            await callback.answer(
                error,
                show_alert=True,
            )
            return

        uid = int(callback.from_user.id)

        rows = snapshot(gid).get("players") or []

        cap = capacity(game)

        occupied = [
            row
            for row in rows
            if (
                row.get("seat") is not None
                and str(row.get("status") or "")
                not in {
                    "removed",
                    "dead",
                    "finished",
                }
            )
        ]

        if len(occupied) < cap:
            await callback.answer(
                "رزرو پس از تکمیل ظرفیت فعال می‌شود.",
                show_alert=True,
            )
            return

        current = next(
            (
                row
                for row in rows
                if int(row["player_id"]) == uid
                and str(row.get("status") or "")
                not in {"removed", "finished"}
            ),
            None,
        )

        if current and current.get("seat") is None:
            app.runtime.state.lobby.leave(
                game_id,
                uid,
            )

            await callback.answer(
                "✅ رزرو لغو شد."
            )

        elif current:
            await callback.answer(
                "شما در لیست اصلی هستید.",
                show_alert=True,
            )
            return

        else:
            await app._ensure_player(
                callback.from_user
            )

            try:
                app.runtime.state.lobby.join(
                    game_id,
                    uid,
                    None,
                    is_substitute=True,
                )

            except Exception:
                logger.exception(
                    "reserve_rejected game=%s user=%s",
                    game_id,
                    uid,
                )

                await callback.answer(
                    "❌ ثبت رزرو انجام نشد.",
                    show_alert=True,
                )
                return

            await callback.answer(
                "🎟 به لیست رزرو اضافه شدید."
            )

        await render(
            gid,
            current_game(gid),
        )

    async def management(
        callback: types.CallbackQuery,
    ):
        parts = parse_callback(
            callback,
            "lobby",
            3,
        )

        if not parts or parts[2] != "management":
            await callback.answer(
                "⚠️ درخواست نامعتبر.",
                show_alert=True,
            )
            return

        gid = group_id(callback)
        game_id = int(parts[1])

        game, error = require_game(
            callback,
            game_id,
        )

        if error:
            await callback.answer(
                error,
                show_alert=True,
            )
            return

        if not await is_manager(
            callback,
            game,
        ):
            await callback.answer(
                "⛔ دسترسی ندارید.",
                show_alert=True,
            )
            return

        keyboard = InlineKeyboardMarkup(
            row_width=1
        )

        keyboard.add(
            InlineKeyboardButton(
                "🔢 تغییر شماره بازی",
                callback_data=(
                    f"lobby:{game_id}:event_menu"
                ),
            ),
            InlineKeyboardButton(
                "📝 تغییر سناریو",
                callback_data=(
                    f"lobby:{game_id}:change_scenario"
                ),
            ),
            InlineKeyboardButton(
                "🎩 تغییر گرداننده",
                callback_data=(
                    f"lobby:{game_id}:change_moderator"
                ),
            ),
            InlineKeyboardButton(
                "🔄 بازسازی پیام لابی",
                callback_data=(
                    f"lobby:{game_id}:refresh"
                ),
            ),
            InlineKeyboardButton(
                "⬅️ بازگشت",
                callback_data=(
                    f"lobby:{game_id}:back"
                ),
            ),
        )

        await callback.message.edit_text(
            "⚙️ <b>مدیریت بازی</b>",
            parse_mode="HTML",
            reply_markup=keyboard,
        )

        await callback.answer()

    async def event_menu(
        callback: types.CallbackQuery,
    ):
        parts = parse_callback(
            callback,
            "lobby",
            3,
        )

        if not parts or parts[2] != "event_menu":
            await callback.answer(
                "⚠️ درخواست نامعتبر.",
                show_alert=True,
            )
            return

        gid = group_id(callback)
        game_id = int(parts[1])

        game, error = require_game(
            callback,
            game_id,
        )

        if error:
            await callback.answer(
                error,
                show_alert=True,
            )
            return

        if not await is_manager(
            callback,
            game,
        ):
            await callback.answer(
                "⛔ دسترسی ندارید.",
                show_alert=True,
            )
            return

        number = int(
            game.get("event_number") or 1
        )

        keyboard = InlineKeyboardMarkup(
            row_width=3
        )

        keyboard.row(
            InlineKeyboardButton(
                "➖",
                callback_data=(
                    f"lobby:{game_id}:event:-1"
                ),
            ),
            InlineKeyboardButton(
                f"🔢 {number}",
                callback_data=(
                    f"lobby:{game_id}:event:nochange"
                ),
            ),
            InlineKeyboardButton(
                "➕",
                callback_data=(
                    f"lobby:{game_id}:event:1"
                ),
            ),
        )

        keyboard.add(
            InlineKeyboardButton(
                "⬅️ بازگشت",
                callback_data=(
                    f"lobby:{game_id}:management"
                ),
            )
        )

        await callback.message.edit_text(
            "🔢 <b>شماره بازی</b>",
            parse_mode="HTML",
            reply_markup=keyboard,
        )

        await callback.answer()

    async def event_adjust(
        callback: types.CallbackQuery,
    ):
        parts = parse_callback(
            callback,
            "lobby",
            4,
        )

        if not parts or parts[2] != "event":
            await callback.answer(
                "⚠️ درخواست نامعتبر.",
                show_alert=True,
            )
            return

        gid = group_id(callback)
        game_id = int(parts[1])
        delta = parts[3]

        game, error = require_game(
            callback,
            game_id,
        )

        if error:
            await callback.answer(
                error,
                show_alert=True,
            )
            return

        if not await is_manager(
            callback,
            game,
        ):
            await callback.answer(
                "⛔ دسترسی ندارید.",
                show_alert=True,
            )
            return

        if delta == "nochange":
            await callback.answer()
            return

        try:
            new_number = max(
                1,
                int(
                    game.get("event_number") or 1
                )
                + int(delta),
            )

        except ValueError:
            await callback.answer(
                "❌ مقدار نامعتبر.",
                show_alert=True,
            )
            return

        if not app.runtime.state.lobby.set_event_number(
            game_id,
            new_number,
        ):
            await callback.answer(
                "❌ تغییر شماره انجام نشد.",
                show_alert=True,
            )
            return

        await callback.answer(
            f"✅ شماره بازی: {new_number}"
        )

        await event_menu(callback)

    async def change_scenario(
        callback: types.CallbackQuery,
    ):
        parts = parse_callback(
            callback,
            "lobby",
            3,
        )

        if not parts or parts[2] != "change_scenario":
            await callback.answer(
                "⚠️ درخواست نامعتبر.",
                show_alert=True,
            )
            return

        gid = group_id(callback)
        game_id = int(parts[1])

        game, error = require_game(
            callback,
            game_id,
        )

        if error:
            await callback.answer(
                error,
                show_alert=True,
            )
            return

        if not await is_manager(
            callback,
            game,
        ):
            await callback.answer(
                "⛔ دسترسی ندارید.",
                show_alert=True,
            )
            return

        await callback.message.edit_text(
            "📝 <b>تغییر سناریو</b>\n\n"
            "سناریوی جدید را انتخاب کنید:",
            parse_mode="HTML",
            reply_markup=scenario_keyboard(
                game_id
            ),
        )

        await callback.answer()

    async def change_moderator(
        callback: types.CallbackQuery,
    ):
        parts = parse_callback(
            callback,
            "lobby",
            3,
        )

        if not parts or parts[2] != "change_moderator":
            await callback.answer(
                "⚠️ درخواست نامعتبر.",
                show_alert=True,
            )
            return

        gid = group_id(callback)
        game_id = int(parts[1])

        game, error = require_game(
            callback,
            game_id,
        )

        if error:
            await callback.answer(
                error,
                show_alert=True,
            )
            return

        if not await is_manager(
            callback,
            game,
        ):
            await callback.answer(
                "⛔ دسترسی ندارید.",
                show_alert=True,
            )
            return

        keyboard = InlineKeyboardMarkup(
            row_width=1
        )

        for admin in await bot.get_chat_administrators(
            gid
        ):
            keyboard.add(
                InlineKeyboardButton(
                    admin.user.full_name,
                    callback_data=(
                        f"lobby:{game_id}:moderator:"
                        f"{int(admin.user.id)}"
                    ),
                )
            )

        await callback.message.edit_text(
            "🎩 <b>تغییر گرداننده</b>",
            parse_mode="HTML",
            reply_markup=keyboard,
        )

        await callback.answer()

    async def refresh(
        callback: types.CallbackQuery,
    ):
        parts = parse_callback(
            callback,
            "lobby",
            3,
        )

        if not parts or parts[2] != "refresh":
            await callback.answer(
                "⚠️ درخواست نامعتبر.",
                show_alert=True,
            )
            return

        gid = group_id(callback)
        game_id = int(parts[1])

        game, error = require_game(
            callback,
            game_id,
        )

        if error:
            await callback.answer(
                error,
                show_alert=True,
            )
            return

        if not await is_manager(
            callback,
            game,
        ):
            await callback.answer(
                "⛔ دسترسی ندارید.",
                show_alert=True,
            )
            return

        ok = await render(
            gid,
            current_game(gid),
        )

        await callback.answer(
            (
                "🔄 پیام لابی بازسازی شد."
                if ok
                else "❌ بازسازی لابی انجام نشد."
            ),
            show_alert=not ok,
        )

    async def back(
        callback: types.CallbackQuery,
    ):
        parts = parse_callback(
            callback,
            "lobby",
            3,
        )

        if not parts or parts[2] != "back":
            await callback.answer(
                "⚠️ درخواست نامعتبر.",
                show_alert=True,
            )
            return

        gid = group_id(callback)
        game_id = int(parts[1])

        game, error = require_game(
            callback,
            game_id,
        )

        if error:
            await callback.answer(
                error,
                show_alert=True,
            )
            return

        if not await is_manager(
            callback,
            game,
        ):
            await callback.answer(
                "⛔ دسترسی ندارید.",
                show_alert=True,
            )
            return

        await render(gid, game)
        await callback.answer()

    async def cancel(
        callback: types.CallbackQuery,
    ):
        parts = parse_callback(
            callback,
            "lobby",
            3,
        )

        if not parts or parts[2] != "cancel":
            await callback.answer(
                "⚠️ درخواست نامعتبر.",
                show_alert=True,
            )
            return

        gid = group_id(callback)
        game_id = int(parts[1])

        game, error = require_game(
            callback,
            game_id,
        )

        if error:
            await callback.answer(
                error,
                show_alert=True,
            )
            return

        if not await is_manager(
            callback,
            game,
        ):
            await callback.answer(
                "⛔ دسترسی ندارید.",
                show_alert=True,
            )
            return

        if not app.runtime.state.games.update_game(
            game_id,
            status="finished",
            state={},
        ):
            await callback.answer(
                "❌ لغو بازی انجام نشد.",
                show_alert=True,
            )
            return

        try:
            app.runtime.state.games.clear_game_players(
                game_id
            )
        except Exception:
            logger.exception(
                "clear_cancelled_lobby_players_failed game=%s",
                game_id,
            )

        message_id = lobby_state(game).get(
            "lobby_message_id"
        )

        if message_id:
            try:
                await bot.edit_message_text(
                    "🚫 <b>این بازی لغو شد.</b>",
                    gid,
                    int(message_id),
                    parse_mode="HTML",
                    reply_markup=None,
                )
            except Exception:
                logger.info(
                    "cancelled_lobby_message_edit_failed "
                    "game=%s",
                    game_id,
                )

        await callback.answer(
            "🚫 بازی لغو شد."
        )

    async def distribute(
        callback: types.CallbackQuery,
    ):
        parts = parse_callback(
            callback,
            "lobby",
            3,
        )

        if not parts or parts[2] != "distribute":
            await callback.answer(
                "⚠️ درخواست نامعتبر.",
                show_alert=True,
            )
            return

        gid = group_id(callback)
        game_id = int(parts[1])

        game, error = require_game(
            callback,
            game_id,
        )

        if error:
            await callback.answer(
                error,
                show_alert=True,
            )
            return

        if not await is_manager(
            callback,
            game,
        ):
            await callback.answer(
                "⛔ فقط گرداننده یا مدیر گروه می‌تواند نقش‌ها را پخش کند.",
                show_alert=True,
            )
            return

        await callback.answer(
            "⏳ در حال پخش نقش‌ها..."
        )

        setattr(
            callback,
            "_canonical_lobby_game_id",
            game_id,
        )

        await app._canonical_distribute_roles(
            callback
        )

    # ------------------------------------------------------------------
    # Canonical callback registration
    # ------------------------------------------------------------------
    #
    # Every canonical callback is scoped by the "lobby:" prefix and,
    # for mutating actions, carries the durable game id.
    #

    dp.register_callback_query_handler(
        new_game,
        lambda callback: callback.data == "new_game",
        state="*",
    )

    dp.register_callback_query_handler(
        scenario_selected,
        lambda callback: (
            str(callback.data or "").startswith("lobby:")
            and ":scenario:" in str(callback.data)
        ),
        state="*",
    )

    dp.register_callback_query_handler(
        moderator_selected,
        lambda callback: (
            str(callback.data or "").startswith("lobby:")
            and ":moderator:" in str(callback.data)
        ),
        state="*",
    )

    dp.register_callback_query_handler(
        toggle_join,
        lambda callback: (
            str(callback.data or "").startswith("lobby:")
            and str(callback.data).endswith(":toggle")
        ),
        state="*",
    )

    dp.register_callback_query_handler(
        seat,
        lambda callback: (
            str(callback.data or "").startswith("lobby:")
            and ":seat:" in str(callback.data)
        ),
        state="*",
    )

    dp.register_callback_query_handler(
        reserve,
        lambda callback: (
            str(callback.data or "").startswith("lobby:")
            and str(callback.data).endswith(":reserve")
        ),
        state="*",
    )

    dp.register_callback_query_handler(
        management,
        lambda callback: (
            str(callback.data or "").startswith("lobby:")
            and str(callback.data).endswith(":management")
        ),
        state="*",
    )

    dp.register_callback_query_handler(
        event_menu,
        lambda callback: (
            str(callback.data or "").startswith("lobby:")
            and str(callback.data).endswith(":event_menu")
        ),
        state="*",
    )

    dp.register_callback_query_handler(
        event_adjust,
        lambda callback: (
            str(callback.data or "").startswith("lobby:")
            and ":event:" in str(callback.data)
        ),
        state="*",
    )

    dp.register_callback_query_handler(
        change_scenario,
        lambda callback: (
            str(callback.data or "").startswith("lobby:")
            and str(callback.data).endswith(
                ":change_scenario"
            )
        ),
        state="*",
    )

    dp.register_callback_query_handler(
        change_moderator,
        lambda callback: (
            str(callback.data or "").startswith("lobby:")
            and str(callback.data).endswith(
                ":change_moderator"
            )
        ),
        state="*",
    )

    dp.register_callback_query_handler(
        refresh,
        lambda callback: (
            str(callback.data or "").startswith("lobby:")
            and str(callback.data).endswith(":refresh")
        ),
        state="*",
    )

    dp.register_callback_query_handler(
        back,
        lambda callback: (
            str(callback.data or "").startswith("lobby:")
            and str(callback.data).endswith(":back")
        ),
        state="*",
    )

    dp.register_callback_query_handler(
        cancel,
        lambda callback: (
            str(callback.data or "").startswith("lobby:")
            and str(callback.data).endswith(":cancel")
        ),
        state="*",
    )

    dp.register_callback_query_handler(
        distribute,
        lambda callback: (
            str(callback.data or "").startswith("lobby:")
            and str(callback.data).endswith(":distribute")
        ),
        state="*",
    )

    app._keyboard_main = lambda: (
        InlineKeyboardMarkup(row_width=1).add(
            InlineKeyboardButton(
                "🎮 بازی جدید",
                callback_data="new_game",
            ),
            InlineKeyboardButton(
                "📖 راهنما",
                callback_data="help",
            ),
        )
    )

    logger.info(
        "CANONICAL_PRODUCTION_LOBBY_ACTIVE"
    )

    return True
```
