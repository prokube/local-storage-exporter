FROM ghcr.io/astral-sh/uv:0.9.15-python3.10-bookworm-slim@sha256:ecef6db674d075cf4705d416b5c75733eebfe46f6f36bbd4188f174ab45f738d AS builder

COPY . /app
WORKDIR /app

# Install Python in builder stage and copy to final image to maintain consistent Debian base
ENV UV_PYTHON_INSTALL_DIR=/python
RUN uv python install 3.13
RUN uv sync --locked --no-dev # It will create a virtual environment in /app/.venv

FROM debian:bookworm-slim@sha256:b4aa902587c2e61ce789849cb54c332b0400fe27b1ee33af4669e1f7e7c3e22f

COPY --from=builder /python /python
COPY --from=builder /app /app
WORKDIR /app

ENV PATH="/app/.venv/bin:$PATH"

CMD ["python", "-m", "local_storage_exporter"]