import queue
from datetime import datetime, timezone, timedelta

# India Standard Time (IST = UTC + 5:30)
IST_TZ = timezone(timedelta(hours=5, minutes=30))

class LLMClientLogQueue:
    _queue = queue.Queue()
    
    @classmethod
    def put(cls, msg: str):
        ist_now = datetime.now(IST_TZ).strftime("%H:%M:%S IST")
        formatted_msg = f"[{ist_now}] {msg}"
        cls._queue.put(formatted_msg)

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
