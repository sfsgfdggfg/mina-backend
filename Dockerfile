FROM python:3.12.1-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

COPY requirements-lock.txt /app/requirements-lock.txt
RUN python -m pip install --no-cache-dir -r /app/requirements-lock.txt

COPY . /app

CMD ["python", "-m", "src.cloud_pilot_launcher"]
