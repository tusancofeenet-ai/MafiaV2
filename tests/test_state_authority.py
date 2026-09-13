from types import SimpleNamespace

from runtime.state_authority import LegacyStateAuthority


class FakeGames:
    def __init__(self, game):
        self.game = game
        self.calls = []

    def update_game(self, game_id, **fields):
        self.calls.append((game_id, fields))
        self.game.update(fields)
        return True


class FakeState:
    def __init__(self, game, pending=None):
        self.games = FakeGames(game)
        self._pending = pending or []

    def active_game(self, group_id):
        return self.games.game


class FakeRuntime:
    def __init__(self, state, pending=None, day=None):
        self.state = state
        self._pending = pending or []
        self._day = day or {"day": 2, "phase": "day"}

    def snapshot(self, group_id):
        return {"game": self.state.games.game, "turn": None, "challenge": self._pending}

    def day_snapshot(self, group_id):
        return self._day


def test_hydrate_makes_persisted_state_the_legacy_view():
    game = {
        "id": "g1", "group_chat_id": 10, "status": "running",
        "moderator_id": 7, "scenario_id": "classic",
        "current_turn_index": 3, "current_turn_seat": 4,
        "state": {"player_slots": {"4": 44}, "turn_order": [4, 2], "extra_turns": [9]},
    }
    main = SimpleNamespace()
    authority = LegacyStateAuthority(main, FakeRuntime(FakeState(game)))

    authority.hydrate(10)

    assert main.player_slots == {4: 44}
    assert main.turn_order == [4, 2]
    assert main.current_turn_index == 3
    assert main.current_turn_seat == 4
    assert main.day_number == 2
    assert main.day_phase == "day"
    assert main.lobby_active is False
    assert main.game_running is True


def test_capture_persists_compatibility_turn_state_then_rehydrates():
    game = {
        "id": "g1", "group_chat_id": 10, "status": "running",
        "current_turn_index": 0, "state": {},
    }
    state = FakeState(game)
    runtime = FakeRuntime(state)
    main = SimpleNamespace(player_slots={1: 11}, turn_order=[1, 2], extra_turns=[11],
                           current_turn_index=1, current_turn_seat=2)
    authority = LegacyStateAuthority(main, runtime)

    authority.capture_compatibility_mutations(10)

    assert state.games.calls
    fields = state.games.calls[-1][1]
    assert fields["current_turn_index"] == 1
    assert fields["current_turn_seat"] == 2
    assert fields["state"]["player_slots"] == {"1": 11}
    assert fields["state"]["turn_order"] == [1, 2]
    assert fields["state"]["extra_turns"] == [11]


def test_challenge_flags_are_derived_from_persisted_challenges():
    game = {"id": "g1", "group_chat_id": 10, "status": "running", "state": {}}
    pending = [{"id": "c1", "challenger_id": 11, "target_id": 22, "status": "pending"}]
    main = SimpleNamespace()
    authority = LegacyStateAuthority(main, FakeRuntime(FakeState(game), pending=pending))

    authority.hydrate(10)

    assert list(main.pending_challenges) == ["c1"]
    assert main.challenge_mode is True
