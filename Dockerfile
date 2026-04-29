# Dockerfile - Judge AI API
FROM python:3.11-slim

WORKDIR /app

ARG SKIPPED_MTG_PAGES
ARG VITE_POSTHOG_KEY
ARG VITE_POSTHOG_HOST

ENV VITE_POSTHOG_KEY=$VITE_POSTHOG_KEY
ENV VITE_POSTHOG_HOST=$VITE_POSTHOG_HOST
ENV SKIPPED_MTG_PAGES=$SKIPPED_MTG_PAGES

# Dépendances système pour psycopg2
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev gcc \
    && rm -rf /var/lib/apt/lists/*

# Copier et installer les dépendances
COPY requirements.txt requirements_auth.txt ./
RUN pip install --no-cache-dir -r requirements.txt -r requirements_auth.txt

# Copier le code source
COPY . .

# Port FastAPI
EXPOSE 8000

# Lancer l'API
CMD ["uvicorn", "api:app", "--host", "0.0.0.0", "--port", "8000"]