FROM python:3.12-slim

RUN pip install --no-cache-dir fastapi uvicorn

WORKDIR /services
CMD ["uvicorn", "orchestration_api:app", "--host", "0.0.0.0", "--port", "8080"]
