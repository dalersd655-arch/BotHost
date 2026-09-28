from datetime import datetime
from sqlalchemy import create_engine, BigInteger, String, Boolean, Integer, Float, DateTime, ForeignKey, Text
from sqlalchemy.orm import declarative_base, sessionmaker, Mapped, mapped_column
from . import config as C

engine = create_engine(C.DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)
Base = declarative_base()

def now(): return datetime.utcnow()

class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)          # Telegram ID
    username: Mapped[str | None] = mapped_column(String(64), nullable=True)
    is_blocked: Mapped[bool] = mapped_column(Boolean, default=False)
    is_subscribed: Mapped[bool] = mapped_column(Boolean, default=False)
    checked_at: Mapped[datetime] = mapped_column(DateTime, default=datetime(2000, 1, 1))
    max_bots: Mapped[int] = mapped_column(Integer, default=C.MAX_BOTS)
    mem_mb: Mapped[int] = mapped_column(Integer, default=C.BOT_MEM_MB)     # RAM на один бот
    cpu: Mapped[float] = mapped_column(Float, default=C.BOT_CPU)           # CPU на один бот
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)

class Bot(Base):
    __tablename__ = "bots"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"), index=True)
    name: Mapped[str] = mapped_column(String(40))
    token_enc: Mapped[str] = mapped_column(Text)                           # зашифрован Fernet
    state: Mapped[str] = mapped_column(String(16), default="building")     # building | ready | error
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)

class ActionLog(Base):
    __tablename__ = "action_logs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, index=True)
    action: Mapped[str] = mapped_column(String(32))
    details: Mapped[str] = mapped_column(Text, default="")
    at: Mapped[datetime] = mapped_column(DateTime, default=now)

def log_action(db, user_id, action, details=""):
    db.add(ActionLog(user_id=user_id, action=action, details=details))
    db.commit()

def get_db():
    with SessionLocal() as db:
        yield db
