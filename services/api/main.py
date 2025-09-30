import os, time
from datetime import datetime
from typing import List, Optional

from fastapi import FastAPI, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import (
    create_engine, Column, Integer, String, Boolean, Float, DateTime, ForeignKey
)
from sqlalchemy.orm import declarative_base, sessionmaker, Session, relationship

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+psycopg2://postgres:postgres@db:5432/uptime"
)

# DB setup with simple retry on startup
for i in range(20):
    try:
        engine = create_engine(DATABASE_URL, pool_pre_ping=True)
        break
    except Exception as e:
        print("DB connect retry...", e)
        time.sleep(1)

SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)
Base = declarative_base()

class Monitor(Base):
    __tablename__ = "monitors"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    url = Column(String, nullable=False)
    method = Column(String, default="GET")
    interval_sec = Column(Integer, default=60)
    timeout_ms = Column(Integer, default=5000)
    expected_statuses = Column(String, default="200-399")
    is_enabled = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)

class Check(Base):
    __tablename__ = "checks"
    id = Column(Integer, primary_key=True, index=True)
    monitor_id = Column(Integer, ForeignKey("monitors.id"), index=True)
    ts = Column(DateTime, default=datetime.utcnow, index=True)
    status_code = Column(Integer, nullable=True)
    latency_ms = Column(Float, nullable=True)
    ok = Column(Boolean, default=False)
    error_reason = Column(String, nullable=True)
    monitor = relationship("Monitor")

# Create tables (idempotent)
for i in range(20):
    try:
        Base.metadata.create_all(bind=engine)
        break
    except Exception as e:
        print("DB migrate retry...", e)
        time.sleep(1)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# ---- Pydantic ----
class MonitorCreate(BaseModel):
    name: str
    url: str
    method: str = "GET"
    interval_sec: int = 60
    timeout_ms: int = 5000
    expected_statuses: str = "200-399"
    is_enabled: bool = True

class MonitorOut(BaseModel):
    id: int
    name: str
    url: str
    method: str
    interval_sec: int
    timeout_ms: int
    expected_statuses: str
    is_enabled: bool
    class Config:
        from_attributes = True

class CheckCreate(BaseModel):
    monitor_id: int
    status_code: Optional[int] = None
    latency_ms: Optional[float] = None
    ok: bool = False
    error_reason: Optional[str] = None

class CheckOut(BaseModel):
    id: int
    monitor_id: int
    ts: datetime
    status_code: Optional[int]
    latency_ms: Optional[float]
    ok: bool
    error_reason: Optional[str]
    class Config:
        from_attributes = True

app = FastAPI(title="Uptime API")

@app.get("/health")
def health():
    return {"ok": True}

@app.post("/monitors", response_model=MonitorOut)
def create_monitor(payload: MonitorCreate, db: Session = Depends(get_db)):
    m = Monitor(**payload.model_dump())
    db.add(m)
    db.commit()
    db.refresh(m)
    return m

@app.get("/monitors", response_model=List[MonitorOut])
def list_monitors(db: Session = Depends(get_db)):
    return db.query(Monitor).order_by(Monitor.id.desc()).all()

@app.get("/public/monitors", response_model=List[MonitorOut])
def list_public_monitors(db: Session = Depends(get_db)):
    return db.query(Monitor).filter(Monitor.is_enabled == True).all()

@app.get("/public/monitors/{monitor_id}/checks", response_model=List[CheckOut])
def list_checks(
    monitor_id: int,
    limit: int = Query(50, ge=1, le=500),
    db: Session = Depends(get_db),
):
    rows = (db.query(Check)
              .filter(Check.monitor_id == monitor_id)
              .order_by(Check.ts.desc())
              .limit(limit)
              .all())
    return rows

@app.post("/checks", response_model=CheckOut)
def create_check(payload: CheckCreate, db: Session = Depends(get_db)):
    # Basic FK check
    mon = db.query(Monitor).get(payload.monitor_id)
    if not mon:
        raise HTTPException(404, "Monitor not found")
    c = Check(**payload.model_dump())
    db.add(c)
    db.commit()
    db.refresh(c)
    return c
