# Use Node 20 LTS and Python 3.10 on a modern Debian version
FROM nikolaik/python-nodejs:python3.10-nodejs20

# Install system dependencies
# We combine these to keep the image size small
RUN apt-get update && \
    apt-get install -y --no-install-recommends ffmpeg aria2 && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# Set the working directory
WORKDIR /app

# Copy the application code
COPY . /app/

# Upgrade pip and install Python dependencies
# Combined into one RUN command to reduce layers
RUN python3 -m pip install --no-cache-dir --upgrade pip && \
    pip3 install --no-cache-dir --upgrade -r requirements.txt

# Start the application
CMD ["python3", "-m", "VIPMUSIC"]
