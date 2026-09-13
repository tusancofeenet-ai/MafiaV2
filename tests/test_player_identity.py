from types import SimpleNamespace

from runtime.player_identity import install


def test_identity_prefers_real_name_from_legacy_player_maps():
    main = SimpleNamespace(
        display_name=lambda uid, fallback=None: "بازیکن",
        players={11: {"first_name": "علی"}},
        players_in_game={},
    )

    assert install(main) is True
    assert main.display_name(11, None) == "علی"


def test_identity_supports_persistent_style_name_fields():
    main = SimpleNamespace(
        display_name=lambda uid, fallback=None: "بازیکن",
        players={},
        players_in_game={22: {"name": "رضا"}},
    )

    install(main)
    assert main.display_name(22, None) == "رضا"
