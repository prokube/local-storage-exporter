# Modified from uv-docker-example (https://github.com/astral-sh/uv-docker-example)

# First, build the application in the `/app` directory
FROM ghcr.io/astral-sh/uv:bookworm-slim@sha256:2597ffa44de9d160ca9ee2e1073728e6492af57b9abba5d909d6272d6e67df1f AS builder
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy

# Configure the Python directory so it is consistent
ENV UV_PYTHON_INSTALL_DIR=/python

# Only use the managed Python version
ENV UV_PYTHON_PREFERENCE=only-managed

# Install Python before the project for caching
RUN uv python install 3.13

WORKDIR /app
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --locked --no-install-project --no-dev

COPY . /app
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev

# Then, use a final image without uv
FROM debian:bookworm-slim@sha256:364d3f277f79b11fafee2f44e8198054486583d3392e2472eb656d5c780156f5

# Copy the Python version
COPY --from=builder --chown=python:python /python /python

# Copy the application from the builder
COPY --from=builder --chown=app:app /app /app

# Place executables in the environment at the front of the path
ENV PATH="/app/.venv/bin:$PATH"

WORKDIR /app
CMD ["python", "-m", "local_storage_exporter"]