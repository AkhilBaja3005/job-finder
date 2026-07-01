# Build Stage for Frontend
FROM node:20-alpine AS frontend-builder
WORKDIR /app/frontend
COPY frontend/package*.json ./
RUN npm install
COPY frontend/ ./
RUN npm run build

# Final Stage for Backend + Frontend Serving
FROM python:3.11-slim
WORKDIR /app

# Install system dependencies for Tectonic compilation
RUN apt-get update && apt-get install -y \
    curl \
    git \
    libfontconfig1-dev \
    libgraphite2-dev \
    libharfbuzz-dev \
    libicu-dev \
    libssl-dev \
    zlib1g-dev \
    && rm -rf /var/lib/apt/lists/*

# Install Tectonic directly via the official static binary release url
# This bypasses the drop-sh redirect installer which can return HTML redirect walls in cloud IPs.
RUN curl -Lo tectonic.tar.gz https://github.com/tectonic-typesetting/tectonic/releases/download/tectonic%400.15.0/tectonic-0.15.0-x86_64-unknown-linux-musl.tar.gz \
    && tar -xzf tectonic.tar.gz \
    && mv tectonic /usr/local/bin/ \
    && rm tectonic.tar.gz

# Copy backend dependencies and install
COPY backend/requirements.txt ./backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt

# Install Playwright and let it fetch the exact browser packages and OS libraries natively
RUN playwright install chromium
RUN playwright install-deps chromium

# Copy frontend built assets
COPY --from=frontend-builder /app/frontend/dist ./frontend/dist

# Copy backend codebase
COPY backend/ ./backend/

WORKDIR /app/backend
EXPOSE 8000
CMD ["python", "main.py"]
