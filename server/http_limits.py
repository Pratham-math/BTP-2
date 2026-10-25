"""Bounded request bodies and simple per-user admission at a single API host."""
import time
from collections import defaultdict, deque
from threading import Lock

from fastapi import HTTPException


class UserLimiter:
    def __init__(self):
        self.events, self.lock = defaultdict(deque), Lock()

    def check(self, user_id, mutation):
        now = time.monotonic()
        with self.lock:
            key = (user_id, mutation)
            events = self.events[key]
            while events and events[0] < now - 60:
                events.popleft()
            if len(events) >= (40 if mutation else 240):
                raise HTTPException(429, "Too many requests. Wait a moment and try again.", headers={"Retry-After": "60"})
            events.append(now)
            if len(self.events) > 10000:
                self.events = defaultdict(deque, {key: values for key, values in self.events.items() if values and values[-1] >= now - 60})


class BodyLimit:
    def __init__(self, app, max_upload):
        self.app, self.max_upload = app, max_upload

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        limit = self.max_upload + 1024 * 1024 if scope.get("path") == "/api/sources/upload" else 2 * 1024 * 1024
        received = 0
        async def bounded_receive():
            nonlocal received
            message = await receive()
            received += len(message.get("body", b""))
            if received > limit:
                raise HTTPException(413, "The request exceeds the configured processing batch size.")
            return message
        await self.app(scope, bounded_receive, send)
