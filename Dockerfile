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

# Install system dependencies for Playwright and Tectonic
RUN apt-get update && apt-get install -y \
    curl \
    git \
    libgconf-2-4 \
    libatk1.0-0 \
    libatk-bridge2.0-0 \
    libgdk-pixbuf2.0-0 \
    libgtk-3-0 \
    libgbm-dev \
    libnss3 \
    libxss1 \
    libasound2 \
    && rm -rf /var/lib/apt/lists/*

# Install Tectonic (LaTeX engine)
RUN curl --proto '=https' --tlsv1.2 -sSf https://drop-sh.fullyjustified.net | sh \
    && mv tectonic /usr/local/bin/

# Copy backend dependencies and install
COPY backend/requirements.txt ./backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt
RUN playwright install chromium
RUN playwright install-deps chromium

# Copy frontend built assets
COPY --from=frontend-builder /app/frontend/dist ./frontend/dist

# Copy backend codebase
COPY backend/ ./backend/

WORKDIR /app/backend
EXPOSE 8000
CMD ["python", "main.py"]
