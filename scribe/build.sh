#!/bin/bash

# Build script for LogLibrarian Scribe Agent
# Cross-compiles for Windows, Linux, and macOS

set -e

echo "Building LogLibrarian Scribe Agent..."

# Create bin directory
mkdir -p bin

# Windows (AMD64)
echo "Building for Windows (AMD64)..."
GOOS=windows GOARCH=amd64 go build -o bin/scribe.exe .
echo "✓ bin/scribe.exe"

# Linux (AMD64)
echo "Building for Linux (AMD64)..."
GOOS=linux GOARCH=amd64 go build -o bin/scribe-linux .
chmod +x bin/scribe-linux
echo "✓ bin/scribe-linux"

# macOS Intel (AMD64)
echo "Building for macOS Intel (AMD64)..."
GOOS=darwin GOARCH=amd64 go build -o bin/scribe-mac-intel .
chmod +x bin/scribe-mac-intel
echo "✓ bin/scribe-mac-intel"

# macOS ARM (M1/M2)
echo "Building for macOS ARM (M1/M2)..."
GOOS=darwin GOARCH=arm64 go build -o bin/scribe-mac-arm .
chmod +x bin/scribe-mac-arm
echo "✓ bin/scribe-mac-arm"

echo ""
echo "Build complete! Binaries available in bin/"
ls -lh bin/
