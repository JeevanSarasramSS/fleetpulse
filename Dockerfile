# One image, several roles (api / processor / simulator / batch / seed): smaller supply chain, one scan.
FROM python:3.11-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY fleetpulse ./fleetpulse
COPY web ./web
COPY db ./db
RUN python -m fleetpulse.ml.train > /dev/null && useradd -u 10001 -m app && chown -R app /app
USER 10001
EXPOSE 8000
CMD ["uvicorn", "fleetpulse.api.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
