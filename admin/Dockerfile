FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1
WORKDIR /app

COPY app.py ./app.py
COPY static ./static

EXPOSE 8090
CMD ["python", "/app/app.py"]
