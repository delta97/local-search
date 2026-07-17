FROM python:3.12-slim

# Firefox runtime libraries + Xvfb for Camoufox's 'virtual' headless mode
RUN apt-get update && apt-get install -y --no-install-recommends \
    xvfb \
    libgtk-3-0 \
    libx11-xcb1 \
    libxt6 \
    libasound2 \
    libdbus-glib-1-2 \
    libxtst6 \
    libxrandr2 \
    libpci3 \
    libegl1 \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
RUN pip install --no-cache-dir "camoufox[geoip]" fastapi "uvicorn[standard]"

# Download the Camoufox browser binary at build time
RUN python -m camoufox fetch

COPY server.py .

EXPOSE 3000
CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "3000"]
