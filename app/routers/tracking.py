"""
Real-Time Tracking Router
--------------------------
WebSocket endpoints for live GPS delivery tracking:
  /ws/driver/{assignment_id}    — Driver sends GPS updates
  /ws/track/{assignment_id}     — Customer/admin listens to live updates
  /ws/monitor                   — Admin listens to ALL active assignments
  /api/tracking/{id}/location   — REST fallback for offline buffer sync
  /api/tracking/{id}            — Customer polls current status (REST fallback)
"""
import json
import logging
from datetime import datetime, timezone
from typing import List

from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect, Query, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db, SessionLocal
from app.models.user import User
from app.models.delivery import DeliveryAssignment, DeliveryTracking, DriverStatus
from app.routers.auth import get_current_user
from app.utils.ws_manager import ws_manager

logger = logging.getLogger(__name__)
router = APIRouter(tags=["Tracking"])


def _get_db_for_ws() -> Session:
    """Get a fresh DB session for WebSocket handlers (not dependency-injected)."""
    return SessionLocal()


# ── Helper: verify assignment & role ─────────────────────────────────────────

def _get_assignment_or_404(assignment_id: int, db: Session) -> DeliveryAssignment:
    a = db.query(DeliveryAssignment).filter(DeliveryAssignment.id == assignment_id).first()
    if not a:
        raise HTTPException(status_code=404, detail="Assignment not found.")
    return a


# ═══════════════════════════════════════════════════════════════
# DRIVER WEBSOCKET — sends GPS updates
# ═══════════════════════════════════════════════════════════════

@router.websocket("/ws/driver/{assignment_id}")
async def driver_ws(
    websocket: WebSocket,
    assignment_id: int,
    token: str = Query(...),
):
    """WebSocket endpoint for the driver app.
    Driver authenticates via ?token=<jwt> query parameter.
    Expected message format (JSON):
      { "lat": 12.345, "lng": 80.123, "recorded_at": "2026-06-05T10:00:00Z" }

    On receiving a location point:
      1. Save to delivery_tracking table
      2. Update driver_status.last_lat/lng
      3. Broadcast to all customer listeners for this assignment
    """
    db = _get_db_for_ws()
    try:
        # Validate token
        from app.utils.security import SECRET_KEY, ALGORITHM
        from jose import jwt, JWTError

        try:
            payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
            user_id = int(payload.get("sub", 0))
        except (JWTError, ValueError):
            await websocket.close(code=4001)
            return

        driver = db.query(User).filter(User.id == user_id, User.role == "driver").first()
        if not driver or not driver.is_active:
            await websocket.close(code=4003)
            return

        assignment = db.query(DeliveryAssignment).filter(
            DeliveryAssignment.id == assignment_id,
            DeliveryAssignment.driver_id == driver.id,
        ).first()
        if not assignment:
            await websocket.close(code=4004)
            return

        await ws_manager.connect_driver(assignment_id, websocket)
        logger.info("Driver %s connected to WS for assignment %s", driver.id, assignment_id)

        try:
            while True:
                raw = await websocket.receive_text()
                try:
                    data = json.loads(raw)
                    lat = float(data["lat"])
                    lng = float(data["lng"])
                    # Allow driver to send device timestamp; fall back to server time
                    try:
                        recorded_at = datetime.fromisoformat(data.get("recorded_at", ""))
                        if recorded_at.tzinfo is None:
                            recorded_at = recorded_at.replace(tzinfo=timezone.utc)
                    except (ValueError, TypeError):
                        recorded_at = datetime.now(timezone.utc)

                    # Persist tracking point
                    point = DeliveryTracking(
                        assignment_id=assignment_id,
                        driver_id=driver.id,
                        latitude=lat,
                        longitude=lng,
                        recorded_at=recorded_at,
                    )
                    db.add(point)

                    # Update driver last known position
                    ds = db.query(DriverStatus).filter(DriverStatus.driver_id == driver.id).first()
                    if ds:
                        ds.last_latitude = lat
                        ds.last_longitude = lng
                        ds.last_updated = datetime.now(timezone.utc)

                    db.commit()

                    # Broadcast to listeners
                    await ws_manager.broadcast_location(
                        assignment_id, driver.id, lat, lng, recorded_at, assignment.status
                    )

                except (KeyError, ValueError, json.JSONDecodeError) as parse_err:
                    logger.debug("Bad GPS message from driver %s: %s", driver.id, parse_err)
                    # Send error back without closing
                    await websocket.send_text(json.dumps({"error": "Invalid message format"}))

        except WebSocketDisconnect:
            logger.info("Driver %s WebSocket disconnected for assignment %s", driver.id, assignment_id)

    finally:
        await ws_manager.disconnect_driver(assignment_id)
        db.close()


# ═══════════════════════════════════════════════════════════════
# CUSTOMER / ADMIN LISTENER WEBSOCKET
# ═══════════════════════════════════════════════════════════════

