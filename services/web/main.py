import os
import urllib.parse

import requests
from fastapi import FastAPI, Form, Request
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

ALARM_CORE_URL = os.environ.get("ALARM_CORE_URL", "http://alarm-core:8082")

app = FastAPI(title="web")
templates = Jinja2Templates(directory="templates")

DAY_LABELS = {
    "mon": "Пн", "tue": "Вт", "wed": "Ср", "thu": "Чт",
    "fri": "Пт", "sat": "Сб", "sun": "Нд",
}
WEEKDAYS = ["mon", "tue", "wed", "thu", "fri"]
WEEKEND = ["sat", "sun"]
ALL_DAYS = WEEKDAYS + WEEKEND


def _format_days(days: str) -> str:
    if days == "once":
        return "Одноразово"
    parts = [d.strip() for d in days.split(",") if d.strip()]
    if sorted(parts) == sorted(ALL_DAYS):
        return "Щодня"
    if sorted(parts) == sorted(WEEKDAYS):
        return "Будні"
    if sorted(parts) == sorted(WEEKEND):
        return "Вихідні"
    return ", ".join(DAY_LABELS.get(d, d) for d in parts) or days


def _error_redirect(message: str) -> RedirectResponse:
    return RedirectResponse(f"/?error={urllib.parse.quote(message)}", status_code=303)


@app.get("/")
def index(request: Request):
    error = request.query_params.get("error")

    try:
        alarms_resp = requests.get(f"{ALARM_CORE_URL}/alarms", timeout=5)
        alarms = alarms_resp.json() if alarms_resp.ok else []
        if not alarms_resp.ok and not error:
            error = f"alarm-core: {alarms_resp.status_code} {alarms_resp.text}"
    except requests.RequestException as e:
        alarms = []
        if not error:
            error = f"alarm-core unreachable: {e}"

    try:
        bt_status = requests.get(f"{ALARM_CORE_URL}/bt-status", timeout=5).json()
    except requests.RequestException:
        bt_status = {"connected": False, "device_mac": None}
    try:
        sounds = requests.get(f"{ALARM_CORE_URL}/sounds", timeout=5).json().get("sounds", [])
    except requests.RequestException:
        sounds = []

    alarms = sorted(alarms, key=lambda a: a.get("time", ""))
    for a in alarms:
        a["days_display"] = _format_days(a.get("days", "once"))

    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "alarms": alarms,
            "bt_status": bt_status,
            "sounds": sounds,
            "error": error,
        },
    )


@app.post("/alarms")
def create_alarm(
    time: str = Form(...),
    days: str = Form("once"),
    label: str = Form(""),
    sound_file: str = Form(...),
    volume: int = Form(50),
):
    try:
        resp = requests.post(
            f"{ALARM_CORE_URL}/alarms",
            json={
                "time": time,
                "days": days,
                "label": label,
                "sound_file": sound_file,
                "volume": volume,
                "enabled": True,
            },
            timeout=5,
        )
    except requests.RequestException as e:
        return _error_redirect(f"alarm-core unreachable: {e}")

    if not resp.ok:
        detail = resp.json().get("detail", resp.text) if resp.headers.get("content-type", "").startswith("application/json") else resp.text
        return _error_redirect(f"Не вдалось зберегти алярм: {detail}")

    return RedirectResponse("/", status_code=303)


@app.post("/alarms/{alarm_id}/delete")
def delete_alarm(alarm_id: int):
    requests.delete(f"{ALARM_CORE_URL}/alarms/{alarm_id}", timeout=5)
    return RedirectResponse("/", status_code=303)


@app.post("/alarms/{alarm_id}/dismiss")
def dismiss_alarm(alarm_id: int):
    requests.post(f"{ALARM_CORE_URL}/alarms/{alarm_id}/dismiss", timeout=5)
    return RedirectResponse("/", status_code=303)


@app.post("/alarms/{alarm_id}/toggle")
def toggle_alarm(alarm_id: int):
    requests.post(f"{ALARM_CORE_URL}/alarms/{alarm_id}/toggle", timeout=5)
    return RedirectResponse("/", status_code=303)


# --- Debug player proxy: instant playback, independent of any alarm ---

@app.post("/debug/play")
async def debug_play(request: Request):
    data = await request.json()
    try:
        r = requests.post(f"{ALARM_CORE_URL}/debug/play", json=data, timeout=5)
        return JSONResponse(content=r.json(), status_code=r.status_code)
    except requests.RequestException as e:
        return JSONResponse(content={"ok": False, "detail": str(e)}, status_code=502)


@app.post("/debug/pause")
def debug_pause():
    r = requests.post(f"{ALARM_CORE_URL}/debug/pause", timeout=5)
    return JSONResponse(content=r.json(), status_code=r.status_code)


@app.post("/debug/resume")
def debug_resume():
    r = requests.post(f"{ALARM_CORE_URL}/debug/resume", timeout=5)
    return JSONResponse(content=r.json(), status_code=r.status_code)


@app.post("/debug/stop")
def debug_stop():
    r = requests.post(f"{ALARM_CORE_URL}/debug/stop", timeout=5)
    return JSONResponse(content=r.json(), status_code=r.status_code)
