"""
bt-manager core logic.

Watches a known Bluetooth speaker via BlueZ's D-Bus API. Reconnects
automatically on disconnect (no retry limit — the speaker may be off for
hours), and notifies alarm-core over HTTP whenever the connection comes
back up so any alarm stuck in `waiting_for_speaker` can play.
"""

import logging
import os
import threading
import time

import dbus
import dbus.mainloop.glib
import requests
import yaml
from gi.repository import GLib

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("bt-manager")

CONFIG_PATH = os.environ.get("KNOWN_DEVICES_PATH", "/config/known_devices.yml")
ALARM_CORE_URL = os.environ.get("ALARM_CORE_URL", "http://localhost:8082")
ADAPTER = os.environ.get("BT_ADAPTER", "hci0")

# Backoff steps in seconds; the last value repeats indefinitely.
BACKOFF_STEPS = [1, 2, 5, 10]

state = {
    "connected": False,
    "device_mac": None,
    "device_name": None,
    "last_change_ts": None,
}
state_lock = threading.Lock()


def load_known_device():
    with open(CONFIG_PATH) as f:
        cfg = yaml.safe_load(f)
    return cfg["speaker"]


def mac_to_device_path(adapter, mac):
    return f"/org/bluez/{adapter}/dev_{mac.replace(':', '_')}"


class BTManager:
    def __init__(self, adapter=ADAPTER):
        self.adapter = adapter
        self.bus = dbus.SystemBus()
        self.mac = None
        self.name = None
        self.device_path = None

    def setup(self):
        speaker = load_known_device()
        self.mac = speaker["mac"]
        self.name = speaker.get("name", self.mac)
        self.device_path = mac_to_device_path(self.adapter, self.mac)

        self.bus.add_signal_receiver(
            self._on_properties_changed,
            dbus_interface="org.freedesktop.DBus.Properties",
            signal_name="PropertiesChanged",
            path=self.device_path,
        )
        log.info("Watching %s (%s) at %s", self.name, self.mac, self.device_path)

    def _device_proxy(self):
        obj = self.bus.get_object("org.bluez", self.device_path)
        return dbus.Interface(obj, "org.bluez.Device1")

    def is_connected(self):
        try:
            obj = self.bus.get_object("org.bluez", self.device_path)
            props = dbus.Interface(obj, "org.freedesktop.DBus.Properties")
            return bool(props.Get("org.bluez.Device1", "Connected"))
        except dbus.exceptions.DBusException:
            return False

    def _on_properties_changed(self, interface, changed, invalidated, path=None):
        if "Connected" not in changed:
            return
        connected = bool(changed["Connected"])
        self._update_state(connected)
        if not connected:
            log.warning("%s disconnected — starting reconnect loop", self.name)
            threading.Thread(target=self._reconnect_loop, daemon=True).start()

    def _update_state(self, connected):
        with state_lock:
            state["connected"] = connected
            state["device_mac"] = self.mac
            state["device_name"] = self.name
            state["last_change_ts"] = time.time()
        if connected:
            self._notify_alarm_core()

    def _notify_alarm_core(self):
        try:
            requests.post(f"{ALARM_CORE_URL}/events/bt-connected", timeout=3)
        except requests.RequestException as e:
            log.error("Failed to notify alarm-core: %s", e)

    def connect_once(self):
        try:
            self._device_proxy().Connect()
            return True
        except dbus.exceptions.DBusException as e:
            log.debug("Connect attempt failed: %s", e)
            return False

    def _reconnect_loop(self):
        step = 0
        while not self.is_connected():
            delay = BACKOFF_STEPS[min(step, len(BACKOFF_STEPS) - 1)]
            log.info("Reconnect attempt in %ss", delay)
            time.sleep(delay)
            if self.connect_once():
                log.info("Reconnected to %s", self.name)
                self._update_state(True)
                return
            step += 1

    def initial_connect(self):
        if self.is_connected():
            self._update_state(True)
        else:
            threading.Thread(target=self._reconnect_loop, daemon=True).start()


def run_dbus_loop():
    dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
    manager = BTManager()
    manager.setup()
    manager.initial_connect()
    GLib.MainLoop().run()


def start_background():
    threading.Thread(target=run_dbus_loop, daemon=True).start()
