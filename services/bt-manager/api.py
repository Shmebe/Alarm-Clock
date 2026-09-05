from fastapi import FastAPI

from manager import state, state_lock, start_background

app = FastAPI(title="bt-manager")


@app.on_event("startup")
def startup():
    start_background()


@app.get("/status")
def status():
    with state_lock:
        return dict(state)
