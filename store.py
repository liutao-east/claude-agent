"""会话与消息的 SQLite 持久化层。

保存「应用层会话 → SDK 会话(session_id)」的映射,以及每轮的用户提问 /
助手回答,供多轮追问与历史查询使用。对话的完整上下文(含工具调用)由
Claude Agent SDK 自行持久化在 ``~/.claude/projects/`` 下;本模块只保存
应用层需要的最小信息。

零第三方依赖:仅使用 Python 标准库(``sqlite3`` / ``uuid`` / ``threading``)。
"""

from __future__ import annotations

import os
import sqlite3
import threading
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime

# 数据库文件路径:默认放在当前工作目录下的 codeqa.db。
# 启动前由 server 读环境变量时该常量已被求值,故 DB_PATH 也需走环境变量。
DB_PATH: str = os.environ.get("DB_PATH", "codeqa.db")

_lock = threading.Lock()
_conn: sqlite3.Connection | None = None


def _now() -> str:
    """当前本地时间的 ISO8601 字符串(精度到秒)。"""
    return datetime.now().isoformat(timespec="seconds")


def _connect() -> sqlite3.Connection:
    """惰性创建模块级单连接(check_same_thread=False,写操作由 _lock 串行化)。"""
    global _conn
    if _conn is None:
        _conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        _conn.row_factory = sqlite3.Row
    return _conn


@dataclass
class Conversation:
    """会话记录,对应 conversations 表的一行。"""

    id: str
    sdk_session_id: str | None
    title: str | None
    created_at: str
    updated_at: str
    total_cost_usd: float
    total_turns: int
    scenario: str | None = None

    def as_dict(self) -> dict:
        return asdict(self)


def init_db() -> None:
    """建表(幂等)并开启 WAL,提升并发读写性能。"""
    conn = _connect()
    with _lock:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS conversations (
                id              TEXT PRIMARY KEY,
                sdk_session_id  TEXT,
                title           TEXT,
                created_at      TEXT NOT NULL,
                updated_at      TEXT NOT NULL,
                total_cost_usd  REAL NOT NULL DEFAULT 0,
                total_turns     INTEGER NOT NULL DEFAULT 0,
                scenario        TEXT
            )
            """
        )
        # 旧库迁移:CREATE TABLE IF NOT EXISTS 不会给已存在的表补列,
        # 故对旧库单独 ALTER 添加 scenario 列;列已存在时忽略。
        try:
            conn.execute("ALTER TABLE conversations ADD COLUMN scenario TEXT")
        except sqlite3.OperationalError:
            pass
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS messages (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                conversation_id TEXT NOT NULL,
                role            TEXT NOT NULL,
                content         TEXT NOT NULL,
                cost_usd        REAL,
                num_turns       INTEGER,
                created_at      TEXT NOT NULL,
                FOREIGN KEY (conversation_id) REFERENCES conversations(id)
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_messages_conversation "
            "ON messages(conversation_id)"
        )
        conn.commit()


def create_conversation(
    title: str | None = None, scenario: str | None = None
) -> Conversation:
    """新建一个会话,返回对应的 Conversation。"""
    conv = Conversation(
        id=str(uuid.uuid4()),
        sdk_session_id=None,
        title=title,
        created_at=_now(),
        updated_at=_now(),
        total_cost_usd=0.0,
        total_turns=0,
        scenario=scenario,
    )
    conn = _connect()
    with _lock:
        conn.execute(
            "INSERT INTO conversations "
            "(id, sdk_session_id, title, created_at, updated_at, "
            " total_cost_usd, total_turns, scenario) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                conv.id,
                conv.sdk_session_id,
                conv.title,
                conv.created_at,
                conv.updated_at,
                conv.total_cost_usd,
                conv.total_turns,
                conv.scenario,
            ),
        )
        conn.commit()
    return conv


def get_conversation(conv_id: str) -> Conversation | None:
    """按 ID 查询会话,不存在返回 None。"""
    conn = _connect()
    with _lock:
        row = conn.execute(
            "SELECT id, sdk_session_id, title, created_at, updated_at, "
            "       total_cost_usd, total_turns, scenario "
            "FROM conversations WHERE id = ?",
            (conv_id,),
        ).fetchone()
    if row is None:
        return None
    return Conversation(
        id=row["id"],
        sdk_session_id=row["sdk_session_id"],
        title=row["title"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        total_cost_usd=row["total_cost_usd"],
        total_turns=row["total_turns"],
        scenario=row["scenario"],
    )


def set_sdk_session_id(conv_id: str, sdk_session_id: str) -> None:
    """记录/更新会话对应的 SDK session_id(用于后续 resume)。幂等。"""
    conn = _connect()
    with _lock:
        conn.execute(
            "UPDATE conversations SET sdk_session_id = ?, updated_at = ? WHERE id = ?",
            (sdk_session_id, _now(), conv_id),
        )
        conn.commit()


def add_message(
    conv_id: str,
    role: str,
    content: str,
    cost_usd: float | None = None,
    num_turns: int | None = None,
) -> None:
    """追加一条消息(role 为 'user' 或 'assistant')。"""
    conn = _connect()
    with _lock:
        conn.execute(
            "INSERT INTO messages "
            "(conversation_id, role, content, cost_usd, num_turns, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (conv_id, role, content, cost_usd, num_turns, _now()),
        )
        conn.commit()


def touch(conv_id: str, *, add_cost: float = 0.0, add_turns: int = 0) -> None:
    """更新会话的最近活动时间,并累加成本与轮数。"""
    conn = _connect()
    with _lock:
        conn.execute(
            "UPDATE conversations SET "
            "  updated_at = ?, "
            "  total_cost_usd = total_cost_usd + ?, "
            "  total_turns = total_turns + ? "
            "WHERE id = ?",
            (_now(), add_cost, add_turns, conv_id),
        )
        conn.commit()


def list_conversations(limit: int = 50) -> list[dict]:
    """按最近活动倒序返回会话摘要列表。"""
    conn = _connect()
    with _lock:
        rows = conn.execute(
            "SELECT id, title, created_at, updated_at, "
            "       total_cost_usd, total_turns, sdk_session_id, scenario "
            "FROM conversations ORDER BY updated_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [dict(r) for r in rows]


def list_messages(conv_id: str) -> list[dict]:
    """按写入顺序返回某会话的全部消息。"""
    conn = _connect()
    with _lock:
        rows = conn.execute(
            "SELECT id, role, content, cost_usd, num_turns, created_at "
            "FROM messages WHERE conversation_id = ? ORDER BY id ASC",
            (conv_id,),
        ).fetchall()
    return [dict(r) for r in rows]
