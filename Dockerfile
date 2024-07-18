# Stage 1: Install dependencies
FROM python:3.11-slim AS builder

WORKDIR /app

COPY requirements.txt .

# Install dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Remove unnecessary files from installed packages
RUN find /usr/local/lib/python3.11/site-packages/ -name "*.pyc" -delete
RUN find /usr/local/lib/python3.11/site-packages/ -name "__pycache__" -delete

# Stage 2: Build the final image
FROM python:3.11-slim

WORKDIR /app

COPY --from=builder /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# Copy your application code
COPY . .

# Expose the port and define the command to run your app
EXPOSE 8000
CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000"]
