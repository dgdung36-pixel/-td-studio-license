"""Server-authoritative, privacy-noticed license keys for Trong Dung Studio.

No admin secrets or plaintext issued keys are ever put in the iOS binary or database.
The authorization token is opaque and revocable. IPs are logged only for explicit
license activation / verification, with automatic 30-day retention cleanup.
"""
from __future__ import annotations

import hashlib
import hmac
import ipaddress
import os
import secrets
import time
import uuid
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Lock
from typing import Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, UniqueConstraint, create_engine, delete, func, select
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, relationship, sessionmaker


def utcnow() -> datetime:
    # SQLAlchemy stores UTC naive values, consistently; ISO responses are UTC aware.
    return datetime.now(timezone.utc).replace(tzinfo=None)


def iso(value: datetime | None) -> str | None:
    return value.replace(tzinfo=timezone.utc).isoformat().replace('+00:00', 'Z') if value else None


def hash_secret(value: str) -> str:
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


class Base(DeclarativeBase):
    pass


class License(Base):
    __tablename__ = 'licenses'
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    label: Mapped[str] = mapped_column(String(80), nullable=False)
    key_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    key_hint: Mapped[str] = mapped_column(String(12), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime)
    max_devices: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    revoked: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime)
    devices: Mapped[list[Device]] = relationship(back_populates='license', cascade='all, delete-orphan')
    sessions: Mapped[list[AccessSession]] = relationship(back_populates='license', cascade='all, delete-orphan')


class Device(Base):
    __tablename__ = 'license_devices'
    __table_args__ = (UniqueConstraint('license_id', 'device_hash', name='uq_license_device'),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    license_id: Mapped[str] = mapped_column(String(36), ForeignKey('licenses.id'), nullable=False, index=True)
    device_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    license: Mapped[License] = relationship(back_populates='devices')


class AccessSession(Base):
    __tablename__ = 'license_sessions'
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    license_id: Mapped[str] = mapped_column(String(36), ForeignKey('licenses.id'), nullable=False, index=True)
    device_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    license: Mapped[License] = relationship(back_populates='sessions')


class AccessEvent(Base):
    __tablename__ = 'license_events'
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    license_id: Mapped[str | None] = mapped_column(String(36), index=True)
    event_type: Mapped[str] = mapped_column(String(24), nullable=False)
    result: Mapped[str] = mapped_column(String(16), nullable=False)
    ip_address: Mapped[str] = mapped_column(String(45), nullable=False)
    device_hint: Mapped[str] = mapped_column(String(12), nullable=False)
    happened_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False, index=True)


raw_url = os.getenv('DATABASE_URL', '').strip() or 'sqlite:///./license-dev.sqlite3'
if raw_url.startswith('postgres://'):
    raw_url = 'postgresql+psycopg://' + raw_url[len('postgres://'):]
elif raw_url.startswith('postgresql://'):
    raw_url = 'postgresql+psycopg://' + raw_url[len('postgresql://'):]
if os.getenv('APP_ENV') == 'production' and raw_url.startswith('sqlite:'):
    raise RuntimeError('Production licenses require a persistent PostgreSQL DATABASE_URL')
engine = create_engine(raw_url, pool_pre_ping=True, connect_args={'check_same_thread': False} if raw_url.startswith('sqlite:') else {})
Base.metadata.create_all(engine)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)

router = APIRouter()
ADMIN_KEY = os.getenv('LICENSE_ADMIN_TOKEN', '')
RETENTION_DAYS = min(90, max(1, int(os.getenv('ACCESS_LOG_RETENTION_DAYS', '30'))))
SESSION_DAYS = 30
bad_hits: dict[str, deque[float]] = defaultdict(deque)
rate_lock = Lock()
last_cleanup = 0.0
cleanup_lock = Lock()
# Optional, explicitly pinned ingress ranges. Never enable trust for all peers.
TRUSTED_PROXIES = tuple(
    ipaddress.ip_network(block.strip(), strict=False)
    for block in os.getenv('TRUSTED_PROXY_CIDRS', '').split(',') if block.strip()
)


def db_session():
    with SessionLocal() as db:
        yield db


