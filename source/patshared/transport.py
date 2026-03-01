from dataclasses import dataclass
from enum import IntEnum

@dataclass
class TransportPosition:
    """Transport position (BBT/frame) data."""
    frame: int
    rolling: bool
    valid_bbt: bool
    bar: int
    beat: int
    tick: int
    beats_per_minutes: float


class TransportWanted(IntEnum):
    """How much transport information should be sent to external
    subscribers.

    - NO: send nothing
    - STATE_ONLY: send only play/pause state changes
    - FULL: send complete transport updates
    """
    NO = 0
    'do not send any transport info'

    STATE_ONLY = 1
    'send transport info only when play/pause changed'

    FULL = 2
    'send all transport infos'