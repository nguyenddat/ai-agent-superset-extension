import os
import threading
import time
from uuid import UUID

_TIMESTAMP_MASK = (1 << 48) - 1
_COUNTER_MASK = (1 << 12) - 1
_RANDOM_MASK = (1 << 62) - 1

_last_timestamp = 0
_counter = 0
_state_lock = threading.Lock()


# RFC 9562 UUID version 7, because Python 3.10 has no uuid.uuid7. Within one millisecond the 12-bit rand_a field
# counts up from a random start, so ids made in one process sort in creation order like Python 3.14's uuid7.
def uuid7() -> UUID:
    global _last_timestamp, _counter
    random_bits = int.from_bytes(os.urandom(10), "big")
    with _state_lock:
        timestamp = time.time_ns() // 1_000_000
        if timestamp > _last_timestamp:
            _last_timestamp, _counter = timestamp, (random_bits >> 64) & (_COUNTER_MASK >> 1)
        else:
            _counter += 1
            if _counter > _COUNTER_MASK:
                _last_timestamp, _counter = _last_timestamp + 1, 0
        timestamp, counter = _last_timestamp, _counter
    value = (
        (timestamp & _TIMESTAMP_MASK) << 80 | 0x7 << 76 | counter << 64 | 0b10 << 62 | random_bits & _RANDOM_MASK
    )
    return UUID(int=value)