def client_ip(request: Request) -> str:
    """Resolve a public IP only across explicit trusted proxy networks.

    The rightmost untrusted address is the original caller for a chain where
    every ingress hop is trusted; never use a caller-provided leftmost address.
    """
    remote = request.client.host if request.client else ''
    try:
        peer = ipaddress.ip_address(remote)
    except ValueError:
        return 'unknown'
    if not any(peer in network for network in TRUSTED_PROXIES):
        return str(peer)
    header = request.headers.get('x-forwarded-for', '')
    if len(header) > 512:
        return str(peer)
    parts = [p.strip() for p in header.split(',') if p.strip()]
    if not parts or len(parts) > 16:
        return str(peer)
    for part in reversed(parts):
        try:
            candidate = ipaddress.ip_address(part)
        except ValueError:
            return str(peer)  # malformed forwarding chain: fail closed
        if not any(candidate in network for network in TRUSTED_PROXIES):
            return str(candidate)
    return str(peer)


def allow_attempt(ip: str) -> None:
    now = time.monotonic()
    with rate_lock:
        q = bad_hits[ip]
        while q and now - q[0] > 900:
            q.popleft()
        if len(q) >= 15:
            raise HTTPException(status_code=429, detail='Thử quá nhiều lần. Vui lòng thử lại sau.')
        q.append(now)


def log_event(db: Session, request: Request, event_type: str, result: str, device_hash: str = '', license_id: str | None = None):
    db.add(AccessEvent(id=str(uuid.uuid4()), license_id=license_id, event_type=event_type,
                       result=result, ip_address=client_ip(request), device_hint=device_hash[:10], happened_at=utcnow()))
    cleanup_old_logs(db)


def cleanup_old_logs(db: Session):
    global last_cleanup
    now = time.monotonic()
    if now - last_cleanup < 3600:
        return
    with cleanup_lock:
        if now - last_cleanup < 3600:
            return
        db.execute(delete(AccessEvent).where(AccessEvent.happened_at < utcnow() - timedelta(days=RETENTION_DAYS)))
        db.execute(delete(AccessSession).where(AccessSession.expires_at < utcnow()))
        last_cleanup = now


def check_admin(authorization: str | None = Header(default=None)):
    if len(ADMIN_KEY) < 32:
        raise HTTPException(503, detail='Admin chưa được cấu hình trên server')
    candidate = authorization.removeprefix('Bearer ').strip() if authorization and authorization.startswith('Bearer ') else ''
    if not hmac.compare_digest(candidate, ADMIN_KEY):
        raise HTTPException(401, detail='Admin token không hợp lệ', headers={'WWW-Authenticate': 'Bearer'})
    return True


def new_key() -> str:
    return 'TD-' + secrets.token_urlsafe(24)


def valid_license(item: License | None) -> bool:
    return bool(item and not item.revoked and (item.expires_at is None or item.expires_at > utcnow()))


def license_info(item: License, db: Session):
    return dict(id=item.id, label=item.label, key_hint=item.key_hint, created_at=iso(item.created_at),
                expires_at=iso(item.expires_at), max_devices=item.max_devices,
                device_count=db.scalar(select(func.count(Device.id)).where(Device.license_id == item.id)),
                revoked=item.revoked, last_seen_at=iso(item.last_seen_at))


class Activation(BaseModel):
    license_key: str = Field(min_length=20, max_length=120)
    device_id: uuid.UUID
    privacy_notice_accepted: Literal[True]


class Verify(BaseModel):
    session_token: str = Field(min_length=20, max_length=140)
    device_id: uuid.UUID


class CreateLicense(BaseModel):
    label: str = Field(min_length=1, max_length=80)
    valid_days: int | None = Field(default=30, ge=1, le=3650)
    max_devices: int = Field(default=1, ge=1, le=20)


class RotateLicense(BaseModel):
    reset_devices: bool = False


@router.get('/v1/license/status')
def license_status():
    return {'ready': len(ADMIN_KEY) >= 32, 'service': 'td-license-v50',
            'ip_log_retention_days': RETENTION_DAYS, 'privacy_notice_required': True}


