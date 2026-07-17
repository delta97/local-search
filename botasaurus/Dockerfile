FROM python:3.12-slim

# Chromium + runtime libs, and Xvfb for BOTASAURUS_HEADLESS=virtual (the
# driver starts the virtual display itself via pyvirtualdisplay).
RUN apt-get update && apt-get install -y --no-install-recommends \
    chromium \
    xvfb \
    curl \
    ca-certificates \
    libglib2.0-0 \
    libnss3 \
    libnspr4 \
    libdbus-1-3 \
    libatk1.0-0 \
    libatk-bridge2.0-0 \
    libcups2 \
    libdrm2 \
    libxkbcommon0 \
    libxcomposite1 \
    libxdamage1 \
    libxfixes3 \
    libxrandr2 \
    libgbm1 \
    libasound2 \
    && rm -rf /var/lib/apt/lists/*

ENV CHROME_EXECUTABLE_PATH=/usr/bin/chromium

WORKDIR /app

# botasaurus-driver pinned: its v4 CDP driver API is young (run_cdp_command
# takes typed cdp.* command objects; verified against this version).
RUN pip install --no-cache-dir \
    "botasaurus-driver==4.0.92" \
    pyvirtualdisplay \
    fastapi \
    "uvicorn[standard]"

COPY server.py .

EXPOSE 3000

CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "3000"]
