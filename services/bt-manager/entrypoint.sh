#!/bin/sh
set -e

# bluealsa was only *installed* before, never *run*. Without this the D-Bus
# service org.bluealsa never appears, so bluealsa-aplay/aplay have nothing
# to talk to. -p a2dp-source: we only need the Pi to act as a source pushing
# audio out to the speaker (a sink) - no hfp-ag/hsp-ag, which would expect
# real telephony audio hardware we don't have here.
bluealsa -p a2dp-source &

exec python3 -m uvicorn api:app --host 0.0.0.0 --port 8081
