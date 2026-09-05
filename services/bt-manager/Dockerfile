FROM python:3.11-slim

# python3-dbus / python3-gi are pulled from apt (system dist-packages) rather
# than pip — building them from source needs a pile of C build deps for no
# benefit here. This assumes the base image's default python3 is 3.11
# (true for python:3.11-slim on Debian bookworm); if that ever drifts,
# these imports will need PYTHONPATH pointed at dist-packages explicitly.
RUN apt-get update && apt-get install -y --no-install-recommends \
        python3-dbus \
        python3-gi \
        bluez \
        bluez-tools \
        bluez-alsa-utils \
        dbus \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir --break-system-packages -r requirements.txt

COPY manager.py api.py ./

EXPOSE 8081
CMD ["uvicorn", "api:app", "--host", "0.0.0.0", "--port", "8081"]
