FROM ghcr.io/astral-sh/uv:0.9.15-python3.14-bookworm-slim@sha256:f11ed962eaf229411ca2082a9d3200fdf23d4ca546e18a307fb55138a4a4817d  AS builder

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