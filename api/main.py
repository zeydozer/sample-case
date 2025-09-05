import os
from datetime import datetime
from dateutil import parser as dt
from typing import Optional, List
from fastapi import FastAPI, Query
from motor.motor_asyncio import AsyncIOMotorClient

MONGO_URI = os.getenv("MONGO_URI", "mongodb://mongo:27017")
DB = os.getenv("MONGO_DB", "commentsdb")
COL = os.getenv("MONGO_COL", "processed")

app = FastAPI(title="Comments API")

client = AsyncIOMotorClient(MONGO_URI)
col = client[DB][COL]

@app.on_event("startup")
async def _idx():
  await col.create_index("commentId", unique=True)
  await col.create_index("sentiment")
  await col.create_index("processed_at")

@app.get("/healthz")
async def healthz():
  doc = await col.find_one({}, {"_id": 1})
  return {"ok": True, "db": bool(doc is not None)}

def to_iso(dtobj: Optional[datetime]):
  return dtobj.isoformat() if isinstance(dtobj, datetime) else dtobj

@app.get("/comments")
async def list_comments(
  category: Optional[str] = Query(None, regex="^(positive|negative|neutral)$"),
  q: Optional[str] = None,
  since: Optional[str] = None,   # ISO8601
  before: Optional[str] = None,  # ISO8601
  limit: int = Query(50, ge=1, le=500),
  skip: int = Query(0, ge=0),
  sort: str = Query("-processed_at"),  # -processed_at / processed_at
):
  filt = {}
  if category:
    filt["sentiment"] = category
  if q:
    filt["text"] = {"$regex": q, "$options": "i"}
  t = {}
  if since:
    t["$gte"] = dt.isoparse(since)
  if before:
    t["$lte"] = dt.isoparse(before)
  if t:
    filt["processed_at"] = t

  sort_spec = [("processed_at", -1 if sort.startswith("-") else 1)]

  cursor = col.find(filt, {
    "_id": 0,
    "commentId": 1,
    "text": 1,
    "sentiment": 1,
    "confidence": 1,
    "processed_at": 1,
    "ts_in": 1
  }).sort(sort_spec).skip(skip).limit(limit)

  items = []
  async for d in cursor:
    d["timestamp"] = to_iso(d.pop("processed_at", None)) or d.get("ts_in")
    items.append({
      "commentId": d.get("commentId"),
      "text": d.get("text"),
      "sentiment": d.get("sentiment"),
      "confidence": d.get("confidence"),
      "timestamp": d.get("timestamp"),
    })
  return {"count": len(items), "items": items}
