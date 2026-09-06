import logging
import os
import subprocess
import threading
import time
from datetime import datetime

import requests

from models import Alarm, SessionLocal
from state_machine import AlarmState

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("scheduler")

BT_MANAGER_URL = os.environ.get("BT_MANAGER_URL", "http://localhost:8081")
SOUNDS_DIR = os.environ.get("SOUNDS_DIR", "/app/sounds")
CHECK_INTERVAL = 20  # seconds


def _bt_status():
    try:
        r = requests.get(f"{BT_MANAGER_URL}/status", timeout=3)
        r.raise_for_status()
        return r.json()
    except requests.RequestException:
        return {"connected": False, "device_mac": None}


def _play_sound(sound_file, device_mac, volume=50):
    volume = max(0, min(100, volume))
    device_arg = f"bluealsa:DEV={device_mac},PROFILE=a2dp,VOL={volume}"
    sound_path = os.path.join(SOUNDS_DIR, sound_file)
    if not os.path.isfile(sound_path):
        log.error("Sound file missing, cannot play: %s", sound_path)
        return
    log.info("Playing %s on %s", sound_path, device_arg)
    subprocess.Popen(["aplay", "-D", device_arg, sound_path])


def _matches_now(alarm: Alarm, now: datetime) -> bool:
    if alarm.state != AlarmState.SCHEDULED.value:
        return False
    if now.strftime("%H:%M") != alarm.time:
        return False
    if alarm.days == "once":
        return True
    today = now.strftime("%a").lower()[:3]
    return today in alarm.days.split(",")


def _maybe_roll_over(alarm: Alarm, now: datetime):
    """Repeating alarms go back to `scheduled` once the trigger minute has passed."""
    if alarm.days == "once":
        return
    if alarm.state in (AlarmState.PLAYING.value, AlarmState.DISMISSED.value):
        if now.strftime("%H:%M") != alarm.time:
            alarm.state = AlarmState.SCHEDULED.value


def _handle_trigger(alarm_id: int):
    session = SessionLocal()
    try:
        alarm = session.get(Alarm, alarm_id)
        if alarm is None:
            return
        status = _bt_status()
        if status.get("connected"):
            alarm.state = AlarmState.PLAYING.value
            session.commit()
            _play_sound(alarm.sound_file, status["device_mac"], alarm.volume)
        else:
            alarm.state = AlarmState.WAITING_FOR_SPEAKER.value
            session.commit()
            log.info("Alarm %s waiting for speaker", alarm_id)
    finally:
        session.close()


def on_bt_connected():
    """Called from the /events/bt-connected webhook - plays anything left waiting."""
    session = SessionLocal()
    try:
        waiting = (
            session.query(Alarm)
            .filter(Alarm.state == AlarmState.WAITING_FOR_SPEAKER.value)
            .all()
        )
        if not waiting:
            return
        status = _bt_status()
        device_mac = status.get("device_mac")
        for alarm in waiting:
            alarm.state = AlarmState.PLAYING.value
            _play_sound(alarm.sound_file, device_mac, alarm.volume)
        session.commit()
    finally:
        session.close()


def tick():
    now = datetime.now()
    session = SessionLocal()
    try:
        alarms = session.query(Alarm).filter(Alarm.enabled.is_(True)).all()
        triggered_ids = []
        for alarm in alarms:
            _maybe_roll_over(alarm, now)
            if _matches_now(alarm, now):
                alarm.state = AlarmState.TRIGGERED.value
                alarm.last_fired_at = now
                triggered_ids.append(alarm.id)
        session.commit()
    finally:
        session.close()

    for alarm_id in triggered_ids:
        _handle_trigger(alarm_id)


def loop_forever():
    while True:
        try:
            tick()
        except Exception:
            log.exception("Scheduler tick failed")
        time.sleep(CHECK_INTERVAL)


def start_background():
    threading.Thread(target=loop_forever, daemon=True).start()
