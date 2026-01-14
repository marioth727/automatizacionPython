# Usamos la versión EXACTA que pide el error para evitar fallos de ejecución
FROM mcr.microsoft.com/playwright/python:v1.57.0-jammy



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
