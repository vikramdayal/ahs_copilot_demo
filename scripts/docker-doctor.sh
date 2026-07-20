#!/usr/bin/env bash
set -euo pipefail

fail() {
  printf 'Docker readiness check failed: %s\n' "$1" >&2
  exit 1
}

command -v docker >/dev/null 2>&1 || fail "docker is not installed or not on PATH."
docker compose version >/dev/null 2>&1 || fail "Docker Compose v2 is unavailable."

if ! docker info >/dev/null 2>&1; then
  cat >&2 <<'MESSAGE'
Docker CLI is installed, but the Docker Engine is not reachable.
On macOS, start Docker Desktop and wait for it to report that the engine is running:

  open -a Docker

Then inspect the context and retry:

  docker context ls
  docker context use desktop-linux   # when that context exists
  unset DOCKER_HOST DOCKER_CONTEXT
  docker info
MESSAGE
  exit 1
fi

docker compose config --quiet
printf 'Docker Engine, Compose, and repository configuration are ready.\n'
