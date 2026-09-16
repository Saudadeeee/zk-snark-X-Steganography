# Research container for the exact LaZer reproduction revision in LAZER.lock.json.
# Runtime is intentionally blocked by src.lazer_backend unless the host exposes
# Linux x86-64 with AVX-512F and AES.  Docker emulation cannot supply AVX-512.
FROM ubuntu@sha256:69cecf4bbf72d2d44a9eef1b71fb98c7fb973d78af11399deccef19beb008ad9

ARG DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install --yes --no-install-recommends \
    ca-certificates git make cmake gcc-13 g++-13 python3 python3-dev python3-cffi \
    sagemath libgmp-dev && \
    rm -rf /var/lib/apt/lists/*

RUN git clone "https://github.com/lazer-crypto/lazer.git" /opt/lazer && \
    git -C /opt/lazer checkout --detach "10eafeca4cd53ff4fc54193dce904dbd0026fefd" && \
    test "$(git -C /opt/lazer rev-parse HEAD)" = "10eafeca4cd53ff4fc54193dce904dbd0026fefd" && \
    git -C /opt/lazer submodule update --init --recursive

ENV CC=gcc-13
ENV CXX=g++-13
RUN make -C /opt/lazer all && \
    make -C /opt/lazer/python && \
    make -C /opt/lazer/python/demo

WORKDIR /opt/lazer/python/demo
CMD ["python3", "demo.py"]
