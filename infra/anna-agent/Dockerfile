# Run the Anna agent in a container, so Gamentic can run with the Anna agent
# (the hackathon "fit with Anna" requirement). Vendor's documented install + run.
FROM python:3.11-slim

# Pin the release for reproducible builds.
ARG ANNA_VERSION=1.1.0-beta.17
ARG ANNA_URL=https://releases.anna.partners/releases/production/${ANNA_VERSION}/Anna-${ANNA_VERSION}-linux-x86_64.tar.gz
ARG ANNA_SHA256=c56896ffd7c5a9ec585b0103f01bdc379c1cfe49a97c8b211d957056383f2c5d

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Run as a normal user, not root. /data is the agent's writable home; creating it
# here (owned by the user) means the named volume inherits that ownership on first mount.
RUN useradd --create-home --uid 10001 anna \
    && mkdir -p /data \
    && chown anna:anna /data

# Install the agent into /opt/anna (download, checksum, unpack).
WORKDIR /opt/anna
RUN curl -fsSL "${ANNA_URL}" -o /tmp/anna.tar.gz \
    && echo "${ANNA_SHA256}  /tmp/anna.tar.gz" | sha256sum -c - \
    && tar -xzf /tmp/anna.tar.gz --strip-components=1 -C /opt/anna \
    && rm /tmp/anna.tar.gz \
    && chmod +x /opt/anna/Anna \
    && chown -R anna:anna /opt/anna

USER anna
ENV HOME=/data
WORKDIR /opt/anna

# The agent serves its own local API (uvicorn/fastapi).
ENTRYPOINT ["/opt/anna/Anna"]
