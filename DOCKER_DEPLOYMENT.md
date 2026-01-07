# Scribe Agent - Docker Deployment

Run the Scribe agent in Docker containers for easy deployment and management.

## Quick Start

### Run with Docker

```bash
docker run -d \
  --name scribe-agent \
  --restart unless-stopped \
  -e SERVER_HOST="your-server:8000" \
  -e AGENT_NAME="$(hostname)-docker" \
  -e LOG_FILE="/var/log/app.log" \
  -v /var/log:/var/log:ro \
  scribe-agent:latest
```

### Run with Docker Compose

Create `docker-compose.yml`:

```yaml
version: '3.8'

services:
  scribe-agent:
    image: scribe-agent:latest
    container_name: scribe-agent
    restart: unless-stopped
    environment:
      - SERVER_HOST=your-server:8000
      - AGENT_NAME=my-app-server
      - LOG_FILE=/var/log/app.log
      - METRICS_INTERVAL=60
    volumes:
      - /var/log:/var/log:ro  # Mount host logs (read-only)
      - ./config.json:/etc/scribe/config.json:ro  # Optional: custom config
    networks:
      - monitoring
    logging:
      driver: "json-file"
      options:
        max-size: "10m"
        max-file: "3"

networks:
  monitoring:
    external: true
```

Start with:
```bash
docker-compose up -d
```

---

## Building the Docker Image

### Dockerfile

The repository includes a Dockerfile:

```dockerfile
FROM golang:1.21-alpine AS builder

WORKDIR /build

# Copy go mod files
COPY go.mod go.sum ./
RUN go mod download

# Copy source
COPY . .

# Build binary
RUN CGO_ENABLED=0 GOOS=linux go build -ldflags="-s -w" -o scribe-agent .

# Runtime image
FROM alpine:latest

RUN apk --no-cache add ca-certificates tzdata

WORKDIR /app

# Copy binary from builder
COPY --from=builder /build/scribe-agent .

# Create non-root user
RUN addgroup -g 1000 scribe && \
    adduser -D -u 1000 -G scribe scribe && \
    chown -R scribe:scribe /app

USER scribe

ENTRYPOINT ["./scribe-agent"]
CMD ["-config", "/etc/scribe/config.json"]
```

### Build Image

```bash
cd scribe
docker build -t scribe-agent:latest .
```

### Build Multi-Architecture

```bash
docker buildx create --use
docker buildx build \
  --platform linux/amd64,linux/arm64 \
  -t scribe-agent:latest \
  --push .
```

---

## Configuration

### Environment Variables

| Variable | Description | Default | Required |
|----------|-------------|---------|----------|
| `SERVER_HOST` | LogLibrarian backend address | `127.0.0.1:8000` | Yes |
| `AGENT_NAME` | Agent display name | Container hostname | No |
| `LOG_FILE` | Log file to monitor | `/var/log/app.log` | Yes |
| `METRICS_INTERVAL` | Metrics collection interval (seconds) | `60` | No |
| `LOG_BATCH_SIZE` | Number of logs per batch | `50` | No |
| `LOG_BATCH_INTERVAL` | Seconds between log batches | `5` | No |
| `SSL_ENABLED` | Use SSL/TLS | `false` | No |
| `SSL_VERIFY` | Verify SSL certificates | `true` | No |

### Using Config File

Mount a configuration file instead of using environment variables:

```bash
docker run -d \
  --name scribe-agent \
  -v /path/to/config.json:/etc/scribe/config.json:ro \
  -v /var/log:/var/log:ro \
  scribe-agent:latest
```

---

## Use Cases

### 1. Monitor Docker Host Logs

Monitor the Docker host's system logs:

```yaml
services:
  scribe-agent:
    image: scribe-agent:latest
    environment:
      - SERVER_HOST=loglibrarian:8000
      - AGENT_NAME=docker-host
      - LOG_FILE=/var/log/syslog
    volumes:
      - /var/log:/var/log:ro
```

### 2. Monitor Application Container Logs

Monitor logs from another container:

```yaml
services:
  app:
    image: nginx:latest
    volumes:
      - app-logs:/var/log/nginx

  scribe-agent:
    image: scribe-agent:latest
    environment:
      - SERVER_HOST=loglibrarian:8000
      - AGENT_NAME=nginx-app
      - LOG_FILE=/app-logs/access.log
    volumes:
      - app-logs:/app-logs:ro

volumes:
  app-logs:
```

### 3. Sidecar Pattern

Run as a sidecar container in Kubernetes:

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: myapp
spec:
  containers:
  - name: app
    image: myapp:latest
    volumeMounts:
    - name: logs
      mountPath: /var/log/app
  
  - name: scribe-agent
    image: scribe-agent:latest
    env:
    - name: SERVER_HOST
      value: "loglibrarian:8000"
    - name: AGENT_NAME
      value: "myapp-pod"
    - name: LOG_FILE
      value: "/var/log/app/app.log"
    volumeMounts:
    - name: logs
      mountPath: /var/log/app
      readOnly: true
  
  volumes:
  - name: logs
    emptyDir: {}
