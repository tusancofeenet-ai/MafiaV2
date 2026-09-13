from types import SimpleNamespace

import runtime.production_bridge as bridge


def test_install_attaches_shared_runtime(monkeypatch):
    calls = {}

    class FakeRuntime:
        def __init__(self):
            self.challenges = object()
            self.state = object()
            calls["runtime"] = self

    class FakeAdapter:
        def __init__(self, game_runtime=None):
            calls["adapter_runtime"] = game_runtime

    class FakeEphemeralRecovery:
        def __init__(self, runtime, main):
            calls["recovery_runtime"] = runtime
            calls["recovery_main"] = main

    monkeypatch.setattr(bridge, "PersistentGameRuntime", FakeRuntime)
    monkeypatch.setattr(bridge, "MigrationAdapter", FakeAdapter)
    monkeypatch.setattr(bridge, "EphemeralRecoveryManager", FakeEphemeralRecovery)
    monkeypatch.setattr(bridge, "install_legacy_turn_cutover", lambda main, adapter: {"next_turn": True})
    monkeypatch.setattr(bridge, "install_legacy_day_cutover", lambda main, runtime: {"cutover": {"start_new_day": True}})
    monkeypatch.setattr(bridge, "install_legacy_state_authority", lambda main, runtime, install_middleware=False: {"installed": True})

    main = SimpleNamespace()
    result = bridge.install(main)

    assert main.persistent_runtime is calls["runtime"]
    assert main._migration_adapter is not calls["runtime"]
    assert calls["adapter_runtime"] is calls["runtime"]
    assert main._persistent_challenge_runtime is calls["runtime"].challenges
    assert result["turn_cutover"]["next_turn"] is True
    assert result["lobby_cutover"] is None
    assert result["day_cutover"]["cutover"]["start_new_day"] is True
    assert result["state_authority"]["installed"] is True
    assert calls["recovery_runtime"] is calls["runtime"]
    assert calls["recovery_main"] is main


def test_startup_calls_original_startup_then_recovery(monkeypatch):
    events = []

    async def original_startup(dp):
        events.append(("original", dp))

    async def fake_recover(main):
        events.append(("recover", main))
        return [{"action": "ok"}]

    monkeypatch.setattr(bridge, "recover_and_hydrate", fake_recover)
    main = SimpleNamespace(dp=object())

    result = __import__("asyncio").run(bridge.startup(main, original_startup))
    assert result == [{"action": "ok"}]
    assert events[0][0] == "original"
    assert events[1][0] == "recover"
