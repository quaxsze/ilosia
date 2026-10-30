FROM node:22-bookworm-slim

ARG HERDR_VERSION=0.9.5
ARG CODEX_VERSION=0.165.0
ARG TARGETARCH

RUN apt-get update \
    && apt-get install --yes --no-install-recommends \
        ca-certificates curl g++ gcc git jq make openssh-server pkg-config \
        python3 python3-venv ripgrep tini \
    && rm -rf /var/lib/apt/lists/* \
    && npm install --global "@openai/codex@${CODEX_VERSION}" \
    && case "$TARGETARCH" in \
        amd64) herdr_arch=x86_64 ;; \
        arm64) herdr_arch=aarch64 ;; \
        *) echo "Unsupported architecture: $TARGETARCH" >&2; exit 1 ;; \
       esac \
    && curl --fail --location --silent --show-error \
        --output /usr/local/bin/herdr \
        "https://github.com/herdrdev/herdr/releases/download/v${HERDR_VERSION}/herdr-linux-${herdr_arch}" \
    && chmod 0755 /usr/local/bin/herdr \
    && groupmod --new-name developer node \
    && usermod --login developer --home /workspace/home --shell /bin/bash node \
    && usermod --password x developer \
    && mkdir -p /workspace/home /workspace/repository /workspace/ssh-host-keys \
    && chown -R 1000:1000 /workspace

COPY sshd_config /etc/ssh/sshd_config_aw0
COPY entrypoint.sh /usr/local/bin/aw0-entrypoint

RUN chmod 0755 /usr/local/bin/aw0-entrypoint

ENV HOME=/workspace/home
WORKDIR /workspace/repository
USER 1000:1000

EXPOSE 2222
ENTRYPOINT ["/usr/bin/tini", "--", "/usr/local/bin/aw0-entrypoint"]
