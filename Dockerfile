# syntax=docker/dockerfile:1
FROM debian:bookworm-slim AS builder

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       build-essential git make gcc g++ libbluetooth-dev libboost-all-dev ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /opt
RUN git clone --depth 1 https://github.com/SBFspot/SBFspot.git
WORKDIR /opt/SBFspot/SBFspot
RUN make nosql && cp nosql/bin/SBFspot /tmp/SBFspot

FROM debian:bookworm-slim

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    CONFIG_DIR=/config \
    DATA_DIR=/data \
    WEB_PORT=8088

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       libbluetooth3 libboost-date-time1.74.0 libboost-system1.74.0 \
       bluez bluez-tools mosquitto-clients ca-certificates bash coreutils \
       grep sed gawk procps python3 python3-flask \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /tmp/SBFspot /usr/local/bin/SBFspot
COPY --from=builder /opt/SBFspot/SBFspot/date_time_zonespec.csv /date_time_zonespec.csv
COPY --from=builder /opt/SBFspot/SBFspot/date_time_zonespec.csv /usr/local/bin/date_time_zonespec.csv
COPY --from=builder /opt/SBFspot/SBFspot/TagList*.txt /
COPY --from=builder /opt/SBFspot/SBFspot/TagList*.txt /usr/local/bin/

WORKDIR /app
COPY app/ /app/
COPY web/static/ /web/static/
COPY config/SBFspot.cfg.example /config/SBFspot.cfg.example

RUN chmod +x /app/entrypoint.sh /app/healthcheck.sh /usr/local/bin/SBFspot

VOLUME ["/config", "/data"]
EXPOSE 8088

HEALTHCHECK --interval=60s --timeout=10s --start-period=60s --retries=3 CMD /app/healthcheck.sh
ENTRYPOINT ["/app/entrypoint.sh"]
