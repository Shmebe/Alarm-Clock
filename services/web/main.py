import os

import requests
from fastapi import FastAPI, Form, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates

ALARM_CORE_URL = os.environ.get("ALARM_CORE_URL", "http://alarm-core:8082")

app = FastAPI(title="web")
templates = Jinja2Templates(directory="templates")


@app.get("/")
def index(request: Request):
    try:
        alarms = requests.get(f"{ALARM_CORE_URL}/alarms", timeout=5).json()
    except requests.RequestException:
        alarms = []
    try:
        bt_status = requests.get(f"{ALARM_CORE_URL}/bt-status", timeout=5).json()
    except requests.RequestException:
        bt_status = {"connected": False, "device_mac": None}

    return templates.TemplateResponse(
        "index.html", {"request": request, "alarms": alarms, "bt_status": bt_status}
    )


@app.post("/alarms")
def create_alarm(
    time: str = Form(...),
    days: str = Form("once"),
    label: str = Form(""),
    sound_file: str = Form(...),
):
    requests.post(
        f"{ALARM_CORE_URL}/alarms",
        json={
            "time": time,
            "days": days,
            "label": label,
            "sound_file": sound_file,
            "enabled": True,
        },
        timeout=5,
    )
    return RedirectResponse("/", status_code=303)


@app.post("/alarms/{alarm_id}/delete")
def delete_alarm(alarm_id: int):
    requests.delete(f"{ALARM_CORE_URL}/alarms/{alarm_id}", timeout=5)
    return RedirectResponse("/", status_code=303)


@app.post("/alarms/{alarm_id}/dismiss")
def dismiss_alarm(alarm_id: int):
    requests.post(f"{ALARM_CORE_URL}/alarms/{alarm_id}/dismiss", timeout=5)
    return RedirectResponse("/", status_code=303)
