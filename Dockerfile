# Stage 1: Build the application
FROM python:3.13-slim AS build-stage

WORKDIR /app

COPY requirements.txt requirements.txt
RUN python -m venv ./venv
# activate venv
ENV PATH="/app/venv/bin:$PATH"  
RUN pip install --no-cache-dir -r requirements.txt

# Stage 2: Run the application
FROM python:3.13-slim

WORKDIR /app

COPY --from=build-stage /app .
COPY . .
# activate venv
ENV PATH="/app/venv/bin:$PATH"

CMD ["python", "local_storage_exporter.py"]
