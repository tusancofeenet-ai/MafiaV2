# Feature parity finalization

## Production target

`main.py` is the canonical production entry point.

Architecture:

`main.py` → `MafiaApplicationV4` → `FeatureParityV4` → persistent runtime/state authority → ephemeral Telegram runtime.

The legacy implementation remains in `main1.py` only as rollback/reference material and is not imported by production.

## Migrated user-facing surface

- `/start` and help
- new game/lobby
- scenario selection and scenario CRUD
- moderator selection/change
- join/leave and seat selection
- full-seat waiting/substitute list and cancellation
- role distribution and role resend
- private role lookup
- seat lookup and seat list
- player list and admin-only player list
- game status
- tag active players / group admins
- turn start, next, countdown and restart recovery
- challenge request, before/after decision, reject, challenge status
- remove player
- restore removed player
- replace player from substitute list
- next permissions for players/moderator
- next anti-spam setting
- game cancellation
- addon compatibility through the clean application's addon layer

## Callback compatibility

The parity layer supports the principal clean `fp:*` callbacks and the required legacy callback aliases, including lobby join/leave/seat, waiting-list actions, challenge actions and management-panel actions.

## State policy

No new module-level mutable game containers were introduced by the cutover. Substitute lists, removed players, challenge requests, pending challenges, paused-turn metadata and Next settings are stored in the active game's persisted state. Telegram message IDs and asyncio task handles remain process-local UI state.

## Validation

The clean entry point is covered by automated tests. The CI validation workflow performs dependency installation, Python compilation and the complete test suite. The latest validated suite reports **72 passed**.

The bootstrap contract also verifies that importing `main.py` constructs the clean application without starting polling and that persistence is installed through the canonical composition layer.

## Operational gate

Live Telegram + production PostgreSQL/Supabase smoke testing remains an operational requirement before the first production deployment. It requires valid runtime credentials and a controlled Telegram test group.

No additional `v5`/`v6` runtime should be created for this gate. Fixes belong in the existing canonical modules.
