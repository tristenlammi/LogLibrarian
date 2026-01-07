# =============================================================================
# Stage 1: Go Builder - Build the main Scribe agent binary
# =============================================================================
FROM golang:1.21-alpine AS builder

WORKDIR /build

# Download dependencies first (better layer caching)
COPY go.mod go.sum ./
RUN go mod download

# Copy source and build
COPY *.go ./
RUN CGO_ENABLED=0 GOOS=linux GOARCH=amd64 go build -a -installsuffix cgo -ldflags="-s -w" -o scribe-agent .

# =============================================================================
# Stage 2: AI Fetcher - Download llama.cpp server binary
# =============================================================================
FROM debian:bookworm-slim AS ai-fetcher

# Install curl and unzip for downloading
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    unzip \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /ai

# Download the latest llama.cpp release for Linux x86_64
# Using the pre-built server binary from official releases
ARG LLAMA_CPP_VERSION=latest
RUN set -ex && \
    # Get the latest release tag if not specified
    if [ "$LLAMA_CPP_VERSION" = "latest" ]; then \
        LLAMA_CPP_VERSION=$(curl -sL https://api.github.com/repos/ggerganov/llama.cpp/releases/latest | grep '"tag_name"' | cut -d'"' -f4); \
    fi && \
    echo "Downloading llama.cpp version: ${LLAMA_CPP_VERSION}" && \
    # Download the Linux x86_64 binary (Ubuntu build works on most Linux distros)
    curl -L -o llama-server.zip \
        "https://github.com/ggerganov/llama.cpp/releases/download/${LLAMA_CPP_VERSION}/llama-${LLAMA_CPP_VERSION}-bin-ubuntu-x64.zip" && \
    # Extract and find the server binary
    unzip llama-server.zip && \
    # Find and copy the server binary (path varies by release)
    find . -name "llama-server" -type f -exec cp {} /ai/llama-runner \; && \
    # Make executable
    chmod +x /ai/llama-runner && \
    # Verify the binary exists
    ls -la /ai/llama-runner && \
    # Clean up
    rm -rf llama-server.zip build/

# =============================================================================
# Stage 3: Final Runtime Image
# =============================================================================
FROM debian:bookworm-slim AS runtime

# Install runtime dependencies for llama.cpp
# - ca-certificates: for HTTPS connections
# - libgomp1: OpenMP runtime for parallel processing
# - libstdc++6: C++ standard library
# - libcurl4: for model downloads (if needed)
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    libgomp1 \
    libstdc++6 \
    libcurl4 \
    && rm -rf /var/lib/apt/lists/* \
    && apt-get clean

# Create non-root user for security
RUN groupadd -r scribe && useradd -r -g scribe scribe

WORKDIR /app

# Copy the Go agent binary from builder stage
COPY --from=builder /build/scribe-agent .

# Copy the AI runner from fetcher stage
COPY --from=ai-fetcher /ai/llama-runner .

# Create directory for AI models and set ownership
RUN mkdir -p /app/ai-models && chown -R scribe:scribe /app

# Environment variables with defaults
ENV SERVER_HOST=127.0.0.1:8000
ENV AGENT_NAME=docker-agent
ENV LOG_FILE=/var/log/syslog

# AI Runner configuration
ENV AI_RUNNER_PATH=/app/llama-runner
ENV AI_MODELS_DIR=/app/ai-models

# Create volume mount points
# - /var/log: for host log access
# - /app/ai-models: for persistent model storage
VOLUME ["/var/log", "/app/ai-models"]

# Switch to non-root user
USER scribe

# Health check (optional)
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD pgrep scribe-agent || exit 1

# Run the agent directly (not as a service)
ENTRYPOINT ["./scribe-agent"]
