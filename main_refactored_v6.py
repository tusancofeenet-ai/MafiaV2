"""MafiaNights production compatibility wrapper (v6).

This version makes the active Telegram group explicit and independent from
Vercel environment overrides. Previous versions remain untouched as rollback
backups.
"""
from __future__ import annotations

import os

from aiogram import types as aiogram_types

from main_refactored import MafiaApplication

# ==============================
# گروه‌های مجاز اجرای ربات
# ==============================
# گروه تست قبلی:
# ALLOWED_GROUP_ID = -1003080272814
# گروه اصلی قبلی:
# ALLOWED_GROUP_ID = -1001760002160
# فقط این گروه فعال است:
ALLOWED_GROUP_ID = -1002356353761
ALLOWED_GROUP_IDS = {ALLOWED_GROUP_ID}


class MafiaApplicationV6(MafiaApplication):
    """Production wrapper with an explicit single active group."""

    def __init__(self, token: str):
        super().__init__(token)
        # Keep the v6 production group explicit without dynamically executing
        # a truncated copy of main_refactored.py.
        self.allowed_group_id = ALLOWED_GROUP_ID
        self.allowed_group_ids = ALLOWED_GROUP_IDS

    def _register_handlers(self) -> None:
        role_store = getattr(self, "roles", None)
        if isinstance(role_store, dict):
            delattr(self, "roles")
        try:
            super()._register_handlers()
        finally:
            self.roles = role_store if isinstance(role_store, dict) else {}

    async def new_game(self, callback: aiogram_types.CallbackQuery) -> None:
        """Start a lobby only in the explicitly active production group."""
        group_id = int(callback.message.chat.id)
        if group_id not in ALLOWED_GROUP_IDS:
            await callback.answer("❌ این ربات در این گروه فعال نیست.", show_alert=True)
            return
        self.ui.group_chat_id = group_id
        self.runtime.lobby.ensure(group_id)
        await self._render_lobby(group_id)
        await callback.answer("🎮 لابی جدید آماده شد.")


TOKEN = os.getenv("API_TOKEN")
if not TOKEN:
    raise ValueError("API_TOKEN environment variable is not set!")

app = MafiaApplicationV6(TOKEN)
bot = app.bot
dp = app.dp


async def on_startup(dp):
    await app.startup()


async def on_shutdown(dp):
    await app.shutdown()
