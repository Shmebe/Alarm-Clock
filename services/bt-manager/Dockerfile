FROM debian:trixie-slim

# Single interpreter for everything in this image: python3-dbus/python3-gi
# (compiled C extensions, only importable under the exact interpreter they
# were built against) and pip packages both go through the same apt-provided
# python3. Using python:3.11-slim here was the original approach, but its
# python3.11 is a separate build from the one apt's python3-dbus targets -
# `import dbus` fails with ModuleNotFoundError even though the package is
# "installed", because it's installed for a different python3.
RUN apt-get update && apt-get install -y --no-install-recommends \
        python3 \
        python3-pip \
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
CMD ["python3", "-m", "uvicorn", "api:app", "--host", "0.0.0.0", "--port", "8081"]
