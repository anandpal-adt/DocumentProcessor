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
<<<<<<< HEAD



# # Single stage Dockerfile

FROM python:3.9-alpine

WORKDIR /app

# Copy the entire application directory into the container
COPY . .

# Install Python dependencies
RUN pip install --no-cache-dir --no-deps -r requirements.txt \
    && pip install uvicorn

EXPOSE 8000    
# Command to run the application
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
=======
>>>>>>> 753e3009d8b3f3c208f37f53db225420a13394c7
