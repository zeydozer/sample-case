## Kurulum

```bash
docker-compose build --no-cache
docker-compose up -d
```

## Test

```bash
docker ps -a
# kafka-init exited
```

```bash
Invoke-WebRequest -Uri "http://localhost:8000/healthz" -UseBasicParsing
```

```bash
Invoke-WebRequest -Uri "http://localhost:8000/comments?limit=5" -UseBasicParsing
```

```bash
Invoke-WebRequest -Uri "http://localhost:8000/comments?category=positive&limit=3" -UseBasicParsing
```

```bash
Invoke-WebRequest -Uri "http://localhost:8000/comments?q=dolor&limit=2" -UseBasicParsing
```

## Servisler

- **API**: http://localhost:8000
- **MongoDB**: localhost:27017
- **Redis**: localhost:6379
- **Kafka**: localhost:9092
- **Sentiment gRPC**: localhost:50051

## Durdurma

```bash
docker-compose down -v
```
