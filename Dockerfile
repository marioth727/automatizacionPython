# Usamos la imagen oficial de Playwright para Python (incluye navegadores)
FROM mcr.microsoft.com/playwright/python:v1.49.1-jammy

# Directorio de trabajo
WORKDIR /app

# Copiar archivos de requerimientos e instalar dependencias de Python
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copiar el resto del código
COPY . .

# Variables de entorno por defecto (Docker)
ENV PYTHONUNBUFFERED=1

# Comando de inicio
CMD ["python", "automation.py"]
