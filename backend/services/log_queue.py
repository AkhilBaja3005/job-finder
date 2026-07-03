import queue

class LLMClientLogQueue:
    _queue = queue.Queue()
    
    @classmethod
    def put(cls, msg: str):
        cls._queue.put(msg)

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
