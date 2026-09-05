from enum import Enum


class AlarmState(str, Enum):
    SCHEDULED = "scheduled"
    TRIGGERED = "triggered"
    WAITING_FOR_SPEAKER = "waiting_for_speaker"
    PLAYING = "playing"
    DISMISSED = "dismissed"


VALID_TRANSITIONS = {
    AlarmState.SCHEDULED: {AlarmState.TRIGGERED},
    AlarmState.TRIGGERED: {AlarmState.WAITING_FOR_SPEAKER, AlarmState.PLAYING},
    AlarmState.WAITING_FOR_SPEAKER: {AlarmState.PLAYING},
    AlarmState.PLAYING: {AlarmState.DISMISSED},
    AlarmState.DISMISSED: {AlarmState.SCHEDULED},  # rolls over for repeating alarms
}


def can_transition(current: str, target: AlarmState) -> bool:
    return target in VALID_TRANSITIONS.get(AlarmState(current), set())
