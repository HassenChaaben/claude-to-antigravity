# Claude2Antigravity (Community edition) as a container.
#   docker run --rm -v ~/.claude:/root/.claude -v ~/.claude.json:/root/.claude.json \
#     -v ~/.gemini:/root/.gemini -v ~/.claude2antigravity:/root/.claude2antigravity \
#     ghcr.io/hassenchaaben/claude2antigravity sync
FROM python:3.12-slim
LABEL org.opencontainers.image.source="https://github.com/HassenChaaben/claude-to-antigravity" \
      org.opencontainers.image.description="Bring your Claude Code skills, plugins, agents, MCP servers and conversations into Google Antigravity." \
      org.opencontainers.image.licenses="MIT"
WORKDIR /src
COPY pyproject.toml README.md LICENSE ./
COPY skills ./skills
RUN pip install --no-cache-dir . && rm -rf /src
WORKDIR /root
ENTRYPOINT ["claude2agy"]
CMD ["--help"]
