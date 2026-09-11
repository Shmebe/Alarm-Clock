import logging
import os
import signal
import subprocess
import threading
import time as time_mod
from datetime import datetime, timedelta
from typing import List, Optional

import requests
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, field_validator

from models import Alarm, SessionLocal, init_db
from scheduler import on_bt_connected, start_background, stop_ringing
from state_machine import AlarmState

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("alarm-core")

BT_MANAGER_URL = os.environ.get("BT_MANAGER_URL", "http://localhost:8081")
SOUNDS_DIR = os.environ.get("SOUNDS_DIR", "/app/sounds")
AUDIO_BUFFER_ARGS = ["--buffer-time=1000000", "--period-time=200000"]

app = FastAPI(title="alarm-core")

_test_lock = threading.Lock()
_test_process = None


def _sound_exists(sound_file: str) -> bool:
    return os.path.isfile(os.path.join(SOUNDS_DIR, sound_file))


class DebugPlayIn(BaseModel):
    sound_file: str
    volume: int = 50


class SnoozeIn(BaseModel):
    minutes: int = 9


class AlarmIn(BaseModel):
    time: str
    days: str = "once"
    label: str = ""
    sound_file: str = "classic-beep.wav"
    volume: int = 50
    enabled: bool = True

    @field_validator("volume")
    @classmethod
    def _clamp_volume(cls, v):
        return max(0, min(100, v))


class AlarmOut(AlarmIn):
    id: int
    state: str
    last_fired_at: Optional[datetime] = None
    snooze_until: Optional[datetime] = None

    class Config:
        from_attributes = True


@app.on_event("startup")
def startup():
    init_db()
    start_background()


@app.get("/alarms", response_model=List[AlarmOut])
def list_alarms():
    session = SessionLocal()
    try:
        return session.query(Alarm).all()
    except Exception:
        log.exception("Failed to list alarms")
        raise HTTPException(500, "Failed to read alarms - check alarm-core logs")
    finally:
        session.close()


@app.post("/alarms", response_model=AlarmOut)
def create_alarm(alarm: AlarmIn):
    if not _sound_exists(alarm.sound_file):
        raise HTTPException(400, f"Sound file not found in library: {alarm.sound_file}")
    session = SessionLocal()
    try:
        db_alarm = Alarm(**alarm.model_dump(), state=AlarmState.SCHEDULED.value)
        session.add(db_alarm)
        session.commit()
        session.refresh(db_alarm)
        log.info("Created alarm %s at %s (days=%s, vol=%s)", db_alarm.id, db_alarm.time, db_alarm.days, db_alarm.volume)
        return db_alarm
    except Exception:
        session.rollback()
        log.exception("Failed to create alarm")
        raise HTTPException(500, "Failed to save alarm - check alarm-core logs")
    finally:
        session.close()


@app.put("/alarms/{alarm_id}", response_model=AlarmOut)
def update_alarm(alarm_id: int, alarm: AlarmIn):
    if not _sound_exists(alarm.sound_file):
        raise HTTPException(400, f"Sound file not found in library: {alarm.sound_file}")
    session = SessionLocal()
    try:
        db_alarm = session.get(Alarm, alarm_id)
        if not db_alarm:
            raise HTTPException(404, "Alarm not found")
        for key, value in alarm.model_dump().items():
            setattr(db_alarm, key, value)
        session.commit()
        session.refresh(db_alarm)
        return db_alarm
    except HTTPException:
        raise
    except Exception:
        session.rollback()
        log.exception("Failed to update alarm %s", alarm_id)
        raise HTTPException(500, "Failed to update alarm - check alarm-core logs")
    finally:
        session.close()


@app.delete("/alarms/{alarm_id}")
def delete_alarm(alarm_id: int):
    stop_ringing(alarm_id)
    session = SessionLocal()
    try:
        db_alarm = session.get(Alarm, alarm_id)
        if not db_alarm:
            raise HTTPException(404, "Alarm not found")
        session.delete(db_alarm)
        session.commit()
        return {"ok": True}
    finally:
        session.close()


@app.post("/alarms/{alarm_id}/dismiss")
def dismiss_alarm(alarm_id: int):
    stop_ringing(alarm_id)
    session = SessionLocal()
    try:
        db_alarm = session.get(Alarm, alarm_id)
        if not db_alarm:
            raise HTTPException(404, "Alarm not found")
        db_alarm.state = AlarmState.DISMISSED.value
        db_alarm.snooze_until = None
        session.commit()
        return {"ok": True}
    finally:
        session.close()