@router.post('/v1/license/activate')
def activate(body: Activation, request: Request, db: Session = Depends(db_session)):
    if len(ADMIN_KEY) < 32:
        raise HTTPException(503, detail='Server chưa cấu hình hệ thống cấp key')
    dh = hash_secret(str(body.device_id))
    allow_attempt(client_ip(request) + ":" + dh[:16])
    item = db.scalar(select(License).where(License.key_hash == hash_secret(body.license_key)).with_for_update())
    if not valid_license(item):
        log_event(db, request, 'activate', 'denied', dh, item.id if item else None)
        db.commit()
        raise HTTPException(401, detail='Key không hợp lệ, hết hạn hoặc đã bị thu hồi')
    device = db.scalar(select(Device).where(Device.license_id == item.id, Device.device_hash == dh))
    if not device:
        count = db.scalar(select(func.count(Device.id)).where(Device.license_id == item.id)) or 0
        if count >= item.max_devices:
            log_event(db, request, 'activate', 'denied', dh, item.id)
            db.commit()
            raise HTTPException(403, detail='Key đã đạt giới hạn thiết bị')
        device = Device(id=str(uuid.uuid4()), license_id=item.id, device_hash=dh)
        db.add(device)
    device.last_seen_at = utcnow()
    item.last_seen_at = utcnow()
    # Invalidate any session for this license on this device before reissuing.
    db.execute(delete(AccessSession).where(AccessSession.license_id == item.id, AccessSession.device_hash == dh))
    raw_token = secrets.token_urlsafe(36)
    session_expires = utcnow() + timedelta(days=SESSION_DAYS)
    db.add(AccessSession(id=str(uuid.uuid4()), license_id=item.id, device_hash=dh,
                         token_hash=hash_secret(raw_token), expires_at=session_expires))
    log_event(db, request, 'activate', 'allowed', dh, item.id)
    db.commit()
    return {'session_token': raw_token, 'session_expires_at': iso(session_expires),
            'label': item.label, 'key_expires_at': iso(item.expires_at)}


def check_session(body: Verify, db: Session):
    sess = db.scalar(select(AccessSession).where(AccessSession.token_hash == hash_secret(body.session_token)))
    dh = hash_secret(str(body.device_id))
    if not sess or not hmac.compare_digest(sess.device_hash, dh) or sess.expires_at <= utcnow():
        return None, None, dh
    item = db.get(License, sess.license_id)
    if not valid_license(item):
        return None, None, dh
    device = db.scalar(select(Device).where(Device.license_id == item.id, Device.device_hash == dh))
    if not device:
        return None, None, dh
    return item, device, dh


@router.post('/v1/license/verify')
def verify(body: Verify, request: Request, db: Session = Depends(db_session)):
    item, device, dh = check_session(body, db)
    if not item:
        log_event(db, request, 'verify', 'denied', dh)
        db.commit()
        raise HTTPException(401, detail='Phiên đã hết hạn hoặc key đã bị thu hồi')
    device.last_seen_at = utcnow()
    item.last_seen_at = utcnow()
    log_event(db, request, 'verify', 'allowed', dh, item.id)
    db.commit()
    return {'valid': True, 'label': item.label, 'key_expires_at': iso(item.expires_at)}


@router.post('/v1/license/logout')
def logout(body: Verify, db: Session = Depends(db_session)):
    dh = hash_secret(str(body.device_id))
    db.execute(delete(AccessSession).where(AccessSession.token_hash == hash_secret(body.session_token),
                                           AccessSession.device_hash == dh))
    db.commit()
    return {'signed_out': True}


@router.get('/v1/admin/keys', dependencies=[Depends(check_admin)])
def list_keys(db: Session = Depends(db_session)):
    items = db.scalars(select(License).order_by(License.created_at.desc()).limit(500)).all()
    return {'items': [license_info(item, db) for item in items]}


@router.post('/v1/admin/keys', dependencies=[Depends(check_admin)])
def create_license(body: CreateLicense, db: Session = Depends(db_session)):
    raw_key = new_key()
    item = License(id=str(uuid.uuid4()), label=body.label.strip(), key_hash=hash_secret(raw_key),
                   key_hint=raw_key[-6:], max_devices=body.max_devices,
                   expires_at=utcnow() + timedelta(days=body.valid_days) if body.valid_days is not None else None)
    if not item.label:
        raise HTTPException(422, detail='Tên key không được để trống')
    db.add(item)
    db.commit()
    return {'key_once': raw_key, 'item': license_info(item, db)}


