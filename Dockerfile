FROM python:3.11-slim

# -------------------------------
# Install system dependencies
# -------------------------------
# libreoffice-writer : docx → pdf
# default-jre        : required by libreoffice
# dos2unix           : line ending safety
RUN apt-get update && apt-get install -y \
    libreoffice-writer \
    default-jre \
    dos2unix \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# -------------------------------
# Set working directory
# -------------------------------
WORKDIR /app

# -------------------------------
# Copy Python requirements
# -------------------------------
# requirements.txt MUST be at repo root
COPY requirements.txt /app/requirements.txt

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# -------------------------------
# Copy backend source code
# -------------------------------
COPY backend /app/backend

# -------------------------------
# Expose port
# -------------------------------
EXPOSE 8000

# -------------------------------
# Start FastAPI
# -------------------------------
CMD ["python", "-m", "uvicorn", "backend.app.main:app", "--host", "0.0.0.0", "--port", "8000"]