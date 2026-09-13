"""Serverless-safe voting finalization and timer option normalization."""
from __future__ import annotations

import html

from runtime import voting_runtime


def _install_end_target(main):
    async def end_target(app):
        v = voting_runtime._v(app)
        targets = [int(x) for x in (v.get("targets") or [])]
        idx = int(v.get("target_index") or 0)
        if idx >= len(targets):
            return await voting_runtime._finish_round(app)

        target = int(targets[idx])
        voted = {int(x) for x in (v.get("votes") or {}).get(str(target), [])}
        rows = {int(x["player_id"]): x for x in voting_runtime._players(app)}
        target_name = voting_runtime._name(app, target, rows.get(target, {}).get("seat"))
        voter_text = "\\n".join(
            f"• {html.escape(voting_runtime._name(app, uid, rows.get(uid, {}).get('seat')))}"
            for uid in sorted(voted)
        ) or "• هیچ‌کس"

        # Consume this deadline before any Telegram API call. If Telegram/Vercel
        # fails while sending the result, the next 10-second tick can continue
        # with the next target instead of leaving the game stuck on an expired
        # voting deadline.
        v["target_index"] = idx + 1
        v["started_at"] = None
        v["deadline"] = None
        voting_runtime._put(app, v)

        await app.bot.send_message(
            voting_runtime._gid(app),
            f"📊 <b>نتیجه رای‌گیری برای {html.escape(target_name)}</b>\\n\\n"
            f"🗳 تعداد رای: <b>{len(voted)}</b>\\n"
            f"👥 رای‌دهندگان:\\n{voter_text}",
            parse_mode="HTML",
        )
        await voting_runtime._start_target(app)

    voting_runtime._end_target = end_target


def install(main):
    voting_runtime.WAIT_OPTIONS = (10, 20, 30)
    voting_runtime.VOTE_OPTIONS = (10, 20, 30)

    try:
        v = voting_runtime._v(main)
        changed = False
        if int(v.get("wait_seconds", 20)) not in voting_runtime.WAIT_OPTIONS:
            v["wait_seconds"] = 20
            changed = True
        if int(v.get("vote_seconds", 20)) not in voting_runtime.VOTE_OPTIONS:
            v["vote_seconds"] = 20
            changed = True
        if changed:
            voting_runtime._put(main, v)
    except Exception:
        pass

    _install_end_target(main)
    main._voting_serverless_patch_installed = True
    return True
