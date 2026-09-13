"""Feature-parity v4.

Lobby ownership is intentionally absent here. The production lobby is owned
exclusively by ``runtime.production_lobby``; this layer extends the
non-lobby feature parity surface and applies scenario-specific challenge
quotas.
"""
from __future__ import annotations

from runtime.feature_parity_v3 import FeatureParityV3
from runtime.scenario_challenge_policy import ScenarioChallengePolicy


class FeatureParityV4(FeatureParityV3):
    """Final feature-parity layer with scenario-aware challenge quotas."""

    def __init__(self, app):
        super().__init__(app)
        self.challenge_policy = ScenarioChallengePolicy(app)

    async def challenge_request(self, callback):
        group_id = int(callback.message.chat.id)
        challenger = int(callback.from_user.id)
        target_seat = int(str(callback.data).rsplit(":", 1)[1])

        allowed, reason, key = self.challenge_policy.check(group_id, challenger)
        if not allowed:
            await callback.answer(reason, show_alert=True)
            return

        game_before = self._game(group_id)
        state_before = dict((game_before or {}).get("state") or {})
        pending_before = dict(state_before.get("challenge_requests") or {})
        bucket_before = dict(pending_before.get(str(target_seat)) or {})
        was_pending = str(challenger) in bucket_before

        # The base handler performs the existing target/self/pending/enable
        # checks and creates the challenge request.
        await super().challenge_request(callback)

        if was_pending:
            return

        game_after = self._game(group_id)
        state_after = dict((game_after or {}).get("state") or {})
        pending_after = dict(state_after.get("challenge_requests") or {})
        bucket_after = dict(pending_after.get(str(target_seat)) or {})
        if bucket_after.get(str(challenger)) == "pending":
            mode = self.challenge_policy.mode(group_id)
            self.challenge_policy.mark(group_id, challenger, key, mode)

    def register(self):
        super().register()
