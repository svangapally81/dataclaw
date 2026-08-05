FROM python:3.12-slim

RUN pip install --no-cache-dir dagster==1.8.0 dagster-webserver==1.8.0

WORKDIR /tmp
CMD ["dagster", "dev", "-h", "0.0.0.0", "-p", "8080", "-f", "/services/dagster_app.py"]
