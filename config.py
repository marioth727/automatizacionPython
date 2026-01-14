# Configuración para la Automatización de Pagos WispHub
import os

# ==========================================
# CONFIGURACIÓN DE ENTORNO (Dokploy / Local)
# ==========================================
# La función getenv intenta leer de las Variables de Entorno de Dokploy.
# Si no encuentra nada, usa los valores por defecto (Tu configuración local).

# ==========================================
# CREDENCIALES SFTP
# ==========================================
FTP_HOST = os.getenv("FTP_HOST", "mft.efecty.com.co")
FTP_USER = os.getenv("FTP_USER", "eft112578")
FTP_PASS = os.getenv("FTP_PASS", "E6R4D5D9")
FTP_PORT = int(os.getenv("FTP_PORT", 22))
FTP_DIR  = os.getenv("FTP_DIR", "/Salida")
FTP_DIR_ENTRY = os.getenv("FTP_DIR_ENTRY", "/Entrada")

# ==========================================
# CREDENCIALES WISPHUB
# ==========================================
WISPHUB_USER = os.getenv("WISPHUB_USER", "admin@rapilink-sas")
WISPHUB_PASS = os.getenv("WISPHUB_PASS", "Soporte2025aTx$")
WISPHUB_LOGIN_URL = "https://wisphub.io/accounts/login/?next=/panel/"
WISPHUB_IMPORT_URL = "https://wisphub.io/efecty-v2/subir-archivo/" 
WISPHUB_DOWNLOAD_URL = "https://wisphub.io/efecty-v2/descargar/"

# ==========================================
# CONFIGURACIÓN GENERAL
# ==========================================
DOWNLOAD_DIR = os.path.join(os.getcwd(), "downloads")
LOG_FILE = "automation.log"
# En Dokploy, queremos que DRY_RUN sea False (Producción) por defecto, o controlarlo via variable.
# Convertimos el string "False" o "True" de env var a booleano
_dry = os.getenv("DRY_RUN", "True") 
DRY_RUN = _dry.lower() == "true" 

HEADLESS = True # En VPS/Docker SIEMPRE debe ser True (no hay pantalla)

# ==========================================
# CONFIGURACIÓN DE AUTOMATIZACIÓN (LOOP)
# ==========================================
ENABLE_LOOP = True
LOOP_INTERVAL_MINUTES = int(os.getenv("LOOP_INTERVAL_MINUTES", 60))
SECONDARY_INTERVAL_MINUTES = int(os.getenv("SECONDARY_INTERVAL_MINUTES", 5))
SYNC_INTERVAL_MINUTES = int(os.getenv("SYNC_INTERVAL_MINUTES", 10))
TASK_DELAY_SECONDS = int(os.getenv("TASK_DELAY_SECONDS", 120))

# ==========================================
# CONFIGURACIÓN DE CORREO
# ==========================================
ENABLE_EMAIL = True
SMTP_SERVER = "smtp.gmail.com"  
SMTP_PORT = 587                 
EMAIL_SENDER = os.getenv("EMAIL_SENDER", "reporte.rapilink@gmail.com")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD", "nnsy qdkx ijor luwr")
EMAIL_RECIPIENT = os.getenv("EMAIL_RECIPIENT", "info.rapilinksas@gmail.com, gestiondecartera.rapilinksas@gmail.com")




