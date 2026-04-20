FROM mcr.microsoft.com/azurelinux/base/core:3.0

ARG RUNNER_VERSION=2.319.1
ARG TARGETARCH=x64

RUN tdnf -y update && tdnf -y install \
        ca-certificates \
        curl \
        tar \
        git \
        jq \
        icu \
        libunwind \
        openssl \
        sudo \
        python3 \
        python3-pip \
        nodejs \
    && tdnf clean all

RUN useradd -m -s /bin/bash runner && \
    echo "runner ALL=(ALL) NOPASSWD:ALL" > /etc/sudoers.d/runner

USER runner
WORKDIR /home/runner

RUN curl -fsSL -o actions-runner.tar.gz \
        https://github.com/actions/runner/releases/download/v${RUNNER_VERSION}/actions-runner-linux-${TARGETARCH}-${RUNNER_VERSION}.tar.gz \
    && tar xzf actions-runner.tar.gz \
    && rm actions-runner.tar.gz

COPY --chown=runner:runner entrypoint.sh /home/runner/entrypoint.sh
RUN chmod +x /home/runner/entrypoint.sh

ENTRYPOINT ["/home/runner/entrypoint.sh"]
