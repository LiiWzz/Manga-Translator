FROM python:3.11-slim
RUN apt-get update && apt-get install -y --no-install-recommends \
    tesseract-ocr fonts-noto-core && rm -rf /var/lib/apt/lists/*
RUN groupadd -r app && useradd -r -g app -m app
WORKDIR /app
COPY pyproject.toml ./
COPY app ./app
RUN pip install --no-cache-dir . && mkdir -p /home/app/.config/manga-translator && \
    chown -R app:app /home/app/.config
USER app
EXPOSE 8000
CMD ["uvicorn","app.main:app","--host","0.0.0.0","--port","8000","--no-access-log"]
