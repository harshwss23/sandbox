# Generated file. Edits are overwritten: the inputs are packages.txt
# and blocked_domains.txt.
# Domain profile: AI/ML/Computer Vision/Computational Statistics
FROM python:3.12-slim-bookworm@sha256:4766d8b510c428e595d74b9cc5bbb2fae8e26316fffb4adc89908d79aacd58a2

COPY .flc/flc-install-packages .flc/flc-block-domains /usr/local/bin/
RUN chmod +x /usr/local/bin/flc-install-packages /usr/local/bin/flc-block-domains

# The test runner, installed separately from packages.txt.
RUN pip3 install --no-cache-dir pytest==8.4.2 \
 || pip3 install --no-cache-dir --break-system-packages pytest==8.4.2

COPY .flc/packages.txt /tmp/flc-packages.txt
RUN flc-install-packages /tmp/flc-packages.txt

COPY .flc/blocked_domains.txt /tmp/flc-blocked-domains.txt
RUN flc-block-domains /tmp/flc-blocked-domains.txt

COPY workspace/ /workspace/
WORKDIR /workspace
