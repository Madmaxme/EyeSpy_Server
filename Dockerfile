FROM python:3.9-slim

WORKDIR /app

# Copy requirements first for better layer caching
COPY requirements.txt .

# Install dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Install additional dependencies
RUN pip install psycopg2-binary google-cloud-storage

# Install OpenAI for bio generation
RUN pip install openai

# Install Gunicorn for production serving
RUN pip install gunicorn

# Copy the rest of the application
COPY . /app/

# Make startup script executable
RUN chmod +x /app/startup.sh

# Expose the port the app runs on
EXPOSE 8080

# Use the startup script to run the application
CMD ["/app/startup.sh"]