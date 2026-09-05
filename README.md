# BT Alarm Clock

Будильник на ARM mini-сервері, що грає звук на Bluetooth-колонку з авто-конектом.
Три сервіси: `bt-manager` (BlueZ/D-Bus, host network), `alarm-core` (шедулер +
sqlite), `web` (CRUD + дашборд). Деталі архітектури — у супровідному design-документі.

## Передумова: колонку треба спарувати вручну один раз

Docker/bt-manager займається лише **реконектом**, не первинним пейрінгом
(BlueZ вимагає взаємодії при першому спарюванні — PIN/confirm). На хості:

```bash
bluetoothctl
power on
agent on
scan on
# знайти MAC колонки, потім:
pair AA:BB:CC:DD:EE:FF
trust AA:BB:CC:DD:EE:FF
connect AA:BB:CC:DD:EE:FF
```

Після цього впиши той самий MAC у `config/known_devices.yml`.

## Запуск

```bash
mkdir -p data
docker compose build
docker compose up -d
```

- Веб-дашборд: `http://<server-ip>:8080`
- `alarm-core` API напряму: `http://<server-ip>:8082/alarms`
- `bt-manager` статус (тільки локально, host network): `http://localhost:8081/status`

## Відомі місця, які варто перевірити на реальному залізі

1. **Версія Python у apt vs pip.** `bt-manager` ставить `python3-dbus` і
   `python3-gi` через apt (system dist-packages), а решту пакетів — pip.
   Це працює, якщо системний `python3` образу збігається з тим, під яким
   запускається uvicorn (на `python:3.11-slim`/Debian bookworm — збігається).
   Якщо колись зміниш базовий образ — перевір це першим.

2. **Сокет bluealsa.** `aplay -D bluealsa:...` в `alarm-core` працює тільки
   якщо `/var/run/bluealsa` реально розділений між `bt-manager` (де крутиться
   демон) і `alarm-core` (звідки йде виклик aplay). У compose це прокинуто як
   bind-mount з хоста — тека має існувати на хості (Docker створить сама, але
   права можуть знадобитись підправити).

3. **Adapter name.** Захардкоджено `hci0` (`BT_ADAPTER` env якщо треба інший).

4. **Формат звукового файлу.** `sound_file` — шлях усередині контейнера
   `alarm-core`; якщо звуки лежать на хості, треба домонтувати том з ними.

## Структура

```
bt-alarm-clock/
├── docker-compose.yml
├── config/known_devices.yml
├── data/                      # sqlite volume
└── services/
    ├── bt-manager/            # D-Bus listener, reconnect loop, /status API
    ├── alarm-core/            # scheduler, state machine, alarms CRUD API
    └── web/                   # dashboard + forms
```
