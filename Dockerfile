FROM python:3.13-slim
WORKDIR /app
COPY requirements.lock .
RUN pip install --no-cache-dir -r requirements.lock
COPY pyproject.toml .
COPY src ./src
RUN pip install --no-cache-dir --no-deps . && useradd --uid 10001 --create-home ledger \
    && mkdir /app/data && chown ledger:ledger /app/data
USER ledger
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health')" || exit 1
CMD ["clearledger", "--host", "0.0.0.0"]
