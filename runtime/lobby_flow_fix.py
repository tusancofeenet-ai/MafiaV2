"""Fix the lobby flow after selecting the moderator.

Selecting a moderator is a configuration step, not a start-game action. The
user must be returned to the same game menu so the scenario can be selected.
"""
from aiogram import types


def install(main):
    dp = main.dp

    async def moderator_selected_fixed(callback: types.CallbackQuery):
        try:
            moderator_id = int(str(callback.data).removeprefix("moderator_"))
        except ValueError:
            await callback.answer("⚠️ گرداننده نامعتبر است.", show_alert=True)
            return

        main.moderator_id = moderator_id

        # Preserve the existing addon configuration for the selected moderator.
        try:
            main.addons.register(
                moderator_id=moderator_id,
                group_id=main.group_chat_id,
            )
            next_config = main.addons.settings.get("next", {})
            main.next_by_players_enabled = next_config.get("allow_players_next", True)
            main.next_by_moderator_enabled = next_config.get("allow_moderator_next", True)
        except Exception:
            # Selecting a moderator must not prevent the lobby from continuing.
            pass

        try:
            member = await main.bot.get_chat_member(main.group_chat_id, moderator_id)
            moderator_name = main.display_name(member.user.id, member.user.full_name)
        except Exception:
            moderator_name = main.display_name(moderator_id, None)

        # IMPORTANT: do not call distribute_roles/start_game here.
        # Return to the configuration menu so scenario selection remains possible.
        await callback.message.edit_text(
            f"🎩 گرداننده انتخاب شد: {moderator_name}\n\n"
            "حالا سناریو را انتخاب کنید یا تنظیمات بازی را تغییر دهید.",
            reply_markup=main.game_menu_keyboard(),
        )
        await callback.answer("✅ گرداننده انتخاب شد.")

    dp.register_callback_query_handler(
        moderator_selected_fixed,
        lambda c: str(c.data or "").startswith("moderator_"),
    )

    handlers = getattr(getattr(dp, "callback_query_handlers", None), "handlers", None)
    if isinstance(handlers, list):
        for i, item in enumerate(handlers):
            if getattr(item, "callback", None) is moderator_selected_fixed:
                handlers.insert(0, handlers.pop(i))
                break
