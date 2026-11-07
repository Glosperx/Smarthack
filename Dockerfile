# Multi-stage full-stack Dockerfile for Smarthack
# Stage 1: Build React frontend
FROM node:22-slim AS web
WORKDIR /web
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# Stage 2: Serve Python FastAPI application with bundled frontend
FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml ./
COPY smarthack ./smarthack
RUN pip install --no-cache-dir .
COPY --from=web /web/dist /app/frontend_dist
ENV SMARTHACK_FRONTEND_DIST=/app/frontend_dist \
    SMARTHACK_HOST=0.0.0.0
EXPOSE 8000
CMD ["python", "-m", "smarthack"]