@router.post('/v1/admin/keys/{key_id}/rotate', dependencies=[Depends(check_admin)])
def rotate_license(key_id: uuid.UUID, body: RotateLicense, db: Session = Depends(db_session)):
    item = db.get(License, str(key_id))
    if not item:
        raise HTTPException(404, 'Không tìm thấy key')
    raw_key = new_key()
    item.key_hash, item.key_hint = hash_secret(raw_key), raw_key[-6:]
    db.execute(delete(AccessSession).where(AccessSession.license_id == item.id))
    if body.reset_devices:
        db.execute(delete(Device).where(Device.license_id == item.id))
    db.commit()
    return {'key_once': raw_key, 'item': license_info(item, db)}


@router.post('/v1/admin/keys/{key_id}/revoke', dependencies=[Depends(check_admin)])
def revoke_license(key_id: uuid.UUID, db: Session = Depends(db_session)):
    item = db.get(License, str(key_id))
    if not item:
        raise HTTPException(404, 'Không tìm thấy key')
    item.revoked = True
    db.execute(delete(AccessSession).where(AccessSession.license_id == item.id))
    db.commit()
    return {'revoked': True, 'item': license_info(item, db)}


@router.post('/v1/admin/keys/{key_id}/restore', dependencies=[Depends(check_admin)])
def restore_license(key_id: uuid.UUID, db: Session = Depends(db_session)):
    item = db.get(License, str(key_id))
    if not item:
        raise HTTPException(404, 'Không tìm thấy key')
    item.revoked = False
    db.commit()
    return {'revoked': False, 'item': license_info(item, db)}


@router.delete('/v1/admin/keys/{key_id}', dependencies=[Depends(check_admin)])
def delete_license(key_id: uuid.UUID, db: Session = Depends(db_session)):
    item = db.get(License, str(key_id))
    if not item:
        raise HTTPException(404, 'Không tìm thấy key')
    db.delete(item)
    db.commit()
    return {'deleted': True}


@router.get('/v1/admin/keys/{key_id}/devices', dependencies=[Depends(check_admin)])
def devices(key_id: uuid.UUID, db: Session = Depends(db_session)):
    if not db.get(License, str(key_id)):
        raise HTTPException(404, 'Không tìm thấy key')
    items = db.scalars(select(Device).where(Device.license_id == str(key_id)).order_by(Device.first_seen_at.desc())).all()
    return {'items': [{'id': d.id, 'device_hint': d.device_hash[:10],
                       'first_seen_at': iso(d.first_seen_at), 'last_seen_at': iso(d.last_seen_at)} for d in items]}


@router.delete('/v1/admin/keys/{key_id}/devices/{device_id}', dependencies=[Depends(check_admin)])
def unbind_device(key_id: uuid.UUID, device_id: uuid.UUID, db: Session = Depends(db_session)):
    item = db.get(Device, str(device_id))
    if not item or item.license_id != str(key_id):
        raise HTTPException(404, 'Không tìm thấy thiết bị')
    db.execute(delete(AccessSession).where(AccessSession.license_id == str(key_id), AccessSession.device_hash == item.device_hash))
    db.delete(item)
    db.commit()
    return {'unbound': True}


@router.get('/v1/admin/logs', dependencies=[Depends(check_admin)])
def view_logs(limit: int = 100, db: Session = Depends(db_session)):
    cleanup_old_logs(db)
    db.commit()
    items = db.scalars(select(AccessEvent).order_by(AccessEvent.happened_at.desc()).limit(min(250, max(1, limit)))).all()
    return {'retention_days': RETENTION_DAYS,
            'items': [{'time': iso(e.happened_at), 'event': e.event_type, 'result': e.result,
                       'ip': e.ip_address, 'key_id': e.license_id, 'device_hint': e.device_hint} for e in items]}


@router.delete('/v1/admin/logs', dependencies=[Depends(check_admin)])
def delete_logs(db: Session = Depends(db_session)):
    count = db.execute(delete(AccessEvent)).rowcount
    db.commit()
    return {'deleted_count': count}


HERE = Path(__file__).parent


@router.get('/admin', include_in_schema=False)
def dashboard():
    return FileResponse(HERE / 'admin.html', headers={'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff',
                                                      'Content-Security-Policy': "default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; base-uri 'none'; form-action 'none'"})


@router.get('/admin/admin.js', include_in_schema=False)
def dashboard_js():
    return FileResponse(HERE / 'admin.js', media_type='text/javascript', headers={'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff'})


@router.get('/admin/admin.css', include_in_schema=False)
def dashboard_css():
    return FileResponse(HERE / 'admin.css', media_type='text/css', headers={'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff'})
