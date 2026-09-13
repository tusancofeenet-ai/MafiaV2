from runtime.game_state_machine import GameStateMachine, Phase


class FakeGames:
    def __init__(self):
        self.game = {"id": "g1", "group_chat_id": 100, "status": "lobby"}
        self.updated = []

    def get_active_game(self, group_id):
        return self.game if group_id == 100 else None

    def update_game(self, game_id, **fields):
        self.updated.append((game_id, fields))
        self.game.update(fields)
        return True


class FakeState:
    def __init__(self):
        self.games = FakeGames()

    def active_game(self, group_id):
        return self.games.get_active_game(group_id)


class FakeTurns:
    def current(self, group_id):
        return None

    def recover(self, group_id):
        return {"recoverable": False}


class FakeChallenges:
    def pending(self, group_id):
        return []


def test_phase_transition_is_explicit():
    machine = GameStateMachine.__new__(GameStateMachine)
    machine.state = FakeState()
    machine.turns = FakeTurns()
    machine.challenges = FakeChallenges()

    result = machine.transition(100, Phase.RUNNING)
    assert result.phase is Phase.RUNNING
    assert result.previous_phase is Phase.LOBBY
    assert machine.state.games.game["status"] == "running"


def test_invalid_transition_is_rejected():
    machine = GameStateMachine.__new__(GameStateMachine)
    machine.state = FakeState()
    machine.turns = FakeTurns()
    machine.challenges = FakeChallenges()

    try:
        machine.transition(100, Phase.CHALLENGE)
    except ValueError:
        pass
    else:
        raise AssertionError("invalid transition was accepted")
