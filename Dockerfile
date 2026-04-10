# Usa uma imagem oficial do Python, leve e rápida
FROM python:3.10-slim

# Define a pasta de trabalho lá no servidor do Google
WORKDIR /app

# Copia os arquivos da sua máquina para o servidor
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Roda a API usando o Gunicorn (Pronto para produção)
CMD exec gunicorn --bind :$PORT --workers 1 --threads 8 --timeout 0 app:app