```

### 4. Kubernetes DaemonSet

Deploy to all nodes:

```yaml
apiVersion: apps/v1
kind: DaemonSet
metadata:
  name: scribe-agent
  namespace: monitoring
spec:
  selector:
    matchLabels:
      app: scribe-agent
  template:
    metadata:
      labels:
        app: scribe-agent
    spec:
      containers:
      - name: scribe-agent
        image: scribe-agent:latest
        env:
        - name: SERVER_HOST
          value: "loglibrarian.monitoring:8000"
        - name: AGENT_NAME
          valueFrom:
            fieldRef:
              fieldPath: spec.nodeName
        - name: LOG_FILE
          value: "/var/log/syslog"
        volumeMounts:
        - name: host-logs
          mountPath: /var/log
          readOnly: true
        resources:
          limits:
            memory: 256Mi
            cpu: 200m
          requests:
            memory: 128Mi
            cpu: 100m
      volumes:
      - name: host-logs
        hostPath:
          path: /var/log
          type: Directory
      hostNetwork: true
      tolerations:
      - effect: NoSchedule
        operator: Exists
```

---

## Docker Compose Full Stack

Deploy entire LogLibrarian stack:

```yaml
version: '3.8'

services:
  # Backend
  librarian:
    build: ./librarian
    container_name: loglibrarian-backend
    ports:
      - "8000:8000"
    environment:
      - DATABASE_URL=sqlite:///data/librarian.db
    volumes:
      - librarian-data:/data
    networks:
      - loglibrarian

  # Frontend Dashboard
  dashboard:
    build: ./dashboard
    container_name: loglibrarian-dashboard
    ports:
      - "5173:5173"
    depends_on:
      - librarian
    networks:
      - loglibrarian

  # Scribe Agent (example)
  scribe-agent:
    build: ./scribe
    container_name: scribe-agent-host
    environment:
      - SERVER_HOST=librarian:8000
      - AGENT_NAME=docker-host
      - LOG_FILE=/var/log/syslog
    volumes:
      - /var/log:/var/log:ro
    depends_on:
      - librarian
    networks:
      - loglibrarian
    restart: unless-stopped

volumes:
  librarian-data:

networks:
  loglibrarian:
    driver: bridge
```

Start everything:
```bash
docker-compose up -d
```

---

## Monitoring & Troubleshooting

### View Container Logs

```bash
docker logs scribe-agent -f
```

### Check Container Status

```bash
docker ps -f name=scribe-agent
```

### Inspect Container

```bash
docker inspect scribe-agent
```

### Access Container Shell

```bash
docker exec -it scribe-agent sh
```

### View Resource Usage

```bash
docker stats scribe-agent
```

### Restart Container

```bash
docker restart scribe-agent
```

---

## Production Considerations

### 1. Resource Limits

Always set resource limits:

```yaml
services:
  scribe-agent:
    # ...
    deploy:
      resources:
        limits:
          cpus: '0.5'
          memory: 256M
        reservations:
          cpus: '0.1'
          memory: 128M
```

### 2. Health Checks

Add health checks:

```yaml
services:
  scribe-agent:
    # ...
    healthcheck:
      test: ["CMD", "pgrep", "scribe-agent"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 10s
```

### 3. Logging

Configure proper logging:

```yaml
services:
  scribe-agent:
    # ...
    logging:
      driver: "json-file"
      options:
        max-size: "10m"
        max-file: "3"
```

### 4. Security

- Run as non-root user (built into Dockerfile)
- Mount log directories as read-only
- Use secrets for sensitive configuration
- Scan images for vulnerabilities

```bash
docker scan scribe-agent:latest
```

### 5. Updates

```bash
# Pull latest image
docker pull scribe-agent:latest

# Recreate container
docker-compose up -d --force-recreate scribe-agent
```

---

## Registry Deployment

### Push to Docker Hub

```bash
docker tag scribe-agent:latest yourusername/scribe-agent:latest
docker tag scribe-agent:latest yourusername/scribe-agent:v1.0.0

docker push yourusername/scribe-agent:latest
docker push yourusername/scribe-agent:v1.0.0
```

### Push to Private Registry

```bash
docker tag scribe-agent:latest registry.example.com/scribe-agent:latest
docker push registry.example.com/scribe-agent:latest
```

### Pull and Run

```bash
docker pull yourusername/scribe-agent:latest
docker run -d \
  --name scribe-agent \
  -e SERVER_HOST="your-server:8000" \
  yourusername/scribe-agent:latest
```

---

## Cleanup

```bash
# Stop and remove container
docker stop scribe-agent
docker rm scribe-agent

# Remove image
docker rmi scribe-agent:latest

# Remove all (Docker Compose)
docker-compose down -v
```
