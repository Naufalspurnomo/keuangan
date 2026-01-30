# Use Python slim image
FROM python:3.11-slim-bookworm

# Set working directory
WORKDIR /app

# Install system dependencies for OpenCV
RUN apt-get update && apt-get install -y \
    libgl1 \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first (for caching)
COPY requirements.txt .

# Install Python dependencies (no more PyTorch/EasyOCR needed - using Groq Vision API)
RUN pip install --no-cache-dir -r requirements.txt

# NOTE: EasyOCR preload removed - now using Groq Vision API for OCR
# To re-enable EasyOCR, uncomment in requirements.txt and add:
# RUN pip install torch --index-url https://download.pytorch.org/whl/cpu
# RUN python -c "import easyocr; easyocr.Reader(['id', 'en'], gpu=False)"

# Copy application code
COPY . .

# Expose port
EXPOSE 8000

# Run the application
CMD ["gunicorn", "main:app", "--bind", "0.0.0.0:8000", "--workers", "1", "--threads", "2", "--timeout", "120"]
