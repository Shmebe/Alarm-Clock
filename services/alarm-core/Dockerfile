FROM python:3.11-slim

# alsa-utils for `aplay`; libasound2-plugin-bluez for the ALSA plugin config
# that resolves the `bluealsa:...` PCM name (the bluealsa *daemon* itself
# runs in bt-manager) - this is what lets `aplay -D bluealsa:...` reach the
# shared socket in /var/run/bluealsa.
RUN apt-get update && apt-get install -y --no-install-recommends \
        alsa-utils \
        libasound2-plugin-bluez \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8082
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8082"]
