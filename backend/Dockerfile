FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y \
    gcc \
    default-libmysqlclient-dev \
    pkg-config \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# ?? IMPORTANTE: copiar código aqui
COPY . .

EXPOSE 8000

# CMD ["python", "manage.py", "runserver", "0.0.0.0:8000"]

# CMD ["sh", "-c", "sleep 10 && python manage.py runserver 0.0.0.0:8000"]
CMD ["sh", "-c", "sleep 15 && python manage.py runserver 0.0.0.0:8000"]
