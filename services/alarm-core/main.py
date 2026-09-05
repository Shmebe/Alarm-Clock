import os
from typing import List

import requests
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from models import Alarm, SessionLocal, init_db
from scheduler import on_bt_connected, start_background
from state_machine import AlarmState

BT_MANAGER_URL = os.environ.get("BT_MANAGER_URL", "http://localhost:8081")

app = FastAPI(title="alarm-core")


class AlarmIn(BaseModel):
    time: str
    days: str = "once"
    label: str = ""
    sound_file: str
    enabled: bool = True


class AlarmOut(AlarmIn):
    id: int
    state: str

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
    finally:
        session.close()


@app.post("/alarms", response_model=AlarmOut)
def create_alarm(alarm: AlarmIn):
    session = SessionLocal()
    try:
        db_alarm = Alarm(**alarm.model_dump(), state=AlarmState.SCHEDULED.value)
        session.add(db_alarm)
        session.commit()
        session.refresh(db_alarm)
        return db_alarm
    finally:
        session.close()


@app.put("/alarms/{alarm_id}", response_model=AlarmOut)
def update_alarm(alarm_id: int, alarm: AlarmIn):
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
    finally:
        session.close()


@app.delete("/alarms/{alarm_id}")
def delete_alarm(alarm_id: int):
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
    session = SessionLocal()
    try:
        db_alarm = session.get(Alarm, alarm_id)
        if not db_alarm:
            raise HTTPException(404, "Alarm not found")
        db_alarm.state = AlarmState.DISMISSED.value
        session.commit()
        return {"ok": True}
    finally:
        session.close()


@app.post("/events/bt-connected")
def bt_connected_event():
    on_bt_connected()
    return {"ok": True}


@app.get("/bt-status")
def bt_status():
    try:
        r = requests.get(f"{BT_MANAGER_URL}/status", timeout=3)
        return r.json()
    except requests.RequestException:
        return {"connected": False, "device_mac": None}
