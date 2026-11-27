"""An asyncio.Lock that is safe to keep in a module global: one lock per running event loop."""
import asyncio
import weakref


class LoopLock:
    def __init__(self) -> None:
        self._locks: "weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, asyncio.Lock]" = weakref.WeakKeyDictionary()

    def get(self) -> asyncio.Lock:
        loop = asyncio.get_running_loop()
        lock = self._locks.get(loop)
        if lock is None:
            lock = self._locks[loop] = asyncio.Lock()
        return lock
