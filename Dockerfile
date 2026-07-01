# Build Stage for Frontend
FROM node:20-alpine AS frontend-builder
WORKDIR /app/frontend
COPY frontend/package*.json ./
RUN npm install
COPY frontend/ ./
RUN npm run build

# Final Stage for Backend + Frontend Serving (matching python:3.11-slim)
FROM python:3.11-slim
WORKDIR /app

# Install system dependencies for Tectonic and base dependencies
# Note: Playwright browser dependencies are installed natively using 'playwright install-deps'
RUN apt-get update && apt-get install -y \
    curl \
    git \
    && rm -rf /var/lib/apt/lists/*

# Install Tectonic (LaTeX engine)
RUN curl --proto '=https' --tlsv1.2 -sSf https://drop-sh.fullyjustified.net | sh \
    && mv tectonic /usr/local/bin/

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
