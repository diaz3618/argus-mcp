BINARY   := argusd
MODULE   := github.com/diaz3618/argus-mcp/packages/argusd
CMD      := ./cmd/argusd

VERSION  := $(shell git describe --tags --always --dirty 2>/dev/null || echo dev)
LDFLAGS  := -s -w -X main.version=$(VERSION)

# Default target builds for the current platform
.PHONY: build
build:
	go build -ldflags "$(LDFLAGS)" -o $(BINARY) $(CMD)

# Run locally
.PHONY: run
run: build
	./$(BINARY) $(ARGS)

# Cross-compilation targets
.PHONY: build-all
build-all: build-linux-amd64 build-linux-arm64 build-darwin-amd64 build-darwin-arm64

.PHONY: build-linux-amd64
build-linux-amd64:
	GOOS=linux GOARCH=amd64 go build -ldflags "$(LDFLAGS)" -o dist/$(BINARY)-linux-amd64 $(CMD)

.PHONY: build-linux-arm64
build-linux-arm64:
	GOOS=linux GOARCH=arm64 go build -ldflags "$(LDFLAGS)" -o dist/$(BINARY)-linux-arm64 $(CMD)

.PHONY: build-darwin-amd64
build-darwin-amd64:
	GOOS=darwin GOARCH=amd64 go build -ldflags "$(LDFLAGS)" -o dist/$(BINARY)-darwin-amd64 $(CMD)

.PHONY: build-darwin-arm64
build-darwin-arm64:
	GOOS=darwin GOARCH=arm64 go build -ldflags "$(LDFLAGS)" -o dist/$(BINARY)-darwin-arm64 $(CMD)

# Tidy and verify
.PHONY: tidy
tidy:
	go mod tidy

.PHONY: vet
vet:
	go vet ./...

.PHONY: test
test:
	go test -v -race ./...

.PHONY: lint
lint:
	golangci-lint run ./...

.PHONY: clean
clean:
	rm -f $(BINARY)
	rm -rf dist/

.PHONY: fmt
fmt:
	gofmt -w .
