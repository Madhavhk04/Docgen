FROM python:3.11-slim

# Install system dependencies
# libreoffice-writer: for docx -> pdf
# default-jre: java runtime needed for libreoffice
# dos2unix: ensure script is in LF format
RUN apt-get update && apt-get install -y \
    libreoffice-writer \
    default-jre \
    dos2unix \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy Frontend
COPY frontend /app/frontend

# Copy Backend
COPY backend /app/backend

# Copy Startup Script
COPY startup.sh /app/startup.sh

# Fix line endings and permissions
RUN dos2unix /app/startup.sh && chmod +x /app/startup.sh

# Set working directory to backend so paths are relative as expected
WORKDIR /app/backend


# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt


# Expose port (Documentation only, Azure uses WEBSITES_PORT)
EXPOSE 8000



# Run the application via startup script
CMD ["/app/startup.sh"]
