"""Hard cutover of legacy lobby callbacks to the persistent lobby owner."""
from __future__ import annotations

import logging


LEGACY_NAMES = {
    "new_game", "start_game", "choose_scenario", "choose_moderator",
    "new_game_handler", "start_game_handler",
    "choose_scenario_handler", "choose_moderator_handler",
}


def _remove_legacy_handlers(dp):
    table = getattr(dp.callback_query_handlers, "handlers", [])
    kept = []
    removed = []
    for item in table:
        fn = getattr(item, "callback", None)
        name = getattr(fn, "__name__", "")
        module = getattr(fn, "__module__", "")
        if name in LEGACY_NAMES and (module == "main1" or module.startswith("main1.")):
            removed.append(name)
            continue
        kept.append(item)
    table[:] = kept
    return removed


def install(main):
    dp = main.dp
    handlers = getattr(dp.callback_query_handlers, "handlers", [])
    by_name = {}
    for item in handlers:
        fn = getattr(item, "callback", None)
        if fn is not None:
            by_name.setdefault(getattr(fn, "__name__", ""), fn)

    v6_new = by_name.get("new")
    v6_scenario = by_name.get("scenario")
    v6_moderator = by_name.get("moderator")
    if v6_new is None:
        logging.error("lobby callback cutover: v6 new handler not found")
        return False

    removed = _remove_legacy_handlers(dp)

    def front(fn):
        current = getattr(dp.callback_query_handlers, "handlers", [])
        for i, item in enumerate(current):
            if getattr(item, "callback", None) is fn:
                current.insert(0, current.pop(i))
                return

    async def legacy_new(callback):
        await v6_new(callback)

    async def legacy_choose_scenario(callback):
        if v6_scenario:
            await v6_scenario(callback)
        else:
            await v6_new(callback)

    async def legacy_choose_moderator(callback):
        if v6_moderator:
            await v6_moderator(callback)
        else:
            await v6_new(callback)

    aliases = [
        (legacy_new, lambda c: c.data in {"new_game", "start_game"}),
        (legacy_choose_scenario, lambda c: c.data == "choose_scenario"),
        (legacy_choose_moderator, lambda c: c.data == "choose_moderator"),
    ]
    for fn, flt in aliases:
        dp.register_callback_query_handler(fn, flt)
        front(fn)

    logging.info("CANONICAL_LOBBY_CALLBACK_CUTOVER_ACTIVE removed=%s aliases=%s", removed, len(aliases))
    return True
