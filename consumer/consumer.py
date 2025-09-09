import os, json, time, uuid, random
from datetime import datetime, timezone
from kafka import KafkaConsumer, KafkaProducer
from kafka.errors import NoBrokersAvailable, KafkaTimeoutError
import grpc
import redis
from pymongo import MongoClient, ASCENDING
import sentiment_pb2, sentiment_pb2_grpc

BOOTSTRAP = os.getenv("BOOTSTRAP_SERVERS", "kafka:9092")
INPUT_TOPIC = os.getenv("INPUT_TOPIC", "raw-comments")
OUTPUT_TOPIC = os.getenv("OUTPUT_TOPIC", "processed-comments")
GROUP_ID = os.getenv("GROUP_ID", "comment-consumer")

SENTIMENT_ADDR = os.getenv("SENTIMENT_ADDR", "sentiment:50051")

MONGO_URI = os.getenv("MONGO_URI", "mongodb://mongo:27017")
MONGO_DB = os.getenv("MONGO_DB", "commentsdb")
MONGO_COL = os.getenv("MONGO_COL", "processed")

REDIS_HOST = os.getenv("REDIS_HOST", "redis")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
CACHE_TTL = int(os.getenv("CACHE_TTL_SEC", "3600"))

GRPC_MAX_RETRIES = int(os.getenv("GRPC_MAX_RETRIES", "3"))
GRPC_BASE_BACKOFF_MS = int(os.getenv("GRPC_BASE_BACKOFF_MS", "100"))

# Kafka retry/backoff ayarları
KAFKA_RETRY_BASE_DELAY_SEC = float(os.getenv("KAFKA_RETRY_BASE_DELAY_SEC", "0.5"))
KAFKA_RETRY_MAX_DELAY_SEC = float(os.getenv("KAFKA_RETRY_MAX_DELAY_SEC", "10"))

# Mongo
mongo = MongoClient(MONGO_URI)
col = mongo[MONGO_DB][MONGO_COL]
col.create_index([("commentId", ASCENDING)], unique=True)

# Redis
r = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)

# gRPC stub
channel = grpc.insecure_channel(SENTIMENT_ADDR)
stub = sentiment_pb2_grpc.SentimentServiceStub(channel)


def analyze_with_cache(text: str, trace_id: str):
  # 1) cache kontrol
  cache_key = f"sent:{hash(text)}"
  cached = r.get(cache_key)
  if cached:
    data = json.loads(cached)
    data["source"] = "cache"
    return data

  # 2) gRPC + retry/backoff
  delay = GRPC_BASE_BACKOFF_MS
  last_err = None
  for attempt in range(1, GRPC_MAX_RETRIES + 1):
    try:
      resp = stub.Analyze(
        sentiment_pb2.AnalyzeRequest(text=text, trace_id=trace_id),
        timeout=5.0,
      )
      result = {"label": resp.label, "confidence": resp.confidence, "source": "grpc"}
      # cache yaz
      r.setex(cache_key, CACHE_TTL, json.dumps(result))
      return result
    except grpc.RpcError as e:
      last_err = e
      # RESOURCE_EXHAUSTED / UNAVAILABLE vb.: backoff
      time.sleep(delay / 1000.0)
      delay *= 2

  # 3) fallback: gRPC başarısız -> etiket yok, status=fallback
  return {"label": None, "confidence": 0.0, "source": "fallback", "error": str(last_err.code()) if last_err else "unknown"}


def build_kafka_clients():
  attempt = 0
  while True:
    try:
      c = KafkaConsumer(
        INPUT_TOPIC,
        bootstrap_servers=BOOTSTRAP,
        group_id=GROUP_ID,
        enable_auto_commit=True,
        auto_offset_reset="latest",
        value_deserializer=lambda v: json.loads(v.decode("utf-8")),
        request_timeout_ms=10000,
        api_version_auto_timeout_ms=10000,
      )
      p = KafkaProducer(
        bootstrap_servers=BOOTSTRAP,
        value_serializer=lambda v: json.dumps(v, ensure_ascii=False).encode("utf-8"),
        key_serializer=lambda v: v.encode("utf-8"),
        acks="all",
        retries=5,
        request_timeout_ms=10000,
        api_version_auto_timeout_ms=10000,
      )
      return c, p
    except NoBrokersAvailable as e:
      attempt += 1
      delay = min(KAFKA_RETRY_MAX_DELAY_SEC, KAFKA_RETRY_BASE_DELAY_SEC * (2 ** min(attempt, 6)))
      delay *= (0.5 + random.random() * 0.5)  # jitter
      print(f"Kafka broker yok (consumer). {attempt}. deneme, {delay:.2f}s sonra...", flush=True)
      time.sleep(delay)


consumer = None
producer = None

while True:
  try:
    if consumer is None or producer is None:
      consumer, producer = build_kafka_clients()

    for msg in consumer:
      payload = msg.value  # {"commentId","text","ts"}
      text = payload.get("text", "")
      trace_id = str(uuid.uuid4())

      result = analyze_with_cache(text, trace_id)

      out = {
        "commentId": payload.get("commentId"),
        "text": text,
        "ts_in": payload.get("ts"),
        "processed_at": datetime.now(timezone.utc).isoformat(),
        "sentiment": result["label"],
        "confidence": result["confidence"],
        "status": result["source"],  # "grpc" | "cache" | "fallback"
        "trace_id": trace_id,
      }

      # Kafka'ya yaz
      k = payload.get("commentId", "")
      producer.send(OUTPUT_TOPIC, key=k, value=out)
      producer.flush()

      # MongoDB'ye kaydet (upsert)
      col.update_one({"commentId": out["commentId"]}, {"$set": out}, upsert=True)

  except (NoBrokersAvailable, KafkaTimeoutError, OSError) as e:
    print("kafka-io-error:", e, flush=True)
    try:
      if consumer:
        consumer.close()
    except Exception:
      pass
    try:
      if producer:
        producer.close()
    except Exception:
      pass
    consumer, producer = None, None
    time.sleep(1.0)
    continue
  except Exception as e:
    # minimum log; gerçek sistemde log/metrics eklenir
    print("consume-error:", e, flush=True)
    time.sleep(0.5)

