
import os
import sqlite3
import threading
import time
from datetime import datetime, date, timedelta

# ---- 数据库文件位置：项目根目录/data/health.db ----
_BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(_BASE_DIR, "data", "health.db")

_lock = threading.Lock()
_conn = None


# =================== 建表 ==================

_SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at  INTEGER NOT NULL,          -- 开始工作的时间 (UTC 秒)
    ended_at    INTEGER,                   -- 结束时间，NULL 表示还在进行
    work_seconds INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS events (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id       INTEGER,              -- 属于哪个工作时段
    kind             TEXT    NOT NULL,     -- bad_posture / too_close / sitting_long
    started_at       INTEGER NOT NULL,
    duration_seconds INTEGER NOT NULL DEFAULT 0,
    detail           TEXT,                 -- 附加信息(JSON 字符串)，比如角度值
    FOREIGN KEY (session_id) REFERENCES sessions(id)
);

CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_events_started ON events(started_at);
CREATE INDEX IF NOT EXISTS idx_events_kind    ON events(kind, started_at);
"""

#事件类型（全组统一，别再改）
KIND_SHOULDER     = "posture_shoulder"# 肩部倾斜
KIND_HEAD         = "posture_head"# 头部左右偏移
KIND_HUNCHBACK    = "posture_hunchback"# 疑似驼背（低头 或 耳肩比异常）
KIND_TOO_CLOSE    = "too_close" # 离屏幕过近
KIND_SITTING_LONG = "sitting_long" # 久坐

POSTURE_KINDS = (KIND_SHOULDER, KIND_HEAD, KIND_HUNCHBACK)
ALL_KINDS = POSTURE_KINDS + (KIND_TOO_CLOSE, KIND_SITTING_LONG)


def init_db():
    """创建数据库和表。程序启动时调用一次即可，重复调用安全。"""
    global _conn
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)

    with _lock:
        if _conn is None:
            _conn = sqlite3.connect(DB_PATH, check_same_thread=False)
            _conn.row_factory = sqlite3.Row
            _conn.execute("PRAGMA journal_mode=WAL")   # 关键：多线程读写更稳
            _conn.execute("PRAGMA foreign_keys=ON")
        _conn.executescript(_SCHEMA)
        _conn.commit()
    return _conn


def _get_conn():
    if _conn is None:
        init_db()
    return _conn


#工作时段

def start_session() -> int:
    """开始一个新的工作时段，返回 session_id。"""
    now = int(time.time())
    with _lock:
        cur = _get_conn().execute(
            "INSERT INTO sessions (started_at, work_seconds) VALUES (?, 0)", (now,)
        )
        _get_conn().commit()
        return cur.lastrowid


def update_work_seconds(session_id: int, seconds: int):
    """定时更新当前时段的累计工作时长（B 的计时器每秒/每分钟调一次）。"""
    with _lock:
        _get_conn().execute(
            "UPDATE sessions SET work_seconds = ? WHERE id = ?", (seconds, session_id)
        )
        _get_conn().commit()


def end_session(session_id: int):
    """结束工作时段。程序退出时调用。"""
    with _lock:
        _get_conn().execute(
            "UPDATE sessions SET ended_at = ? WHERE id = ?", (int(time.time()), session_id)
        )
        _get_conn().commit()


#事件记录

def log_event(kind, duration_seconds=0, session_id=None, detail=None) -> int:
    with _lock:
        cur = _get_conn().execute(
            "INSERT INTO events (session_id, kind, started_at, duration_seconds, detail) "
            "VALUES (?, ?, ?, ?, ?)",
            (session_id, kind, int(time.time()), duration_seconds, detail))
        _get_conn().commit()
        return cur.lastrowid


def update_event_duration(event_id: int, duration_seconds: int):
    """事件结束时把时长修正为真实值（写入时只知道 5 秒阈值）。"""
    with _lock:
        _get_conn().execute(
            "UPDATE events SET duration_seconds = ? WHERE id = ?",
            (duration_seconds, event_id))
        _get_conn().commit()


#设置项

# 默认设置，第一次运行时写进库
DEFAULT_SETTINGS = {
    "shoulder_threshold_deg":   "4.0",# 肩线倾斜阈值（度）
    "head_threshold_ratio":     "0.15",# 头部左右偏移阈值（肩宽倍数）
    "hunchback_threshold_ratio": "0.40",# 耳肩水平距离比阈值
    "distance_threshold_cm":    "50",# 距离过近阈值
    "landmark_confidence":      "0.6",# 关键点置信度下限
    "alert_cooldown_sec":       "60",# 同一问题再次提醒的间隔
    "sitting_limit_min":        "45",
    "voice_enabled":            "true",
}


def get_settings() -> dict:
    """读出全部设置，缺的用默认值补齐。"""
    with _lock:
        rows = _get_conn().execute("SELECT key, value FROM settings").fetchall()
    result = dict(DEFAULT_SETTINGS)
    result.update({r["key"]: r["value"] for r in rows})
    return result


def set_setting(key: str, value: str):
    with _lock:
        _get_conn().execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, str(value)),
        )
        _get_conn().commit()


#给 D 的统计接口!!!

def _local_day_range(day: date):
    """把'某一天'转成 [起, 止) 的 UTC 秒数区间。"""
    start_local = datetime.combine(day, datetime.min.time())
    start_utc = int(start_local.timestamp())
    end_utc = int((start_local + timedelta(days=1)).timestamp())
    return start_utc, end_utc


def daily_stats(day: date | None = None) -> dict:
    """
    返回某一天（默认今天）的统计，D 拿去画折线图。
    结构：
    {
      "date": "2026-11-02",
      "counts": {"bad_posture": 12, "too_close": 3, "sitting_long": 2},
      "total_seconds": 3600,
      "work_seconds": 7200
    }
    """
    day = day or date.today()
    start, end = _local_day_range(day)

    with _lock:
        rows = _get_conn().execute(
            "SELECT kind, COUNT(*) AS c, SUM(duration_seconds) AS s "
            "FROM events WHERE started_at >= ? AND started_at < ? GROUP BY kind",
            (start, end),
        ).fetchall()

        work = _get_conn().execute(
            "SELECT SUM(work_seconds) AS w FROM sessions "
            "WHERE started_at < ? AND (ended_at IS NULL OR ended_at >= ?)",
            (end, start),
        ).fetchone()

    counts = {k: 0 for k in ALL_KINDS}
    total = 0
    for r in rows:
        counts[r["kind"]] = r["c"]
        total += (r["s"] or 0)

    return {
        "date": str(day),
        "counts": counts,
        "bad_posture_total": sum(counts[k] for k in POSTURE_KINDS),
        "total_seconds": total,
        "work_seconds": work["w"] or 0,

    }


def weekly_stats(end_day: date | None = None) -> list[dict]:
    """最近 7 天，每天一条 daily_stats，给折线图用。"""
    end_day = end_day or date.today()
    return [daily_stats(end_day - timedelta(days=i)) for i in range(6, -1, -1)]


#自测

if __name__ == "__main__":
    init_db()
    sid = start_session()
    log_event(KIND_SHOULDER, 6, sid)
    log_event(KIND_HUNCHBACK, 8, sid)
    log_event(KIND_TOO_CLOSE, 2, sid)
    update_work_seconds(sid, 600)
    set_setting("voice_enabled", "false")

    print("设置:", get_settings())
    print("今日:", daily_stats())
    end_session(sid)
    print("数据库位置:", DB_PATH)