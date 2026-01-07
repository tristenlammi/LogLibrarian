# Scribe Binaries

This directory contains pre-built Scribe agent binaries that are served via the `/api/download/{filename}` endpoint.

## Built by CI

During GitHub Actions CI/CD, the Scribe Go code is compiled for multiple platforms:

- `scribe-linux-amd64` - Linux x86_64
- `scribe-linux-arm64` - Linux ARM64 (Raspberry Pi 4, etc.)
- `scribe-windows-amd64.exe` - Windows x86_64

These binaries are automatically copied into the backend Docker image.

## Local Development

For local development with `docker compose build`, you need to build the binaries manually:

```bash
cd ../scribe
GOOS=linux GOARCH=amd64 go build -o ../librarian/scribe-bin/scribe-linux-amd64 .
GOOS=windows GOARCH=amd64 go build -o ../librarian/scribe-bin/scribe-windows-amd64.exe .
```

Or use the build script:

```bash
cd ../scribe
./build-all.sh
cp bin/* ../librarian/scribe-bin/
```
