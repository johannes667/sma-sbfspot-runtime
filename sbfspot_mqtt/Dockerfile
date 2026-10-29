# syntax=docker/dockerfile:1
FROM debian:bookworm-slim AS builder
ARG SBFSPOT_REF=b77f65047e9f4a136a09677838f6b4e5024862ee
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential git ca-certificates libbluetooth-dev \
    libboost-date-time-dev libboost-system-dev \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /src
RUN --mount=type=secret,id=proxy_ca \
    if [ -f /run/secrets/proxy_ca ]; then export GIT_SSL_CAINFO=/run/secrets/proxy_ca; fi; \
    git init && git remote add origin https://github.com/SBFspot/SBFspot.git \
    && git fetch --depth 1 origin "$SBFSPOT_REF" && git checkout --detach FETCH_HEAD
COPY sbfspot-valid-values.patch /src/valid-values.patch
RUN git apply --check valid-values.patch && git apply valid-values.patch
RUN make -C SBFspot nosql && strip SBFspot/nosql/bin/SBFspot

FROM debian:bookworm-slim
RUN apt-get update && apt-get install -y --no-install-recommends \
    libbluetooth3 libboost-date-time1.74.0 libboost-system1.74.0 \
    python3 python3-paho-mqtt ca-certificates tzdata \
    && rm -rf /var/lib/apt/lists/*
COPY --from=builder /src/SBFspot/nosql/bin/SBFspot /usr/local/bin/SBFspot
COPY --from=builder /src/SBFspot/date_time_zonespec.csv /usr/local/bin/
COPY --from=builder /src/SBFspot/TagListEN-US.txt /usr/local/bin/
COPY --from=builder /src/SBFspot/SBFspot.cfg /usr/local/share/SBFspot.default.cfg
COPY --from=builder /src/license.md /usr/local/share/SBFspot.LICENSE
COPY bridge.py /app/bridge.py
WORKDIR /usr/local/bin
ENTRYPOINT ["python3", "-I", "-u", "-B", "/app/bridge.py"]
