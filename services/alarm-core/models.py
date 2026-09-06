import os

from sqlalchemy import Boolean, Column, DateTime, Integer, String, create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

DB_PATH = os.environ.get("DB_PATH", "/data/alarms.db")
engine = create_engine(f"sqlite:///{DB_PATH}", connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(bind=engine)
Base = declarative_base()


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


def init_db():
    Base.metadata.create_all(engine)
