FROM mcr.microsoft.com/playwright/python:v1.46.0-jammy

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copiar o restante do código
COPY . .

# Expor a porta que o Render vai usar
EXPOSE 8080

# Comando para iniciar o bot
CMD ["python", "bot.py"]
