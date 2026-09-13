"""Scenario management adapter that applies scenario snapshots to live games."""
from __future__ import annotations

from aiogram import types

from runtime.scenario_management_v3 import ScenarioManagementV3


class ScenarioManagementV4(ScenarioManagementV3):
    async def scenario_pick(self, callback: types.CallbackQuery):
        p = self._parts(callback, "scenario_pick", 4)
        if not p:
            return
        gid = int(callback.message.chat.id)
        game = self._game(gid)
        sid = int(p[3])
        if not game or not await self._allowed(callback, gid, game):
            await callback.answer("⛔ دسترسی ندارید.", show_alert=True)
            return
        row = self.scenarios.get_by_id(sid)
        if not row or not row.get("is_active", True):
            await callback.answer("❌ سناریو معتبر نیست.", show_alert=True)
            return
        try:
            scenario_runtime = getattr(self.app, "scenario_runtime", None)
            if scenario_runtime:
                scenario_runtime.apply_to_game(game["id"], sid)
            else:
                self.app.runtime.state.games.update_game(game["id"], scenario_id=sid)
            self.app.runtime.state.games.update_game(game["id"], moderator_id=None)
        except Exception:
            await callback.answer("❌ اتصال سناریو به بازی انجام نشد.", show_alert=True)
            return

        kb = types.InlineKeyboardMarkup(row_width=2)
        for admin in await self.app.bot.get_chat_administrators(gid):
            kb.insert(types.InlineKeyboardButton(
                admin.user.full_name,
                callback_data=f"mgmt:{game['id']}:moderator_pick:{int(admin.user.id)}",
            ))
        await callback.message.edit_text(
            "🎩 <b>انتخاب گرداننده</b>\n\n"
            "سناریو و قوانین آن به موتور بازی متصل شد.\n"
            "تغییر سناریو بدون تعیین گرداننده کامل نمی‌شود:",
            parse_mode="HTML", reply_markup=kb,
        )
        await callback.answer("✅ سناریو به بازی متصل شد.")
