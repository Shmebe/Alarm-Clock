import logging
import os

from sqlalchemy import Boolean, Column, DateTime, Integer, String, create_engine, text
from sqlalchemy.orm import declarative_base, sessionmaker

log = logging.getLogger("models")

DB_PATH = os.environ.get("DB_PATH", "/data/alarms.db")
engine = create_engine(f"sqlite:///{DB_PATH}", connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(bind=engine)
Base = declarative_base()

# Any column added to the model after the table already existed on disk must
# be listed here. SQLAlchemy's create_all() only creates *missing tables*,
# never adds columns to a table that's already there - a schema drift here
# breaks every read/write with "no such column" until the DB file is wiped
# or the column is added by hand. This makes it self-healing instead.
_COLUMNS_ADDED_AFTER_LAUNCH = {
    "volume": "INTEGER DEFAULT 50",
    "sound_file": "TEXT DEFAULT 'classic-beep.wav'",
}


class Alarm(Base):
    __tablename__ = "alarms"

    id = Column(Integer, primary_key=True)
    time = Column(String, nullable=False)          # "HH:MM"
    days = Column(String, default="once")           # "mon,tue,wed,thu,fri" or "once"
    label = Column(String, default="")
    sound_file = Column(String, nullable=False, default="classic-beep.wav")
    volume = Column(Integer, default=50)            # 0-100, forwarded to bluealsa's VOL=
    enabled = Column(Boolean, default=True)
    state = Column(String, default="scheduled")
    last_fired_at = Column(DateTime, nullable=True)


def _migrate_missing_columns():
    with engine.begin() as conn:
        existing = {row[1] for row in conn.execute(text("PRAGMA table_info(alarms)"))}
        for col, ddl in _COLUMNS_ADDED_AFTER_LAUNCH.items():
            if col not in existing:
                log.warning("Migrating: adding missing column '%s' to alarms table", col)
                conn.execute(text(f"ALTER TABLE alarms ADD COLUMN {col} {ddl}"))


def init_db():
    Base.metadata.create_all(engine)
    _migrate_missing_columns()
