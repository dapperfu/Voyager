.PHONY: build run smoke clean help

build:
	docker compose build

run:
	docker compose up

smoke:
	SMOKE=1 docker compose up --abort-on-container-exit --exit-code-from voyager

clean:
	docker compose down

help:
	@echo "build  Build the Voyager image"
	@echo "run    Start the NeoForge server and Voyager"
	@echo "smoke  Join the server and print one observation"
	@echo "clean  Stop the compose project and keep the world volume"
