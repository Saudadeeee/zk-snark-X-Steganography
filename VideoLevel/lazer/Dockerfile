# Research container for the exact LaZer reproduction revision in LAZER.lock.json.
# Runtime is intentionally blocked by src.lazer_backend unless the host exposes
# Linux x86-64 with AVX-512F and AES.  Docker emulation cannot supply AVX-512.
FROM ubuntu:24.04

ARG DEBIAN_FRONTEND=noninteractive
ARG LAZER_REPOSITORY=https://github.com/lazer-crypto/lazer.git
ARG LAZER_REVISION=10eafeca4cd53ff4fc54193dce904dbd0026fefd

RUN apt-get update && apt-get install --yes --no-install-recommends \
    ca-certificates git make cmake gcc-13 g++-13 python3 python3-dev python3-cffi \
    sagemath libgmp-dev && \
    rm -rf /var/lib/apt/lists/*

RUN git clone "${LAZER_REPOSITORY}" /opt/lazer && \
    git -C /opt/lazer checkout --detach "${LAZER_REVISION}" && \
    git -C /opt/lazer submodule update --init --recursive

ENV CC=gcc-13
ENV CXX=g++-13
RUN make -C /opt/lazer all && \
    make -C /opt/lazer/python && \
    make -C /opt/lazer/python/demo

WORKDIR /opt/lazer/python/demo
CMD ["python3", "demo.py"]
