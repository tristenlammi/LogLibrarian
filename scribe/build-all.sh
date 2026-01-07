#!/bin/bash

# Scribe Agent - Quick Start Script
# Builds cross-platform binaries

set -e

echo "Building Scribe Agent for multiple platforms..."
echo ""

# Create dist directory
mkdir -p dist

# Linux AMD64
echo "Building for Linux AMD64..."
GOOS=linux GOARCH=amd64 go build -ldflags="-s -w" -o dist/scribe-agent-linux-amd64 .
echo "✓ dist/scribe-agent-linux-amd64"

# Linux ARM64
echo "Building for Linux ARM64..."
GOOS=linux GOARCH=arm64 go build -ldflags="-s -w" -o dist/scribe-agent-linux-arm64 .
echo "✓ dist/scribe-agent-linux-arm64"

# Windows AMD64
echo "Building for Windows AMD64..."
GOOS=windows GOARCH=amd64 go build -ldflags="-s -w" -o dist/scribe-agent-windows-amd64.exe .
echo "✓ dist/scribe-agent-windows-amd64.exe"

# macOS AMD64
echo "Building for macOS AMD64..."
GOOS=darwin GOARCH=amd64 go build -ldflags="-s -w" -o dist/scribe-agent-darwin-amd64 .
echo "✓ dist/scribe-agent-darwin-amd64"

# macOS ARM64 (Apple Silicon)
echo "Building for macOS ARM64..."
GOOS=darwin GOARCH=arm64 go build -ldflags="-s -w" -o dist/scribe-agent-darwin-arm64 .
echo "✓ dist/scribe-agent-darwin-arm64"

echo ""
echo "Build complete! Binaries are in dist/"
echo ""
echo "File sizes:"
ls -lh dist/

echo ""
echo "To install:"
echo "  Linux:   ./install-linux.sh"
echo "  Windows: ./install-windows.ps1"
