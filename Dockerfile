FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Most PaaS providers (Railway, Render, Fly.io) inject $PORT at runtime.
ENV PORT=3000
EXPOSE 3000

CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT}"]
