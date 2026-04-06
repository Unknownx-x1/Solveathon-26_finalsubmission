FROM python:3.10-slim

# Install system dependencies (needed for OpenCV, PostgreSQL, easyocr, etc)
RUN apt-get update && apt-get install -y \
    libgl1-mesa-glx \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# Set up a non-root user (Hugging Face runs Docker Spaces as user 1000)
RUN useradd -m -u 1000 user
USER user

# Set environment variables for the user
ENV HOME=/home/user \
    PATH=/home/user/.local/bin:$PATH \
    PORT=7860 \
    FLASK_ENV=production

# Set working directory to the user's home
WORKDIR $HOME/app

# Copy requirements file and install dependencies
COPY --chown=user:user requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt || pip install --no-cache-dir -r requirements.txt

# Pre-download easyocr models (optional, but speeds up first load)
# RUN python -c "import easyocr; easyocr.Reader(['en'])"

# Copy the rest of the application
COPY --chown=user:user . .

# Make port 7860 available to the world outside this container
EXPOSE 7860

# Run the application using gunicorn
CMD ["gunicorn", "--bind", "0.0.0.0:7860", "--workers", "2", "--timeout", "120", "app:app"]
