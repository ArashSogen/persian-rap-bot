FROM python:3.11-slim

# Install system dependencies: ffmpeg for audio processing, yt-dlp dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy requirements and install Python deps
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Create data directories for persistence
RUN mkdir -p data downloads

# Expose health check port
EXPOSE 8080

# Run with gunicorn
CMD ["gunicorn", "bot:app", "--bind", "0.0.0.0:8080", "--workers", "1", "--threads", "8", "--timeout", "120"]
