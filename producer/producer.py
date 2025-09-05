import json, os, random, string, time
from datetime import datetime, timezone
from kafka import KafkaProducer

BOOTSTRAP = os.getenv("BOOTSTRAP_SERVERS", "kafka:9092")
TOPIC = os.getenv("TOPIC", "raw-comments")
MIN_MS = int(os.getenv("MIN_INTERVAL_MS", "100"))
MAX_MS = int(os.getenv("MAX_INTERVAL_MS", "10000"))
DUP_P = float(os.getenv("DUP_REPEAT_PROB", "0.25"))

lorem_words = (
  "lorem ipsum dolor sit amet consectetur adipiscing elit sed do eiusmod tempor"
  "incididunt ut labore et dolore magna aliqua ut enim ad minim veniam quis nostrud"
  "exercitation ullamco laboris nisi ut aliquip ex ea commodo consequat"
  "duis aute irure dolor in reprehenderit in voluptate velit esse cillum dolore eu"
  "fugiat nulla pariatur excepteur sint occaecat cupidatat non proident sunt in culpa"
  "qui officia deserunt mollit anim id est laborum"
).split()

def rand_text():
  n = random.randint(5, 80)  # farklı uzunluklar
  return " ".join(random.choices(lorem_words, k=n)).strip()

def new_id(k=12):
  alphabet = string.ascii_lowercase + string.digits
  return "".join(random.choices(alphabet, k=k))

producer = KafkaProducer(
  bootstrap_servers=BOOTSTRAP,
  value_serializer=lambda v: json.dumps(v, ensure_ascii=False).encode("utf-8"),
  key_serializer=lambda v: v.encode("utf-8"),
  linger_ms=10,
)

last_texts = []

while True:
  use_dup = last_texts and random.random() < DUP_P
  if use_dup:
    text = random.choice(last_texts)
  else:
    text = rand_text()
    if len(last_texts) > 1000:
      last_texts.pop(0)
    last_texts.append(text)

  payload = {
    "commentId": new_id(),
    "text": text,
    "ts": datetime.now(timezone.utc).isoformat(),
  }

  # key: aynı metin tekrar gelse de farklı commentId olabilir
  key = str(abs(hash(text)) % (10**12))

  producer.send(TOPIC, key=key, value=payload)
  producer.flush()

  # değişken üretim sıklığı: kimi zaman 100ms, kimi zaman 10s
  interval_ms = random.randint(MIN_MS, MAX_MS)
  time.sleep(interval_ms / 1000.0)
