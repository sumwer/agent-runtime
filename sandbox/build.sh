#!/usr/bin/env bash
set -euo pipefail
docker build --network "${SANDBOX_BUILD_NETWORK:-default}" \
  --build-arg HTTP_PROXY --build-arg HTTPS_PROXY \
  --build-arg "PIP_INDEX_URL=${SANDBOX_PIP_INDEX_URL:-https://pypi.org/simple}" \
  -t agent-runtime-sandbox:latest "$(dirname "$0")"
