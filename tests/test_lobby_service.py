from services.lobby_service import LobbyService


class FakeGameRepository:
    def __init__(self):
        self.game = None
        self.players_data = []

    def get_active_game(self, group_chat_id):
        return self.game

    def next_event_number(self, group_chat_id):
        return 1

    def create_game(self, **kwargs):
        self.game = {"id": "game-1", "group_chat_id": kwargs["group_chat_id"]}
        return "game-1"

    def add_player(self, **kwargs):
        self.players_data.append(kwargs)
        return len(self.players_data)

    def list_players(self, game_id):
        return [
            {"id": "gp-1", "player_id": 11, "seat": 1, "status": "active", "is_substitute": False,
             "username": "one", "first_name": "One", "last_name": None, "nickname": "Player One", "role": "مافیا"},
            {"id": "gp-2", "player_id": 22, "seat": None, "status": "waiting", "is_substitute": True,
             "username": "two", "first_name": "Two", "last_name": None, "nickname": None, "role": None},
        ]

    def update_game(self, game_id, **fields):
        return True


def test_get_or_create_is_idempotent():
    repo = FakeGameRepository()
    service = LobbyService(repo)
    first = service.get_or_create(-100, 1)
    second = service.get_or_create(-100, 1)
    assert first["id"] == second["id"] == "game-1"


def test_public_players_does_not_expose_role():
    service = LobbyService(FakeGameRepository())
    players = service.players("game-1")
    assert all("role" not in player for player in players)
    assert players[0]["nickname"] == "Player One"


def test_snapshot_separates_seats_and_waiting():
    service = LobbyService(FakeGameRepository())
    snapshot = service.snapshot("game-1")
    assert snapshot["seats"] == {"1": 11}
    assert snapshot["waiting"] == [22]
