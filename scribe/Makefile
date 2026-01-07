.PHONY: all clean windows linux macos-intel macos-arm

# Binary output directory
BIN_DIR = bin

# Build all platforms
all: windows linux macos-intel macos-arm

# Clean build artifacts
clean:
	rm -rf $(BIN_DIR)

# Create bin directory
$(BIN_DIR):
	mkdir -p $(BIN_DIR)

# Windows build (AMD64)
windows: $(BIN_DIR)
	GOOS=windows GOARCH=amd64 go build -o $(BIN_DIR)/scribe.exe .
	@echo "Built: $(BIN_DIR)/scribe.exe"

# Linux build (AMD64)
linux: $(BIN_DIR)
	GOOS=linux GOARCH=amd64 go build -o $(BIN_DIR)/scribe-linux .
	@echo "Built: $(BIN_DIR)/scribe-linux"

# macOS Intel build (AMD64)
macos-intel: $(BIN_DIR)
	GOOS=darwin GOARCH=amd64 go build -o $(BIN_DIR)/scribe-mac-intel .
	@echo "Built: $(BIN_DIR)/scribe-mac-intel"

# macOS ARM build (M1/M2)
macos-arm: $(BIN_DIR)
	GOOS=darwin GOARCH=arm64 go build -o $(BIN_DIR)/scribe-mac-arm .
	@echo "Built: $(BIN_DIR)/scribe-mac-arm"

# Local build (current platform)
local: $(BIN_DIR)
	go build -o $(BIN_DIR)/scribe .
	@echo "Built: $(BIN_DIR)/scribe"
