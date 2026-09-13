from sqlalchemy import text

from .base import DatabaseRepository


BASE_SCORE = 50


class RatingRepository(DatabaseRepository):
    """Persistence and aggregate queries for player ratings."""

    def record(self, user_id, game_id, score, result, role, *, win_bonus=0,
               challenge_bonus=0, warning_penalty=0, kick_penalty=0):
        with self.SessionLocal() as session:
            row = session.execute(
                text("""
                    insert into public.mafia_ratings
                        (user_id, game_id, score, changes, result, role,
                         base_score, win_bonus, challenge_bonus,
                         warning_penalty, kick_penalty)
                    values
                        (:user_id, :game_id, :score, :score, :result, :role,
                         :base_score, :win_bonus, :challenge_bonus,
                         :warning_penalty, :kick_penalty)
                    on conflict (user_id, game_id) where user_id is not null and game_id is not null
                    do update set
                        score = excluded.score,
                        changes = excluded.changes,
                        result = excluded.result,
                        role = excluded.role,
                        base_score = excluded.base_score,
                        win_bonus = excluded.win_bonus,
                        challenge_bonus = excluded.challenge_bonus,
                        warning_penalty = excluded.warning_penalty,
                        kick_penalty = excluded.kick_penalty,
                        updated_at = now()
                    returning id
                """),
                {
                    "user_id": int(user_id), "game_id": game_id,
                    "score": int(score), "result": result, "role": role,
                    "base_score": BASE_SCORE, "win_bonus": int(win_bonus),
                    "challenge_bonus": int(challenge_bonus),
                    "warning_penalty": int(warning_penalty),
                    "kick_penalty": int(kick_penalty),
                },
            ).scalar_one()
            session.commit()
            return row

    def player_summary(self, user_id):
        with self.SessionLocal() as session:
            row = session.execute(text("""
                select
                    count(*)::int as games,
                    (50 + coalesce(sum(score), 0))::int as score,
                    count(*) filter (where result='win')::int as wins,
                    count(*) filter (where result='loss')::int as losses,
                    count(*) filter (where result='draw')::int as draws,
                    coalesce(sum(win_bonus),0)::int as win_bonus,
                    coalesce(sum(challenge_bonus),0)::int as challenge_bonus,
                    coalesce(sum(warning_penalty),0)::int as warning_penalty,
                    coalesce(sum(kick_penalty),0)::int as kick_penalty,
                    count(*) filter (where kick_penalty > 0)::int as kicks,
                    coalesce(sum(challenge_bonus / 3),0)::int as challenges,
                    coalesce(sum(warning_penalty),0)::int as warnings,
                    coalesce(max(score),0)::int as best_game_delta
                from public.mafia_ratings
                where user_id=:user_id
            """), {"user_id": int(user_id)}).mappings().one()
            return dict(row)

    def player_profile(self, user_id):
        with self.SessionLocal() as session:
            row = session.execute(text("""
                select p.user_id, p.username, p.first_name, p.last_name, p.nickname,
                       coalesce(r.games,0)::int as games,
                       (50 + coalesce(r.score,0))::int as score,
                       coalesce(r.wins,0)::int as wins,
                       coalesce(r.losses,0)::int as losses,
                       coalesce(r.draws,0)::int as draws
                from public.mafia_players p
                left join (
                    select user_id,count(*) games,sum(score) score,
                           count(*) filter(where result='win') wins,
                           count(*) filter(where result='loss') losses,
                           count(*) filter(where result='draw') draws
                    from public.mafia_ratings group by user_id
                ) r on r.user_id=p.user_id
                where p.user_id=:user_id limit 1
            """), {"user_id": int(user_id)}).mappings().first()
            return dict(row) if row else None

    def rating_details(self, user_id):
        with self.SessionLocal() as session:
            row = session.execute(text("""
                select
                    (50 + coalesce(sum(score),0))::int as score,
                    coalesce(sum(win_bonus),0)::int as win_bonus,
                    coalesce(sum(challenge_bonus),0)::int as challenge_bonus,
                    coalesce(sum(warning_penalty),0)::int as warning_penalty,
                    coalesce(sum(kick_penalty),0)::int as kick_penalty,
                    count(*) filter(where challenge_bonus > 0)::int as challenge_games,
                    coalesce(sum(challenge_bonus / 3),0)::int as challenges,
                    count(*) filter(where warning_penalty > 0)::int as warning_games,
                    coalesce(sum(warning_penalty),0)::int as warnings,
                    count(*) filter(where kick_penalty > 0)::int as kicks
                from public.mafia_ratings
                where user_id=:user_id
            """), {"user_id": int(user_id)}).mappings().one()
            return dict(row)

    def rank(self, user_id):
        with self.SessionLocal() as session:
            row = session.execute(text("""
                with totals as (
                    select p.user_id,
                           (50 + coalesce(sum(r.score),0))::int score,
                           count(r.id)::int games,
                           count(r.id) filter(where r.result='win')::int wins
                    from public.mafia_players p
                    left join public.mafia_ratings r on r.user_id=p.user_id
                    group by p.user_id
                )
                select 1 + count(*) filter(where t.score > me.score
                    or (t.score=me.score and t.wins > me.wins)
                    or (t.score=me.score and t.wins=me.wins and t.games > me.games))::int as rank,
                    me.score, me.games, me.wins,
                    (select count(*)::int from totals) as total_players
                from totals me join totals t on true
                where me.user_id=:user_id group by me.score,me.games,me.wins
            """), {"user_id": int(user_id)}).mappings().first()
            return dict(row) if row else {"rank": None, "score": BASE_SCORE, "games": 0, "wins": 0, "total_players": 0}

    def top(self, limit=10):
        with self.SessionLocal() as session:
            rows = session.execute(text("""
                select p.user_id,
                       coalesce(p.nickname,p.first_name,p.username,p.user_id::text) as name,
                       count(r.id)::int as games,
                       (50 + coalesce(sum(r.score),0))::int as score,
                       count(r.id) filter (where r.result='win')::int as wins
                from public.mafia_players p
                left join public.mafia_ratings r on r.user_id=p.user_id
                group by p.user_id,p.nickname,p.first_name,p.username
                order by score desc, wins desc, games desc, p.user_id
                limit :limit
            """), {"limit": max(1, min(int(limit), 100))}).mappings().all()
            return [dict(row) for row in rows]

    def group_summary(self, user_id, group_chat_id):
        with self.SessionLocal() as session:
            row = session.execute(text("""
                select count(*)::int games,
                       (50 + coalesce(sum(r.score),0))::int score,
                       count(*) filter(where r.result='win')::int wins,
                       count(*) filter(where r.result='loss')::int losses,
                       count(*) filter(where r.result='draw')::int draws,
                       coalesce(sum(r.win_bonus),0)::int win_bonus,
                       coalesce(sum(r.challenge_bonus),0)::int challenge_bonus,
                       coalesce(sum(r.warning_penalty),0)::int warning_penalty,
                       coalesce(sum(r.kick_penalty),0)::int kick_penalty
                from public.mafia_ratings r join public.mafia_games g on g.id=r.game_id
                where r.user_id=:user_id and g.group_chat_id=:group_chat_id
            """), {"user_id": int(user_id), "group_chat_id": int(group_chat_id)}).mappings().one()
            return dict(row)

    def group_top(self, group_chat_id, limit=10):
        with self.SessionLocal() as session:
            rows = session.execute(text("""
                select p.user_id,
                       coalesce(p.nickname,p.first_name,p.username,p.user_id::text) as name,
                       count(r.id)::int as games,
                       (50 + coalesce(sum(r.score),0))::int as score,
                       count(r.id) filter (where r.result='win')::int as wins
                from public.mafia_players p
                join public.mafia_ratings r on r.user_id=p.user_id
                join public.mafia_games g on g.id=r.game_id
                where g.group_chat_id=:group_chat_id
                group by p.user_id,p.nickname,p.first_name,p.username
                order by score desc,wins desc,games desc,p.user_id limit :limit
            """), {"group_chat_id": int(group_chat_id), "limit": max(1,min(int(limit),100))}).mappings().all()
            return [dict(row) for row in rows]
