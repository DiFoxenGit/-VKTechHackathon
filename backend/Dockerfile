FROM python:3.11-slim
RUN apt-get update && apt-get install -y --no-install-recommends \
      libreoffice-impress fonts-dejavu-core fonts-liberation fontconfig \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
COPY designer ./designer
COPY designer/assets/fonts/*.ttf /usr/share/fonts/truetype/designer/
RUN fc-cache -f
RUN useradd --create-home designer && mkdir /data && chown designer:designer /data
USER designer
ENV DESIGNER_DATA_DIR=/data PYTHONUNBUFFERED=1
EXPOSE 8000
CMD ["uvicorn", "designer.server:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
