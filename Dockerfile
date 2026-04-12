# Étape 1 : Build
FROM python:3.11-slim AS build
WORKDIR /app
COPY . .
RUN pip install -r requirements.txt
