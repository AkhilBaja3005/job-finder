import queue
import logging
from datetime import datetime, timezone, timedelta

# India Standard Time (IST = UTC + 5:30)
IST_TZ = timezone(timedelta(hours=5, minutes=30))

def get_ist_time_str() -> str:
    return datetime.now(IST_TZ).strftime("%H:%M:%S IST")

def log_ist(msg: str):
    """Central IST Logger: formats with IST timestamp, prints to console/docker logs, and queues for admin web stream."""
    ist_now = get_ist_time_str()
    formatted = f"[{ist_now}] {msg}"
    print(formatted)
    LLMClientLogQueue._queue.put(formatted)

class LLMClientLogQueue:
    _queue = queue.Queue()
    
    @classmethod
    def put(cls, msg: str):
        log_ist(msg)

    @classmethod
    def get(cls, block: bool = True, timeout: float = None):
        """Fetches a single message, blocking if necessary until one arrives."""
        return cls._queue.get(block=block, timeout=timeout)
        
    @classmethod
    def get_all(cls):
        msgs = []
        while not cls._queue.empty():
            try:
                msgs.append(cls._queue.get_nowait())
            except Exception:
                break
        return msgs
