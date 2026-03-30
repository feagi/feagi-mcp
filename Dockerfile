FROM python:3.11-slim

WORKDIR /app

COPY pyproject.toml .
COPY README.md .
COPY LICENSE .
COPY src/ ./src/

RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir .

ENV FEAGI_HOST=localhost
ENV FEAGI_PORT=8000

EXPOSE 8000

CMD ["python", "-m", "feagi_mcp.server"]
