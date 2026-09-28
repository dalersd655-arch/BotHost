import sqlite3
import asyncio
import json
import secrets
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
from config import DB_PATH, ADMIN_IDS, DEFAULT_BOTS_LIMIT

def _get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    return conn

def _init_db_sync():
    with _get_connection() as conn:
        cursor = conn.cursor()
        
        # Users table
        cursor.execute(f"""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            telegram_id INTEGER UNIQUE NOT NULL,
            username TEXT,
            first_name TEXT,
            is_admin BOOLEAN DEFAULT 0,
            is_blocked BOOLEAN DEFAULT 0,
            bots_limit INTEGER DEFAULT {DEFAULT_BOTS_LIMIT},
            is_subscribed BOOLEAN DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_active TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """)

        # Bots table
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS bots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            bot_token TEXT NOT NULL,
            container_id TEXT,
            status TEXT DEFAULT 'STOPPED',
            env_vars TEXT DEFAULT '{}',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
        );
        """)

        # Auth tokens for web login
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS login_tokens (
            token TEXT PRIMARY KEY,
            telegram_id INTEGER NOT NULL,
            expires_at TIMESTAMP NOT NULL,
            used BOOLEAN DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """)

        # System Logs
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS system_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            bot_id INTEGER,
            level TEXT DEFAULT 'INFO',
            message TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """)
        
        conn.commit()

async def init_db():
    await asyncio.to_thread(_init_db_sync)

# User operations
def _get_or_create_user_sync(telegram_id: int, username: Optional[str], first_name: Optional[str]) -> Dict[str, Any]:
    with _get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM users WHERE telegram_id = ?", (telegram_id,))
        row = cursor.fetchone()
        
        is_admin = 1 if telegram_id in ADMIN_IDS else 0
        now = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")

        if row:
            # Update user info and last_active
            update_admin = 1 if (row["is_admin"] or is_admin) else 0
            cursor.execute("""
                UPDATE users 
                SET username = ?, first_name = ?, last_active = ?, is_admin = ?
                WHERE telegram_id = ?
            """, (username, first_name, now, update_admin, telegram_id))
            conn.commit()
            cursor.execute("SELECT * FROM users WHERE telegram_id = ?", (telegram_id,))
            return dict(cursor.fetchone())
        else:
            cursor.execute("""
                INSERT INTO users (telegram_id, username, first_name, is_admin, is_blocked, bots_limit, is_subscribed, last_active)
                VALUES (?, ?, ?, ?, 0, ?, 0, ?)
            """, (telegram_id, username, first_name, is_admin, DEFAULT_BOTS_LIMIT, now))
            conn.commit()
            cursor.execute("SELECT * FROM users WHERE telegram_id = ?", (telegram_id,))
            return dict(cursor.fetchone())

async def get_or_create_user(telegram_id: int, username: Optional[str] = None, first_name: Optional[str] = None) -> Dict[str, Any]:
    return await asyncio.to_thread(_get_or_create_user_sync, telegram_id, username, first_name)

def _get_user_by_telegram_id_sync(telegram_id: int) -> Optional[Dict[str, Any]]:
    with _get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM users WHERE telegram_id = ?", (telegram_id,))
        row = cursor.fetchone()
        return dict(row) if row else None

async def get_user_by_telegram_id(telegram_id: int) -> Optional[Dict[str, Any]]:
    return await asyncio.to_thread(_get_user_by_telegram_id_sync, telegram_id)

def _get_user_by_id_sync(user_id: int) -> Optional[Dict[str, Any]]:
    with _get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM users WHERE id = ?", (user_id,))
        row = cursor.fetchone()
        return dict(row) if row else None

async def get_user_by_id(user_id: int) -> Optional[Dict[str, Any]]:
    return await asyncio.to_thread(_get_user_by_id_sync, user_id)

def _update_user_subscription_sync(telegram_id: int, is_subscribed: bool):
    with _get_connection() as conn:
        conn.execute("UPDATE users SET is_subscribed = ? WHERE telegram_id = ?", (1 if is_subscribed else 0, telegram_id))
        conn.commit()

async def update_user_subscription(telegram_id: int, is_subscribed: bool):
    await asyncio.to_thread(_update_user_subscription_sync, telegram_id, is_subscribed)

def _update_user_block_status_sync(user_id: int, is_blocked: bool):
    with _get_connection() as conn:
        conn.execute("UPDATE users SET is_blocked = ? WHERE id = ?", (1 if is_blocked else 0, user_id))
        conn.commit()

async def update_user_block_status(user_id: int, is_blocked: bool):
    await asyncio.to_thread(_update_user_block_status_sync, user_id, is_blocked)

def _update_user_limit_sync(user_id: int, bots_limit: int):
    with _get_connection() as conn:
        conn.execute("UPDATE users SET bots_limit = ? WHERE id = ?", (bots_limit, user_id))
        conn.commit()

async def update_user_limit(user_id: int, bots_limit: int):
    await asyncio.to_thread(_update_user_limit_sync, user_id, bots_limit)

def _get_all_users_sync() -> List[Dict[str, Any]]:
    with _get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT u.*, COUNT(b.id) AS bots_count
            FROM users u
            LEFT JOIN bots b ON u.id = b.user_id
            GROUP BY u.id
            ORDER BY u.created_at DESC
        """)
        return [dict(r) for r in cursor.fetchall()]

async def get_all_users() -> List[Dict[str, Any]]:
    return await asyncio.to_thread(_get_all_users_sync)

