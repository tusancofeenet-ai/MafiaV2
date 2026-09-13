"""Canonical display-name resolver for legacy and persistent game views."""
from __future__ import annotations

import logging


_GENERIC = {"", "?", "❓", "None", "بازیکن", "بازیکن 0"}


def _clean(value):
    if value is None:
        return None
    text = str(value).strip()
    return text if text not in _GENERIC else None


def _lookup(container, uid):
    if not isinstance(container, dict):
        return None
    try:
        value = container.get(uid)
        if value is None:
            value = container.get(str(uid))
    except Exception:
        return None
    if isinstance(value, dict):
        for key in ("nickname", "name", "full_name", "first_name", "display_name"):
            found = _clean(value.get(key))
            if found:
                return found
        return None
    return _clean(value)


def install(main):
    """Make ``main.display_name`` resilient to incomplete legacy player maps.

    The persistent player rows and the legacy ``players``/``players_in_game``
    maps do not always contain the same name field. Voting and turn UIs should
    still resolve the same real name instead of falling back to ``بازیکن``.
    """
    if getattr(main, "_canonical_identity_installed", False):
        return False

    original = getattr(main, "display_name", None)
    if not callable(original):
        return False

    def display_name(uid, fallback=None):
        try:
            value = _clean(original(uid, fallback))
            if value:
                return value
        except Exception:
            pass

        for source_name in ("players", "players_in_game"):
            source = getattr(main, source_name, None)
            value = _lookup(source, uid)
            if value:
                return value

        value = _clean(fallback)
        if value:
            return value
        logging.debug("identity: no display name for user %s", uid)
        return "بازیکن"

    main.display_name = display_name
    main._canonical_identity_installed = True
    return True
