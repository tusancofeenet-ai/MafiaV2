# MafiaNights migration state

## Architecture

The repository now uses the clean production entry point and persistent runtime boundary:

`main.py` → `MafiaApplicationV4` → `FeatureParityV4` → `PersistentGameRuntime` / persistent state → Telegram UI.

The legacy implementation remains in `main1.py` only as rollback/reference code. It is not imported by the production entry point.

Persistent infrastructure covers:

- Player/profile persistence
- Scenario persistence
- Lobby repository/service/runtime/handler
- Turn repository/service/runtime with active-turn uniqueness
- Challenge repository/service/runtime with pause/resume metadata
- Day/night repository boundary through persisted game state
- Unified `PersistentGameRuntime`
- `GameStateMachine`
- Production bootstrap and persistence composition
- Restart recovery and legacy-state hydration
- Lobby cut-over middleware
- Day/night compatibility bridge
- Legacy-state authority boundary
- Restart-safe ephemeral recovery manager

## Current production boundary

`main.py` is the canonical production entry point. It constructs the clean application, installs the composed persistence layer, and starts polling only when executed as the process entry point.

`Dockerfile` also targets `python main.py`.

The webhook adapter imports the canonical `main.app`; it no longer boots the legacy runtime entry point.

## State authority contract

The database/persistent runtime is the source of truth for durable game state. Compatibility handlers may maintain process-local UI state, but durable game/player/turn/challenge/lobby/day mutations are written through the persistent runtime.

### Persisted authoritative state

- `player_slots`
- `turn_order`
- `current_turn_index`
- `current_turn_seat`
- `players_in_game`
- `extra_turns`
- feature-parity compatibility state such as substitutes, removed players, challenge requests, pending challenges and Next settings

### Derived compatibility state

Legacy compatibility views such as waiting/lobby flags, day/phase aliases and selected-scenario views are reconstructed from the persisted snapshot/runtime and are not independent durable truth.

### Ephemeral process/UI state

- Telegram message IDs
- asyncio timer task handles
- local anti-spam timestamps

These values are intentionally not persisted as game truth.

## Validation status

The clean entry point is covered by automated contract tests. The validation workflow performs dependency installation, Python compilation and the complete `tests/` suite.

Latest validated run:

- Python 3.11
- compileall: passed
- test suite: passed
- clean entrypoint import contract: passed
- total tests in the latest validation: 72 passed

The tests intentionally use isolated/fake persistence where appropriate; they do not require a production Telegram token.

## Remaining production gate

A live Telegram + production database smoke test still requires deployment/runtime credentials and an actual test group. This is an operational validation step, not a reason to create another runtime implementation.

Before the first production deployment of this cutover, verify:

1. `API_TOKEN` is configured in the hosting environment.
2. `DATABASE_URL` points to the production PostgreSQL/Supabase database.
3. The bot can initialize persistence and recover an active game.
4. A controlled test group can execute lobby → seats → role distribution → turn → challenge → day/night → restart recovery.
5. The webhook, if enabled, points to the canonical `main.app` adapter.

No additional feature-parity implementation should be created until this operational smoke test is complete.