# Bot operations
def _create_bot_sync(user_id: int, name: str, bot_token: str, env_vars: Optional[dict] = None) -> Dict[str, Any]:
    env_json = json.dumps(env_vars or {})
    with _get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO bots (user_id, name, bot_token, env_vars, status)
            VALUES (?, ?, ?, ?, 'STOPPED')
        """, (user_id, name, bot_token, env_json))
        conn.commit()
        bot_id = cursor.lastrowid
        cursor.execute("SELECT * FROM bots WHERE id = ?", (bot_id,))
        return dict(cursor.fetchone())

async def create_bot(user_id: int, name: str, bot_token: str, env_vars: Optional[dict] = None) -> Dict[str, Any]:
    return await asyncio.to_thread(_create_bot_sync, user_id, name, bot_token, env_vars)

def _get_bot_by_id_sync(bot_id: int) -> Optional[Dict[str, Any]]:
    with _get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM bots WHERE id = ?", (bot_id,))
        row = cursor.fetchone()
        return dict(row) if row else None

async def get_bot_by_id(bot_id: int) -> Optional[Dict[str, Any]]:
    return await asyncio.to_thread(_get_bot_by_id_sync, bot_id)

def _get_bots_by_user_id_sync(user_id: int) -> List[Dict[str, Any]]:
    with _get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM bots WHERE user_id = ? ORDER BY created_at DESC", (user_id,))
        return [dict(r) for r in cursor.fetchall()]

async def get_bots_by_user_id(user_id: int) -> List[Dict[str, Any]]:
    return await asyncio.to_thread(_get_bots_by_user_id_sync, user_id)

def _get_all_bots_sync() -> List[Dict[str, Any]]:
    with _get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT b.*, u.telegram_id, u.username
            FROM bots b
            JOIN users u ON b.user_id = u.id
            ORDER BY b.created_at DESC
        """)
        return [dict(r) for r in cursor.fetchall()]

async def get_all_bots() -> List[Dict[str, Any]]:
    return await asyncio.to_thread(_get_all_bots_sync)

def _update_bot_status_sync(bot_id: int, status: str, container_id: Optional[str] = None):
    now = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    with _get_connection() as conn:
        if container_id is not None:
            conn.execute("UPDATE bots SET status = ?, container_id = ?, updated_at = ? WHERE id = ?", (status, container_id, now, bot_id))
        else:
            conn.execute("UPDATE bots SET status = ?, updated_at = ? WHERE id = ?", (status, now, bot_id))
        conn.commit()

async def update_bot_status(bot_id: int, status: str, container_id: Optional[str] = None):
    await asyncio.to_thread(_update_bot_status_sync, bot_id, status, container_id)

def _update_bot_config_sync(bot_id: int, name: Optional[str] = None, bot_token: Optional[str] = None, env_vars: Optional[dict] = None):
    now = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    with _get_connection() as conn:
        updates = ["updated_at = ?"]
        params = [now]
        if name:
            updates.append("name = ?")
            params.append(name)
        if bot_token:
            updates.append("bot_token = ?")
            params.append(bot_token)
        if env_vars is not None:
            updates.append("env_vars = ?")
            params.append(json.dumps(env_vars))
        params.append(bot_id)
        conn.execute(f"UPDATE bots SET {', '.join(updates)} WHERE id = ?", params)
        conn.commit()

async def update_bot_config(bot_id: int, name: Optional[str] = None, bot_token: Optional[str] = None, env_vars: Optional[dict] = None):
    await asyncio.to_thread(_update_bot_config_sync, bot_id, name, bot_token, env_vars)

def _delete_bot_sync(bot_id: int):
    with _get_connection() as conn:
        conn.execute("DELETE FROM bots WHERE id = ?", (bot_id,))
        conn.commit()

async def delete_bot(bot_id: int):
    await asyncio.to_thread(_delete_bot_sync, bot_id)

# Login Tokens
def _create_login_token_sync(telegram_id: int, ttl_minutes: int = 15) -> str:
    token = secrets.token_urlsafe(32)
    expires_at = (datetime.utcnow() + timedelta(minutes=ttl_minutes)).strftime("%Y-%m-%d %H:%M:%S")
    with _get_connection() as conn:
        conn.execute("""
            INSERT INTO login_tokens (token, telegram_id, expires_at, used)
            VALUES (?, ?, ?, 0)
        """, (token, telegram_id, expires_at))
        conn.commit()
    return token

async def create_login_token(telegram_id: int, ttl_minutes: int = 15) -> str:
    return await asyncio.to_thread(_create_login_token_sync, telegram_id, ttl_minutes)

def _verify_and_use_login_token_sync(token: str) -> Optional[int]:
    now = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    with _get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT telegram_id FROM login_tokens
            WHERE token = ? AND used = 0 AND expires_at > ?
        """, (token, now))
        row = cursor.fetchone()
        if row:
            conn.execute("UPDATE login_tokens SET used = 1 WHERE token = ?", (token,))
            conn.commit()
            return row["telegram_id"]
        return None

async def verify_and_use_login_token(token: str) -> Optional[int]:
    return await asyncio.to_thread(_verify_and_use_login_token_sync, token)

# Logging
def _add_system_log_sync(message: str, bot_id: Optional[int] = None, level: str = "INFO"):
    with _get_connection() as conn:
        conn.execute("INSERT INTO system_logs (bot_id, level, message) VALUES (?, ?, ?)", (bot_id, level, message))
        conn.commit()

async def add_system_log(message: str, bot_id: Optional[int] = None, level: str = "INFO"):
    await asyncio.to_thread(_add_system_log_sync, message, bot_id, level)

def _get_system_logs_sync(limit: int = 100) -> List[Dict[str, Any]]:
    with _get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM system_logs ORDER BY created_at DESC LIMIT ?", (limit,))
        return [dict(r) for r in cursor.fetchall()]

async def get_system_logs(limit: int = 100) -> List[Dict[str, Any]]:
    return await asyncio.to_thread(_get_system_logs_sync, limit)
