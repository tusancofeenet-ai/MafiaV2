import time
import json

from sqlalchemy import text
from .base import DatabaseRepository


class GameRepository(DatabaseRepository):
    """Persistence for mafia_games and mafia_game_players with short TTL caches."""

    CACHE_TTL = 0.75

    def __init__(self, database_url=None):
        super().__init__(database_url)
        self._active_cache: dict[int, tuple[float, dict | None]] = {}
        self._players_cache: dict[str, tuple[float, list[dict]]] = {}

    def _invalidate(self, group_chat_id=None, game_id=None):
        if group_chat_id is None:
            self._active_cache.clear()
        else:
            self._active_cache.pop(int(group_chat_id), None)
        if game_id is None:
            self._players_cache.clear()
        else:
            self._players_cache.pop(str(game_id), None)

    def next_event_number(self, group_chat_id):
        with self.SessionLocal() as session:
            value = session.execute(text("select coalesce(max(event_number),0)+1 from public.mafia_games where group_chat_id=:group_chat_id"), {"group_chat_id": int(group_chat_id)}).scalar_one()
            return int(value)

    def create_game(self, group_chat_id, moderator_id=None, scenario_id=None, event_number=None, state=None):
        event_number = int(event_number) if event_number is not None else self.next_event_number(group_chat_id)
        with self.SessionLocal() as session:
            row = session.execute(text("""
                insert into public.mafia_games(event_number,group_chat_id,moderator_id,scenario_id,status,state)
                values(:event_number,:group_chat_id,:moderator_id,:scenario_id,'lobby',CAST(:state AS jsonb)) returning id
            """), {"event_number": event_number, "group_chat_id": int(group_chat_id), "moderator_id": moderator_id, "scenario_id": scenario_id, "state": json.dumps(state or {}, ensure_ascii=False)}).scalar_one()
            session.commit()
        self._invalidate(int(group_chat_id), row)
        return row

    def get_game(self, game_id):
        """Return a game by id regardless of lifecycle status."""
        with self.SessionLocal() as session:
            row = session.execute(text("select * from public.mafia_games where id=:game_id limit 1"), {"game_id": int(game_id)}).mappings().first()
            return dict(row) if row else None

    def get_finished_game(self, game_id):
        """Return a finalized game without treating it as an active game."""
        with self.SessionLocal() as session:
            row = session.execute(text("select * from public.mafia_games where id=:game_id and status='finished' limit 1"), {"game_id": int(game_id)}).mappings().first()
            return dict(row) if row else None

    def list_finished_games(self, group_chat_id=None, limit=50):
        with self.SessionLocal() as session:
            if group_chat_id is None:
                rows = session.execute(text("select * from public.mafia_games where status='finished' order by finished_at desc nulls last, created_at desc limit :limit"), {"limit": int(limit)}).mappings().all()
            else:
                rows = session.execute(text("select * from public.mafia_games where group_chat_id=:group_chat_id and status='finished' order by finished_at desc nulls last, created_at desc limit :limit"), {"group_chat_id": int(group_chat_id), "limit": int(limit)}).mappings().all()
            return [dict(row) for row in rows]

    def get_active_game(self, group_chat_id):
        gid = int(group_chat_id)
        cached = self._active_cache.get(gid)
        if cached and time.monotonic() - cached[0] < self.CACHE_TTL:
            return dict(cached[1]) if cached[1] else None
        with self.SessionLocal() as session:
            row = session.execute(text("""
                select * from public.mafia_games
                where group_chat_id=:group_chat_id and status in ('lobby','running','paused')
                order by created_at desc limit 1
            """), {"group_chat_id": gid}).mappings().first()
            value = dict(row) if row else None
        self._active_cache[gid] = (time.monotonic(), value)
        return dict(value) if value else None

    def list_active_games(self):
        with self.SessionLocal() as session:
            rows = session.execute(text("select * from public.mafia_games where status in ('running','paused') order by updated_at desc")).mappings().all()
            return [dict(row) for row in rows]

    def list_games(self, group_chat_id=None, limit=100):
        with self.SessionLocal() as session:
            if group_chat_id is None:
                rows = session.execute(text("select * from public.mafia_games order by created_at desc limit :limit"), {"limit": int(limit)}).mappings().all()
            else:
                rows = session.execute(text("select * from public.mafia_games where group_chat_id=:group_chat_id order by created_at desc limit :limit"), {"group_chat_id": int(group_chat_id), "limit": int(limit)}).mappings().all()
            return [dict(row) for row in rows]

    def update_game(self, game_id, **fields):
        allowed = {"event_number","moderator_id","scenario_id","status","current_turn_seat","current_turn_index","state","started_at","finished_at"}
        fields = {k:v for k,v in fields.items() if k in allowed}
        if not fields: return False
        params = {"game_id": game_id}; assignments = []
        for key, value in fields.items():
            if key == "state": assignments.append("state=CAST(:state AS jsonb)"); params[key] = json.dumps(value or {}, ensure_ascii=False)
            else: assignments.append(f"{key}=:{key}"); params[key] = value
        assignments.append("updated_at=now()")
        with self.SessionLocal() as session:
            result = session.execute(text(f"update public.mafia_games set {', '.join(assignments)} where id=:game_id"), params); session.commit()
        self._active_cache.clear(); self._invalidate(game_id=game_id); return result.rowcount > 0

    def add_player(self, game_id, player_id, seat=None, role=None, status="active", is_substitute=False):
        uid = int(player_id)
        with self.SessionLocal() as session:
            existing = session.execute(text("select id from public.mafia_game_players where game_id=:game_id and (player_id=:player_id or user_id=:user_id) limit 1"), {"game_id": game_id, "player_id": uid, "user_id": uid}).mappings().first()
            if existing: return existing["id"]
            if seat is not None and session.execute(text("select 1 from public.mafia_game_players where game_id=:game_id and seat=:seat limit 1"), {"game_id": game_id, "seat": int(seat)}).first(): raise ValueError("این صندلی قبلاً رزرو شده است")
            row = session.execute(text("insert into public.mafia_game_players(game_id,user_id,player_id,seat,role,status,is_substitute) values(:game_id,:user_id,:player_id,:seat,:role,:status,:is_substitute) returning id"), {"game_id": game_id, "user_id": uid, "player_id": uid, "seat": seat, "role": role, "status": status, "is_substitute": is_substitute}).scalar_one(); session.commit()
        self._invalidate(game_id=game_id); return row

    def list_players(self, game_id):
        key = str(game_id); cached = self._players_cache.get(key)
        if cached and time.monotonic() - cached[0] < self.CACHE_TTL: return [dict(row) for row in cached[1]]
        with self.SessionLocal() as session:
            rows = session.execute(text("select gp.*,p.username,p.first_name,p.last_name,p.nickname from public.mafia_game_players gp join public.mafia_players p on p.user_id=gp.player_id where gp.game_id=:game_id order by gp.seat nulls last,gp.joined_at"), {"game_id": game_id}).mappings().all(); value=[dict(row) for row in rows]
        self._players_cache[key]=(time.monotonic(),value); return [dict(row) for row in value]

    def set_player_role(self, game_id, player_id, role):
        with self.SessionLocal() as session:
            result=session.execute(text("update public.mafia_game_players set role=:role, updated_at=now() where game_id=:game_id and (player_id=:player_id or user_id=:player_id)"), {"game_id":game_id,"player_id":int(player_id),"role":role});session.commit()
        self._invalidate(game_id=game_id);return result.rowcount>0

    def remove_player(self, game_id, player_id):
        with self.SessionLocal() as session:
            result=session.execute(text("delete from public.mafia_game_players where game_id=:game_id and (player_id=:player_id or user_id=:player_id)"), {"game_id":game_id,"player_id":int(player_id)});session.commit()
        self._invalidate(game_id=game_id);return result.rowcount>0

    def clear_game_players(self, game_id):
        """Delete all transient player membership rows when a game is cancelled."""
        with self.SessionLocal() as session:
            result = session.execute(text("delete from public.mafia_game_players where game_id=:game_id"), {"game_id": int(game_id)})
            session.commit()
        self._invalidate(game_id=game_id)
        return result.rowcount

    def set_player_seat(self, game_id, player_id, seat):
        with self.SessionLocal() as session:
            if seat is not None and session.execute(text("select player_id from public.mafia_game_players where game_id=:game_id and seat=:seat and player_id<>:player_id limit 1"), {"game_id":game_id,"seat":int(seat),"player_id":int(player_id)}).first(): raise ValueError("این صندلی قبلاً رزرو شده است")
            result=session.execute(text("update public.mafia_game_players set seat=:seat,status=:status where game_id=:game_id and (player_id=:player_id or user_id=:player_id)"), {"game_id":game_id,"player_id":int(player_id),"seat":seat,"status":"waiting" if seat is None else "active"});session.commit()
        self._invalidate(game_id=game_id);return result.rowcount>0

    def set_player_status(self, game_id, player_id, status):
        with self.SessionLocal() as session:
            result=session.execute(text("update public.mafia_game_players set status=:status where game_id=:game_id and (player_id=:player_id or user_id=:player_id)"), {"game_id":game_id,"player_id":int(player_id),"status":status});session.commit()
        self._invalidate(game_id=game_id);return result.rowcount>0

    def set_player_alive(self, game_id, player_id, is_alive=True):
        with self.SessionLocal() as session:
            result=session.execute(text("update public.mafia_game_players set is_alive=:is_alive, updated_at=now() where game_id=:game_id and (player_id=:player_id or user_id=:player_id)"), {"game_id":game_id,"player_id":int(player_id),"is_alive":bool(is_alive)});session.commit()
        self._invalidate(game_id=game_id);return result.rowcount>0

    def promote_waiting_player(self, game_id, seat):
        with self.SessionLocal() as session:
            row=session.execute(text("select id,player_id,user_id from public.mafia_game_players where game_id=:game_id and seat is null and status='waiting' order by joined_at limit 1"), {"game_id":game_id}).mappings().first()
            if not row:return None
            if session.execute(text("select 1 from public.mafia_game_players where game_id=:game_id and seat=:seat limit 1"), {"game_id":game_id,"seat":int(seat)}).first():raise ValueError("این صندلی قبلاً رزرو شده است")
            session.execute(text("update public.mafia_game_players set seat=:seat,status='active',is_substitute=false where id=:id"), {"id":row["id"],"seat":int(seat)});session.commit()
        self._invalidate(game_id=game_id);return {"id":row["id"],"player_id":row["player_id"] or row["user_id"],"seat":int(seat)}
