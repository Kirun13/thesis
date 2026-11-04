FROM thesis-response:local
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends tshark tcpdump mosquitto mosquitto-clients \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY . /app/online
