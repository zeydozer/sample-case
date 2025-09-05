import os, time, random, threading
from concurrent import futures
import grpc

import sentiment_pb2
import sentiment_pb2_grpc

# Config
PORT = os.getenv("PORT", "50051")
RATE_LIMIT_RPS = float(os.getenv("RATE_LIMIT_RPS", "100"))
RANDOM_DROP_PROB = float(os.getenv("RANDOM_DROP_PROB", "0.0"))
PER_CHAR_DELAY_MS = int(os.getenv("PER_CHAR_DELAY_MS", "2"))
MAX_DELAY_MS = int(os.getenv("MAX_DELAY_MS", "5000"))

# Rate limit: token bucket
class TokenBucket:
  def __init__(self, rate, capacity=None):
    self.rate = float(rate)
    self.capacity = float(capacity if capacity is not None else rate)
    self.tokens = self.capacity
    self.t = time.monotonic()
    self.lock = threading.Lock()

  def allow(self, cost=1.0):
    with self.lock:
      now = time.monotonic()
      elapsed = now - self.t
      self.t = now
      self.tokens = min(self.capacity, self.tokens + elapsed * self.rate)
      if self.tokens >= cost:
        self.tokens -= cost
        return True
      return False

bucket = TokenBucket(RATE_LIMIT_RPS)

# Cache: aynı metin tekrar analiz edildiğinde aynı sonuç
_cache = {}
_cache_lock = threading.Lock()
_labels = ("positive", "negative", "neutral")

class SentimentService(sentiment_pb2_grpc.SentimentServiceServicer):
  def Analyze(self, request, context):
    text = request.text or ""

    # Rate limit: aşılırsa drop
    if not bucket.allow():
      context.abort(grpc.StatusCode.RESOURCE_EXHAUSTED, "rate limit exceeded")

    # Rastgele drop
    if random.random() < RANDOM_DROP_PROB:
      context.abort(grpc.StatusCode.UNAVAILABLE, "random drop")

    # Gecikme: metin uzunluğuna bağlı
    delay_ms = min(MAX_DELAY_MS, max(0, len(text) * PER_CHAR_DELAY_MS))
    if delay_ms:
      time.sleep(delay_ms / 1000.0)

    # Sonuç: ilkinde rastgele, sonrasında aynı metin için aynı sonuç
    with _cache_lock:
      label = _cache.get(text)
      if label is None:
        label = random.choice(_labels)
        _cache[text] = label

    confidence = {"positive": 0.9, "negative": 0.9, "neutral": 0.6}[label]
    return sentiment_pb2.AnalyzeResponse(text=text, label=label, confidence=confidence)

def serve():
  server = grpc.server(futures.ThreadPoolExecutor(max_workers=16))
  sentiment_pb2_grpc.add_SentimentServiceServicer_to_server(SentimentService(), server)
  server.add_insecure_port(f"[::]:{PORT}")
  server.start()
  server.wait_for_termination()

if __name__ == "__main__":
  serve()