@app.post("/alarms/{alarm_id}/snooze")
def snooze_alarm(alarm_id: int, payload: SnoozeIn = SnoozeIn()):
    stop_ringing(alarm_id)
    session = SessionLocal()
    try:
        db_alarm = session.get(Alarm, alarm_id)
        if not db_alarm:
            raise HTTPException(404, "Alarm not found")
        minutes = max(1, payload.minutes)
        db_alarm.state = AlarmState.SCHEDULED.value
        db_alarm.snooze_until = datetime.now() + timedelta(minutes=minutes)
        session.commit()
        return {"ok": True, "snooze_until": db_alarm.snooze_until.isoformat()}
    finally:
        session.close()


@app.post("/alarms/{alarm_id}/toggle")
def toggle_alarm(alarm_id: int):
    session = SessionLocal()
    try:
        db_alarm = session.get(Alarm, alarm_id)
        if not db_alarm:
            raise HTTPException(404, "Alarm not found")
        db_alarm.enabled = not db_alarm.enabled
        if not db_alarm.enabled and db_alarm.state in (
            AlarmState.TRIGGERED.value,
            AlarmState.WAITING_FOR_SPEAKER.value,
            AlarmState.PLAYING.value,
        ):
            stop_ringing(alarm_id)
            db_alarm.state = AlarmState.DISMISSED.value
            db_alarm.snooze_until = None
        session.commit()
        return {"ok": True, "enabled": db_alarm.enabled}
    finally:
        session.close()


@app.post("/events/bt-connected")
def bt_connected_event():
    on_bt_connected()
    return {"ok": True}


@app.get("/sounds")
def list_sounds():
    try:
        files = sorted(
            f for f in os.listdir(SOUNDS_DIR)
            if f.lower().endswith((".wav", ".mp3", ".ogg"))
        )
    except FileNotFoundError:
        files = []
    return {"sounds": files}


@app.get("/server-time")
def server_time():
    now = datetime.now()
    tz_name = os.environ.get("TZ") or (time_mod.tzname[0] if time_mod.tzname else "unknown")
    return {"tz": tz_name, "now": now.isoformat(), "now_hhmm": now.strftime("%H:%M")}


@app.get("/bt-status")
def bt_status():
    try:
        r = requests.get(f"{BT_MANAGER_URL}/status", timeout=3)
        return r.json()
    except requests.RequestException:
        return {"connected": False, "device_mac": None}


def _stop_test_process():
    global _test_process
    if _test_process and _test_process.poll() is None:
        _test_process.terminate()
        try:
            _test_process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            _test_process.kill()
    _test_process = None


@app.post("/debug/play")
def debug_play(payload: DebugPlayIn):
    global _test_process
    status = bt_status()
    if not status.get("connected"):
        raise HTTPException(400, "Speaker not connected")

    volume = max(0, min(100, payload.volume))
    device_arg = f"bluealsa:DEV={status['device_mac']},PROFILE=a2dp,VOL={volume}"
    sound_path = os.path.join(SOUNDS_DIR, payload.sound_file)
    if not os.path.isfile(sound_path):
        raise HTTPException(404, f"Sound file not found: {payload.sound_file}")

    with _test_lock:
        _stop_test_process()
        _test_process = subprocess.Popen(["aplay", "-D", device_arg, *AUDIO_BUFFER_ARGS, sound_path])
    return {"ok": True, "playing": payload.sound_file, "volume": volume}


@app.post("/debug/pause")
def debug_pause():
    with _test_lock:
        if _test_process and _test_process.poll() is None:
            _test_process.send_signal(signal.SIGSTOP)
            return {"ok": True, "paused": True}
    return {"ok": False, "reason": "nothing playing"}


@app.post("/debug/resume")
def debug_resume():
    with _test_lock:
        if _test_process and _test_process.poll() is None:
            _test_process.send_signal(signal.SIGCONT)
            return {"ok": True, "paused": False}
    return {"ok": False, "reason": "nothing playing"}


@app.post("/debug/stop")
def debug_stop():
    with _test_lock:
        _stop_test_process()
    return {"ok": True}
