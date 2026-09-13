import asyncio
from types import SimpleNamespace

import runtime.stable_round_engine as engine


class FakeBot:
    def __init__(self):
        self.messages = []

    async def get_chat_member(self, chat_id, uid):
        return SimpleNamespace(user=SimpleNamespace(full_name=f"User {uid}", first_name=f"User {uid}"))

    async def send_message(self, chat_id, text, **kwargs):
        self.messages.append((chat_id, text, kwargs))
        return SimpleNamespace(message_id=len(self.messages))


class FakeMain:
    def __init__(self):
        self.bot = FakeBot()
        self.group_chat_id = 123
        self.player_slots = {1: 101, 2: 102, 3: 103}
        self.players = {101: "Ali", 102: "", 103: "بازیکن"}
        self.turn_order = [1, 2, 3]
        self.current_turn_index = 0
        self._stable_normal_order = [1, 2, 3]
        self._stable_phase = "normal"
        self._stable_day_ended = False
        self._stable_day_active = True
        self._stable_extra_seats = set()
        self._stable_extra_used = set()
        self._stable_challenge_used = set()
        self._stable_challenge_locked = set()
        self._stable_challenge_requests = {}
        self._stable_challenge_request_messages = {}
        self._gm_extra_next_round = set()
        self._gm_extra_phase = False
        self._gm_extra_turn_active = False
        self._gm_muted_active = set()
        self.challenge_active = False
        self.pending_challenges = {}
        self.active_challenger_seats = set()
        self.challenge_mode = False
        self.current_turn_message_id = None
        self.turn_timer_task = None
        self.nicknames = None


def test_normal_day_ends_without_restart(monkeypatch):
    main = FakeMain()
    started = []
    ended = []

    async def fake_start(main_obj, seat, duration=120, is_challenge=False):
        started.append((seat, is_challenge))

    async def fake_end(main_obj):
        ended.append(True)
        main_obj._stable_day_ended = True

    monkeypatch.setattr(engine, "_start_turn", fake_start)
    monkeypatch.setattr(engine, "_end_day", fake_end)

    asyncio.run(engine._advance(main))
    assert started == [(1, False)]

    main.current_turn_index = 1
    asyncio.run(engine._advance(main))
    main.current_turn_index = 2
    asyncio.run(engine._advance(main))
    main.current_turn_index = 3
    asyncio.run(engine._advance(main))

    assert started == [(1, False), (2, False), (3, False)]
    assert ended == [True]
    assert main._stable_day_ended is True


def test_explicit_extra_runs_once_then_ends(monkeypatch):
    main = FakeMain()
    main.current_turn_index = 3
    main._gm_extra_next_round = {2}
    extras = []
    ended = []

    async def fake_extra(main_obj, seat):
        extras.append(seat)

    async def fake_end(main_obj):
        ended.append(True)
        main_obj._stable_day_ended = True

    monkeypatch.setattr(engine, "_start_extra", fake_extra)
    monkeypatch.setattr(engine, "_end_day", fake_end)

    asyncio.run(engine._advance(main))
    assert main.turn_order == [2]
    assert main.current_turn_index == 0
    assert main._gm_extra_next_round == set()
    assert extras == [2]

    main.current_turn_index = 1
    asyncio.run(engine._advance(main))
    assert ended == [True]
    assert main._stable_day_ended is True


def test_missing_first_turn_name_is_hydrated():
    main = FakeMain()
    assert asyncio.run(engine._resolve_name(main, 102)) == "User 102"
    assert main.players[102] == "User 102"
    assert asyncio.run(engine._resolve_name(main, 103)) == "User 103"
    assert main.players[103] == "User 103"
