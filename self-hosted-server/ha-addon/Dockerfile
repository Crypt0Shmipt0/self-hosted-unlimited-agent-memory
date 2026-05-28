ARG BUILD_FROM
FROM chromadb/chroma:1.5.9

ENV ANONYMIZED_TELEMETRY=FALSE

EXPOSE 8000

LABEL \
    io.hass.version="1.5.9" \
    io.hass.type="addon" \
    io.hass.arch="amd64|aarch64"

# Bypass the upstream image's entrypoint (which hard-codes /data) so that
# the persistent data lands in /share/ — survives add-on rebuilds and is
# captured by HA backups when the user configures include_folders=["share"].
ENTRYPOINT ["chroma", "run", "--host", "0.0.0.0", "--port", "8000", "--path", "/share/personal-memory-server"]
CMD []
