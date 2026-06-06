"""
WebSocket connection manager for real-time delivery tracking.

Architecture:
  - One delivery session (assignment) has exactly ONE driver WebSocket sender.
  - Multiple customers (and admin monitors) can listen to the same assignment.
  - The manager holds all connections in-process — no Redis needed for a
    single-server deployment. If you later scale to multiple workers, swap
    the internal dict for a Redis pub/sub channel with the same interface.

Connection types:
  "driver"   — the delivery partner sending GPS updates
  "customer" — the customer whose meal is being delivered
  "admin"    — admin monitoring view (receives all active assignments)
"""
import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Dict, List
from fastapi import WebSocket

logger = logging.getLogger(__name__)


class ConnectionManager:
    def __init__(self):
        # assignment_id → driver WebSocket (only one per assignment)
        self._drivers: Dict[int, WebSocket] = {}
        # assignment_id → list of listener WebSockets (customers + admins)
        self._listeners: Dict[int, List[WebSocket]] = {}
        # admin monitor sockets that receive ALL assignment updates
        self._admin_monitors: List[WebSocket] = []
        self._lock = asyncio.Lock()

    # ── Connection lifecycle ──────────────────────────────────────────────────

    async def connect_driver(self, assignment_id: int, ws: WebSocket):
        await ws.accept()
        async with self._lock:
            self._drivers[assignment_id] = ws
        logger.info("Driver WebSocket connected for assignment %s", assignment_id)

    async def connect_listener(self, assignment_id: int, ws: WebSocket):
        await ws.accept()
        async with self._lock:
            self._listeners.setdefault(assignment_id, []).append(ws)
        logger.info("Customer listener connected for assignment %s", assignment_id)

    async def connect_admin_monitor(self, ws: WebSocket):
        await ws.accept()
        async with self._lock:
            self._admin_monitors.append(ws)
        logger.info("Admin monitor WebSocket connected")

    async def disconnect_driver(self, assignment_id: int):
        async with self._lock:
            self._drivers.pop(assignment_id, None)
        logger.info("Driver WebSocket disconnected for assignment %s", assignment_id)

    async def disconnect_listener(self, assignment_id: int, ws: WebSocket):
        async with self._lock:
            listeners = self._listeners.get(assignment_id, [])
            if ws in listeners:
                listeners.remove(ws)
        logger.info("Customer listener disconnected for assignment %s", assignment_id)

    async def disconnect_admin_monitor(self, ws: WebSocket):
        async with self._lock:
            if ws in self._admin_monitors:
                self._admin_monitors.remove(ws)

    # ── Broadcasting ──────────────────────────────────────────────────────────

    async def broadcast_location(
        self,
        assignment_id: int,
        driver_id: int,
        latitude: float,
        longitude: float,
        recorded_at: datetime,
        status: str = "on_the_way",
    ):
        """Broadcast a GPS update to all listeners of an assignment.
        Also notifies admin monitor connections.
        Dead sockets are pruned automatically.
        """
        payload = json.dumps({
            "type": "location_update",
            "assignment_id": assignment_id,
            "driver_id": driver_id,
            "latitude": latitude,
            "longitude": longitude,
            "recorded_at": recorded_at.isoformat(),
            "status": status,
            "server_time": datetime.now(timezone.utc).isoformat(),
        })

        dead_listeners: List[WebSocket] = []

        async with self._lock:
            listeners = list(self._listeners.get(assignment_id, []))
            admins = list(self._admin_monitors)

        for ws in listeners:
            try:
                await ws.send_text(payload)
            except Exception:
                dead_listeners.append(ws)

        for ws in admins:
            try:
                await ws.send_text(payload)
            except Exception:
                # Don't remove admin sockets here — handled in their own disconnect
                pass

        # Prune dead sockets
        if dead_listeners:
            async with self._lock:
                for ws in dead_listeners:
                    lst = self._listeners.get(assignment_id, [])
                    if ws in lst:
                        lst.remove(ws)

    async def broadcast_status_change(self, assignment_id: int, status: str):
        """Notify all listeners that a delivery status changed (e.g. delivered)."""
        payload = json.dumps({
            "type": "status_change",
            "assignment_id": assignment_id,
            "status": status,
            "server_time": datetime.now(timezone.utc).isoformat(),
        })

        async with self._lock:
            listeners = list(self._listeners.get(assignment_id, []))
            admins = list(self._admin_monitors)

        dead: List[WebSocket] = []
        for ws in listeners + admins:
            try:
                await ws.send_text(payload)
            except Exception:
                dead.append(ws)

        if dead:
            async with self._lock:
                for ws in dead:
                    lst = self._listeners.get(assignment_id, [])
                    if ws in lst:
                        lst.remove(ws)
                    if ws in self._admin_monitors:
                        self._admin_monitors.remove(ws)

    def active_assignment_count(self) -> int:
        return len(self._drivers)

    def has_driver(self, assignment_id: int) -> bool:
        return assignment_id in self._drivers

    def listener_count(self, assignment_id: int) -> int:
        return len(self._listeners.get(assignment_id, []))


# Module-level singleton — imported by the tracking router
ws_manager = ConnectionManager()
