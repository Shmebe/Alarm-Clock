FROM python:3.11-slim

# alsa-utils for `aplay`; libasound2-plugin-bluez ships the actual plugin
# (.so) that implements `type bluealsa`. The package is also *supposed* to
# register the convenience named PCM (`pcm.bluealsa { ... }`, which is what
# lets you write `aplay -D bluealsa:DEV=...,PROFILE=...`) via a conf.d snippet,
# but that registration relies on dpkg triggers that don't reliably fire in a
# minimal --no-install-recommends container with no udev/systemd. So we
# define pcm.bluealsa/ctl.bluealsa explicitly in /etc/asound.conf instead of
# depending on the package to wire it up.
RUN apt-get update && apt-get install -y --no-install-recommends \
        alsa-utils \
        libasound2-plugin-bluez \
    && rm -rf /var/lib/apt/lists/*

RUN cat > /etc/asound.conf << 'EOF'
pcm.bluealsa {
    @args [ DEV PROFILE VOL SRV ]
    @args.DEV {
        type string
        default "00:00:00:00:00:00"
    }
    @args.PROFILE {
        type string
        default "a2dp"
    }
    @args.VOL {
        type string
        default "unchanged"
    }
    @args.SRV {
        type string
        default "org.bluealsa"
    }
    type plug
    slave.pcm {
        type bluealsa
        device $DEV
        profile $PROFILE
        volume $VOL
        service $SRV
    }
}

ctl.bluealsa {
    @args [ SRV ]
    @args.SRV {
        type string
        default "org.bluealsa"
    }
    type bluealsa
    service $SRV
}
EOF

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8082
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8082"]
