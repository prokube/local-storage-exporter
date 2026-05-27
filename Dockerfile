FROM ghcr.io/astral-sh/uv:0.11.16-python3.14-trixie-slim@sha256:14fbf3734501e0d9179b68c952445c03fe46787ed8d6a5bb3143dcf59fef2093 AS builder

COPY . /app
WORKDIR /app

# Install Python in builder stage and copy to final image to maintain consistent Debian base
ENV UV_PYTHON_INSTALL_DIR=/python
RUN uv python install 3.14
RUN uv sync --locked --no-dev # It will create a virtual environment in /app/.venv

FROM debian:trixie-slim@sha256:b6e2a152f22a40ff69d92cb397223c906017e1391a73c952b588e51af8883bf8

COPY --from=builder /python /python
COPY --from=builder /app /app
WORKDIR /app

ENV PATH="/app/.venv/bin:$PATH"

CMD ["python", "-m", "local_storage_exporter"]
