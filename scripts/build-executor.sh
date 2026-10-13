#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
docker build -f docker/Dockerfile -t paper2code-executor:local .
docker image inspect paper2code-executor:local --format '{{.Id}} {{.Os}}/{{.Architecture}}'
