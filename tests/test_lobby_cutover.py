from types import SimpleNamespace

from runtime.lobby_cutover import LobbyCutover


class FakeLobby:
    def __init__(self):
        self.rows = []
        self.calls = []

    def ensure(self, group, moderator=None, scenario=None):
        self.calls.append(("ensure", group, moderator, scenario))
        return {"id": "g1"}

    def set_moderator(self, group, moderator):
        self.calls.append(("moderator", group, moderator))

    def set_scenario(self, group, scenario):
        self.calls.append(("scenario", group, scenario))

    def join(self, group, uid, seat=None, moderator_id=None, scenario_id=None):
        self.calls.append(("join", group, uid, seat))
        return {"player_id": uid, "seat": seat}

    def assign_seat(self, group, uid, seat):
        self.calls.append(("assign", group, uid, seat))
        return {"player_id": uid, "seat": seat}

    def leave(self, group, uid):
        self.calls.append(("leave", group, uid))
        return True

    def persist_legacy_state(self, group, **kwargs):
        self.calls.append(("state", group, kwargs))
        return True

    def snapshot(self, group):
        return {"game": {"id": "g1", "group_chat_id": group, "moderator_id": 7,
                          "scenario_id": "classic", "status": "lobby"},
                "players": [{"player_id": 7, "seat": 1, "status": "active",
                             "first_name": "Mod"},
                            {"player_id": 8, "seat": None, "status": "waiting",
                             "first_name": "Wait"}],
                "seats": {"1": 7}, "waiting": [8]}


class FakeRuntime:
    def __init__(self, lobby):
        self.lobby = lobby

    def lobby_snapshot(self, group):
        return self.lobby.snapshot(group)


def test_hydrate_restores_lobby_state():
    lobby = FakeLobby()
    main = SimpleNamespace(players={}, player_slots={}, waiting_list=[])
    cutover = LobbyCutover(main, FakeRuntime(lobby))
    snapshot = cutover.hydrate(100)
    assert snapshot["game"]["status"] == "lobby"
    assert main.moderator_id == 7
    assert main.selected_scenario == "classic"
    assert main.player_slots == {1: 7}
    assert main.waiting_list[0]["id"] == 8


def test_persist_mirrors_seats_and_waiting_list():
    lobby = FakeLobby()
    main = SimpleNamespace(
        game_running=False,
        lobby_active=True,
        moderator_id=7,
        selected_scenario="classic",
        player_slots={1: 7, 2: 9},
        waiting_list=[{"id": 8, "name": "Wait"}],
    )
    cutover = LobbyCutover(main, FakeRuntime(lobby))
    cutover.persist(100)
    assert ("join", 100, 7, 1) in lobby.calls
    assert ("join", 100, 9, 2) in lobby.calls
    assert ("join", 100, 8, None) in lobby.calls
    assert any(call[0] == "state" for call in lobby.calls)