@router.websocket("/ws/track/{assignment_id}")
async def track_ws(
    websocket: WebSocket,
    assignment_id: int,
    token: str = Query(...),
):
    """Customer or admin listens to live GPS updates for a specific assignment.
    Sends initial status snapshot on connect, then relays driver broadcasts.
    """
    db = _get_db_for_ws()
    try:
        from app.utils.security import SECRET_KEY, ALGORITHM
        from jose import jwt, JWTError

        try:
            payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
            user_id = int(payload.get("sub", 0))
        except (JWTError, ValueError):
            await websocket.close(code=4001)
            return

        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            await websocket.close(code=4001)
            return

        assignment = db.query(DeliveryAssignment).filter(
            DeliveryAssignment.id == assignment_id
        ).first()
        if not assignment:
            await websocket.close(code=4004)
            return

        # Customers can only track their own deliveries
        if user.role == "customer" and assignment.customer_id != user.id:
            await websocket.close(code=4003)
            return

        await ws_manager.connect_listener(assignment_id, websocket)

        # Send initial status snapshot
        ds = db.query(DriverStatus).filter(DriverStatus.driver_id == assignment.driver_id).first()
        await websocket.send_text(json.dumps({
            "type": "initial_status",
            "assignment_id": assignment_id,
            "status": assignment.status,
            "driver_latitude": ds.last_latitude if ds else None,
            "driver_longitude": ds.last_longitude if ds else None,
            "last_updated": ds.last_updated.isoformat() if ds and ds.last_updated else None,
        }))

        try:
            # Keep connection alive; actual updates are pushed from driver WS
            while True:
                await websocket.receive_text()  # pings / keep-alive from client
        except WebSocketDisconnect:
            pass
    finally:
        await ws_manager.disconnect_listener(assignment_id, websocket)
        db.close()


# ═══════════════════════════════════════════════════════════════
# ADMIN ALL-ASSIGNMENTS MONITOR
# ═══════════════════════════════════════════════════════════════

@router.websocket("/ws/monitor")
async def admin_monitor_ws(
    websocket: WebSocket,
    token: str = Query(...),
):
    """Admin monitor WebSocket — receives updates from ALL active assignments."""
    db = _get_db_for_ws()
    try:
        from app.utils.security import SECRET_KEY, ALGORITHM
        from jose import jwt, JWTError

        try:
            payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
            user_id = int(payload.get("sub", 0))
        except (JWTError, ValueError):
            await websocket.close(code=4001)
            return

        user = db.query(User).filter(User.id == user_id).first()
        if not user or user.role != "admin":
            await websocket.close(code=4003)
            return

        await ws_manager.connect_admin_monitor(websocket)

        try:
            while True:
                await websocket.receive_text()
        except WebSocketDisconnect:
            pass
    finally:
        await ws_manager.disconnect_admin_monitor(websocket)
        db.close()


# ═══════════════════════════════════════════════════════════════
# REST FALLBACK — Offline buffer sync + Customer poll
# ═══════════════════════════════════════════════════════════════

class LocationBatch(BaseModel):
    """Batch of GPS points for offline buffer sync."""
    points: List[dict]  # [{lat, lng, recorded_at}, ...]


@router.post("/api/tracking/{assignment_id}/location")
async def sync_offline_locations(
    assignment_id: int,
    batch: LocationBatch,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """REST endpoint for syncing buffered GPS points after reconnection.
    Accepts up to 200 points per call.
    """
    if current_user.role != "driver":
        raise HTTPException(status_code=403, detail="Driver access required.")

    assignment = db.query(DeliveryAssignment).filter(
        DeliveryAssignment.id == assignment_id,
        DeliveryAssignment.driver_id == current_user.id,
    ).first()
    if not assignment:
        raise HTTPException(status_code=404, detail="Assignment not found.")

    points = batch.points[:200]  # Hard cap
    saved = 0
    last_lat = last_lng = None

    for p in points:
        try:
            lat = float(p["lat"])
            lng = float(p["lng"])
            try:
                recorded_at = datetime.fromisoformat(p.get("recorded_at", ""))
                if recorded_at.tzinfo is None:
                    recorded_at = recorded_at.replace(tzinfo=timezone.utc)
            except (ValueError, TypeError):
                recorded_at = datetime.now(timezone.utc)

            db.add(DeliveryTracking(
                assignment_id=assignment_id,
                driver_id=current_user.id,
                latitude=lat, longitude=lng, recorded_at=recorded_at,
            ))
            last_lat, last_lng = lat, lng
            saved += 1
        except (KeyError, ValueError):
            pass

    if last_lat and last_lng:
        ds = db.query(DriverStatus).filter(DriverStatus.driver_id == current_user.id).first()
        if ds:
            ds.last_latitude = last_lat
            ds.last_longitude = last_lng
            ds.last_updated = datetime.now(timezone.utc)
        db.commit()

        # Broadcast the latest point to any live listeners
        await ws_manager.broadcast_location(
            assignment_id, current_user.id, last_lat, last_lng,
            datetime.now(timezone.utc), assignment.status
        )

    db.commit()
    return {"saved": saved}


@router.get("/api/tracking/{assignment_id}")
def get_tracking_status(
    assignment_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Customer REST poll — returns current delivery status and last known driver location."""
    assignment = db.query(DeliveryAssignment).filter(
        DeliveryAssignment.id == assignment_id
    ).first()
    if not assignment:
        raise HTTPException(status_code=404, detail="Assignment not found.")

    # Customers can only see their own deliveries
    if current_user.role == "customer" and assignment.customer_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not your delivery.")

    ds = db.query(DriverStatus).filter(DriverStatus.driver_id == assignment.driver_id).first()
    driver = db.query(User).filter(User.id == assignment.driver_id).first()

    # Last tracking point for ETA calculation
    last_point = (
        db.query(DeliveryTracking)
        .filter(DeliveryTracking.assignment_id == assignment_id)
        .order_by(DeliveryTracking.recorded_at.desc())
        .first()
    )

    return {
        "assignment_id": assignment_id,
        "status": assignment.status,
        "driver_name": driver.full_name if driver else "—",
        "driver_phone": driver.phone if driver else "—",
        "driver_latitude": last_point.latitude if last_point else None,
        "driver_longitude": last_point.longitude if last_point else None,
        "last_updated": last_point.recorded_at.isoformat() if last_point else None,
        "delivered_at": assignment.delivered_at.isoformat() if assignment.delivered_at else None,
    }
