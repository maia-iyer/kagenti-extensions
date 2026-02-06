# Use minimal Python base image
FROM python:3.12-slim

# UID/GID for non-root user (keep in sync with container_builder.go ClientRegistrationUID/GID)
ARG UID=1000
ARG GID=1000

# Create non-root user
RUN groupadd -g ${GID} appuser && useradd -u ${UID} -g appuser appuser

# Set work directory
WORKDIR /app

# Copy your script
COPY client_registration.py .

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Ensure non-root user owns application directory
RUN chown -R ${UID}:${GID} /app

# Switch to non-root user
USER ${UID}:${GID}

# Register client
CMD ["python", "client_registration.py"]