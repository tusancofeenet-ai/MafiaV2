"""Persistence bootstrap for the clean MafiaNights runtime.

This module is deliberately a small composition boundary: it keeps the
existing, tested persistence implementations behind one entry point while the
legacy production bootstrap is being retired. No gameplay state is stored in
module-level containers here.
"""
from __future__ import annotations

import logging
from typing import Any

from runtime.postgres_fsm_storage import install as install_fsm
from runtime.scenario_persistence_patch import install as install_scenarios
from runtime.addons_persistence_patch import install as install_addons


def install(app: Any) -> dict[str, bool]:
    """Install all persistent storage adapters exactly once."""
    results = {
        "fsm": bool(install_fsm(app)),
        "scenarios": bool(install_scenarios(app)),
        "addons": bool(install_addons(app)),
    }
    logging.info("Final persistence layer installed: %s", results)
    return results
