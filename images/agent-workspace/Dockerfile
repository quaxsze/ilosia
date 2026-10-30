FROM ghcr.io/astral-sh/uv:0.13.6 AS uv
FROM ghcr.io/jdx/mise:2026.10.4 AS mise
FROM node:26.13.0-bookworm-slim

ARG HERDR_VERSION=0.9.5
ARG CODEX_VERSION=0.165.0
ARG TARGETARCH

COPY --from=uv /uv /uvx /usr/local/bin/
COPY --from=mise /usr/local/bin/mise /usr/local/bin/mise

RUN apt-get update \
    && apt-get install --yes --no-install-recommends \
        bash build-essential ca-certificates curl file git jq less libatomic1 \
        openssh-server pkg-config procps python3 python3-dev python3-venv \
        ripgrep rsync tini unzip xz-utils \
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
    && chown -R 1000:1000 /workspace \
    && herdr --version \
    && codex --version \
    && uv --version \
    && mise --version

COPY sshd_config /etc/ssh/sshd_config_ilosia
COPY entrypoint.sh /usr/local/bin/ilosia-workspace-entrypoint
COPY clone-repository.sh /usr/local/bin/clone-repository

RUN chmod 0755 /usr/local/bin/ilosia-workspace-entrypoint \
        /usr/local/bin/clone-repository

ENV HOME=/workspace/home \
    SHELL=/bin/bash \
    NPM_CONFIG_PREFIX=/workspace/home/.local \
    UV_CACHE_DIR=/workspace/home/.cache/uv \
    UV_TOOL_BIN_DIR=/workspace/home/.local/bin \
    MISE_DATA_DIR=/workspace/home/.local/share/mise \
    MISE_CONFIG_DIR=/workspace/home/.config/mise \
    MISE_CACHE_DIR=/workspace/home/.cache/mise \
    PATH=/workspace/home/.local/bin:/workspace/home/.local/share/mise/shims:/usr/local/bin:/usr/bin:/bin

WORKDIR /workspace/repository
USER 1000:1000

EXPOSE 2222
ENTRYPOINT ["/usr/bin/tini", "--", "/usr/local/bin/ilosia-workspace-entrypoint"]
