"""Scenario management v3: challenge limits are scoped to gameplay turns/rounds."""
from __future__ import annotations

import html
import json
from typing import Any

from aiogram import types
from aiogram.dispatcher import FSMContext

from repositories.scenario_repository import ScenarioRepository
from runtime.scenario_management_v2 import ScenarioForm, ScenarioManagementV2


class ScenarioManagementV3(ScenarioManagementV2):
    """Enhanced scenario CRUD with the correct challenge-scope semantics."""

    @staticmethod
    def _challenge_label(mode: str) -> str:
        return (
            "محدود — هر بازیکن حداکثر ۱ چالش در هر دور"
            if mode != "free"
            else "آزاد — هر بازیکن حداکثر ۱ چالش در هر نوبت صحبت"
        )

    def _summary(self, row: dict[str, Any]) -> str:
        cfg = row.get("config") or {}
        if isinstance(cfg, str):
            try:
                cfg = json.loads(cfg)
            except Exception:
                cfg = {}
        roles = row.get("roles") or []
        role_cfg = cfg.get("roles") or {}
        sides = cfg.get("sides") or {}
        mode = cfg.get("challenge_mode", "limited")
        settings = cfg.get("settings") or {}
        lines = [
            f"📝 <b>{html.escape(str(row.get('name') or 'بدون نام'))}</b>",
            f"📖 توضیح: {html.escape(str(row.get('description') or '—'))}",
            f"👥 بازیکنان: <b>{row.get('min_players') or '—'} تا {row.get('max_players') or '—'}</b>",
            f"⚔️ چالش: <b>{html.escape(self._challenge_label(str(mode)))}</b>",
            "",
            "🎭 <b>ترکیب نقش‌ها</b>",
        ]
        for role in roles:
            r = str(role)
            rc = role_cfg.get(r) or {}
            side = rc.get("side") or sides.get(r) or "نامشخص"
            lines.append(f"• {html.escape(r)} — ساید: {html.escape(str(side))}")
        if settings:
            lines += ["", "⚙️ <b>تنظیمات</b>"]
            for k, v in settings.items():
                lines.append(f"• {html.escape(str(k))}: {html.escape(str(v))}")
        return "\n".join(lines)

    async def challenge_mode(self, callback: types.CallbackQuery, state: FSMContext):
        if not await self._admin(callback):
            return
        s = self.sessions[int(callback.from_user.id)]
        mode = callback.data.rsplit(":", 1)[1]
        s["data"]["challenge_mode"] = mode
        # The limit is fixed by the selected scope; it is NOT a whole-game quota.
        # Keeping challenge_limit=1 in config preserves compatibility with older data.
        s["data"]["challenge_limit"] = 1 if mode == "limited" else None
        await callback.message.answer(
            "⚙️ تنظیمات اضافی را JSON وارد کنید؛ اگر ندارید «-» بزنید.\n"
            "مثال: {\"allow_player_next\":true,\"allow_moderator_next\":true}"
        )
        await ScenarioForm.settings.set()
        await callback.answer()

    async def settings(self, message: types.Message, state: FSMContext):
        user_id = int(message.from_user.id)
        s = self.sessions.pop(user_id)
        data = s["data"]
        raw = (message.text or "").strip()
        if raw == "-":
            settings = {}
        else:
            try:
                settings = json.loads(raw)
                assert isinstance(settings, dict)
            except Exception:
                await message.answer("⚠️ JSON نامعتبر است. دوباره ارسال کنید.")
                self.sessions[user_id] = s
                return

        role_cfg = {
            r: {"side": data["sides"][r], "challenge": data["challenge_mode"]}
            for r in data["roles"]
        }
        cfg = {
            "roles": role_cfg,
            "sides": data["sides"],
            "challenge_mode": data["challenge_mode"],
            "challenge_limit": data.get("challenge_limit"),
            "settings": settings,
        }
        try:
            if s.get("mode") == "edit":
                sid = self.repo.update_by_id(
                    s["id"], data["name"], data.get("description"),
                    data["min_players"], data["max_players"], data["roles"], cfg, True,
                )
            else:
                sid = self.repo.upsert(
                    data["name"], data.get("description"), data["min_players"],
                    data["max_players"], data["roles"], cfg, True,
                )
            await state.finish()
            row = self.repo.get_by_id(sid)
            await message.answer("✅ سناریو ذخیره شد.\n\n" + self._summary(row), parse_mode="HTML")
        except Exception as exc:
            self.sessions[user_id] = s
            await message.answer(f"❌ ذخیره سناریو انجام نشد: {html.escape(str(exc))}")

    async def delete_confirm(self, callback: types.CallbackQuery):
        if not await self._admin(callback):
            return
        sid = int(callback.data.rsplit(":", 1)[1])
        row = self.repo.get_by_id(sid)
        if not row:
            await callback.answer("سناریو پیدا نشد.", show_alert=True)
            return
        self.repo.set_active(sid, False)
        await callback.message.edit_text(
            f"✅ سناریوی «{html.escape(str(row['name']))}» غیرفعال شد."
        )
        await callback.answer()
