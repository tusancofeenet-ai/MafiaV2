from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_production_entrypoint_has_one_lobby_installer():
    main = (ROOT / "main.py").read_text(encoding="utf-8")
    assert "runtime.production_lobby_priority" not in main
    assert "runtime.new_game_guard" not in main
    assert main.count("install_production_lobby(app)") == 1


def test_feature_parity_v4_does_not_register_legacy_lobby():
    source = (ROOT / "runtime" / "feature_parity_v4.py").read_text(encoding="utf-8")
    for token in ("legacy_join", "legacy_leave", "join_game", "leave_game", "slot_", "join_waiting", "leave_waiting"):
        assert token not in source


def test_lobby_callbacks_are_game_bound():
    source = (ROOT / "runtime" / "production_lobby.py").read_text(encoding="utf-8")
    assert 'callback_data=f"lobby:{int(game[\'id\'])}:toggle"' in source
    assert 'callback_data=f"lobby:{int(game[\'id\'])}:seat:{seat_no}"' in source
    assert 'callback_data=f"lobby:{int(game[\'id\'])}:cancel"' in source


def test_lobby_has_explicit_stale_game_guard_and_seat_bounds():
    source = (ROOT / "runtime" / "production_lobby.py").read_text(encoding="utf-8")
    assert "expected_id is not None" in source
    assert "target < 1 or target > cap" in source
    assert 'str(game.get("status") or "") != "lobby"' in source


def test_lobby_message_id_is_durable_per_game():
    source = (ROOT / "runtime" / "production_lobby.py").read_text(encoding="utf-8")
    assert 'state.get("lobby_message_id")' in source
    assert 'save_lobby_state(game, lobby_message_id=int(msg.message_id))' in source
