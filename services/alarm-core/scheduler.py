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

# A2DP over Bluetooth has higher and jitterier latency than local audio.
# aplay's default buffer/period is tuned for local hardware and underruns
# constantly on this link, which ALSA "fixes" by silently restarting the
# stream on every xrun - audible as stutter/stammer throughout playback.
# Latency doesn't matter at all for an alarm clock, so trade it generously
# for stability: 1s buffer, 200ms period.
AUDIO_BUFFER_ARGS = ["--buffer-time=1000000", "--period-time=200000"]

# --- Looping ringer management -------------------------------------------
# One alarm can be "ringing" at a time per alarm_id: a background thread
# that keeps restarting `aplay` until told to stop. Tracked in-memory only -
# on container restart any alarm stuck mid-ring is recovered back to
# `scheduled` (see _recover_stuck_states), since the ringer itself is gone.

_ringers = {}
_ringers_lock = threading.Lock()


def _bt_status():
    try:
        r = requests.get(f"{BT_MANAGER_URL}/status", timeout=3)
        r.raise_for_status()
        return r.json()
    except requests.RequestException:
        return {"connected": False, "device_mac": None}


def _play_sound(sound_file, device_mac, volume=50):
    """One-shot playback, used by the debug player only."""
    volume = max(0, min(100, volume))
    device_arg = f"bluealsa:DEV={device_mac},PROFILE=a2dp,VOL={volume}"
    sound_path = os.path.join(SOUNDS_DIR, sound_file)
    if not os.path.isfile(sound_path):
        log.error("Sound file missing, cannot play: %s", sound_path)
        return
    log.info("Playing %s on %s", sound_path, device_arg)
    subprocess.Popen(["aplay", "-D", device_arg, *AUDIO_BUFFER_ARGS, sound_path])


def _ring_loop(alarm_id, sound_path, device_arg, stop_event):
    log.info("Alarm %s: starting ring loop on %s", alarm_id, device_arg)
    while not stop_event.is_set():
        proc = subprocess.Popen(["aplay", "-D", device_arg, *AUDIO_BUFFER_ARGS, sound_path])
        while proc.poll() is None:
            if stop_event.wait(timeout=0.2):
                proc.terminate()
                try:
                    proc.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    proc.kill()
                log.info("Alarm %s: ring loop stopped", alarm_id)
                return
        # aplay exited on its own (track ended) - loop again unless stopped.
    log.info("Alarm %s: ring loop stopped", alarm_id)


def start_ringing(alarm_id, sound_file, device_mac, volume=50):
    volume = max(0, min(100, volume))
    device_arg = f"bluealsa:DEV={device_mac},PROFILE=a2dp,VOL={volume}"
    sound_path = os.path.join(SOUNDS_DIR, sound_file)
    if not os.path.isfile(sound_path):
        log.error("Alarm %s: sound file missing, cannot ring: %s", alarm_id, sound_path)
        return
    with _ringers_lock:
        _stop_ringing_locked(alarm_id)
        stop_event = threading.Event()
        thread = threading.Thread(
            target=_ring_loop, args=(alarm_id, sound_path, device_arg, stop_event), daemon=True
        )
        _ringers[alarm_id] = {"stop_event": stop_event, "thread": thread}
        thread.start()


def _stop_ringing_locked(alarm_id):
    entry = _ringers.pop(alarm_id, None)
    if entry:
        entry["stop_event"].set()


def stop_ringing(alarm_id):
    with _ringers_lock:
        _stop_ringing_locked(alarm_id)


# --- Trigger matching -------------------------------------------------

def _matches_now(alarm: Alarm, now: datetime) -> bool:
    if alarm.state != AlarmState.SCHEDULED.value:
        return False
    if alarm.snooze_until:
        return now >= alarm.snooze_until
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
            start_ringing(alarm.id, alarm.sound_file, status["device_mac"], alarm.volume)
        else:
            alarm.state = AlarmState.WAITING_FOR_SPEAKER.value
            session.commit()
            log.info("Alarm %s waiting for speaker", alarm_id)
    finally:
        session.close()


def on_bt_connected():
    """Called from the /events/bt-connected webhook - rings anything left waiting."""
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
            start_ringing(alarm.id, alarm.sound_file, device_mac, alarm.volume)
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
                alarm.snooze_until = None
                triggered_ids.append(alarm.id)
        session.commit()
    finally:
        session.close()

    for alarm_id in triggered_ids:
        _handle_trigger(alarm_id)


def _recover_stuck_states():
    """On startup, any alarm left mid-ring belongs to a ringer thread that no
    longer exists (the process just restarted) - put it back to schedulable
    instead of showing a phantom 'playing' state forever."""
    session = SessionLocal()
    try:
        stuck = (
            session.query(Alarm)
            .filter(Alarm.state.in_([
                AlarmState.TRIGGERED.value,
                AlarmState.WAITING_FOR_SPEAKER.value,
                AlarmState.PLAYING.value,
            ]))
            .all()
        )
        for alarm in stuck:
            log.warning("Recovering alarm %s from stuck state '%s' after restart", alarm.id, alarm.state)
            alarm.state = AlarmState.SCHEDULED.value
        if stuck:
            session.commit()
    finally:
        session.close()


def loop_forever():
    while True:
        try:
            tick()
        except Exception:
            log.exception("Scheduler tick failed")
        time.sleep(CHECK_INTERVAL)


def start_background():
    _recover_stuck_states()
    threading.Thread(target=loop_forever, daemon=True).start()
