import os
import logging
import time
import paramiko
from datetime import datetime
import config

# Playwright Imports
from playwright.sync_api import sync_playwright

# Configuración de Logging Dual (Consola + Archivo)
log_formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
root_logger = logging.getLogger()
root_logger.setLevel(logging.INFO)

# Handler para archivo
file_handler = logging.FileHandler("automation.log")
file_handler.setFormatter(log_formatter)
root_logger.addHandler(file_handler)

# Handler para consola (Para ver en Dokploy)
console_handler = logging.StreamHandler()
console_handler.setFormatter(log_formatter)
root_logger.addHandler(console_handler)

logging.getLogger("paramiko").setLevel(logging.WARNING)

def setup_directories():
    """Crea los directorios necesarios si no existen."""
    for directory in ["downloads", "reportes"]:
        if not os.path.exists(directory):
            os.makedirs(directory)
            logging.info(f"Directorio creado: {directory}")

def connect_sftp():
    """Conecta al servidor SFTP y retorna el cliente."""
    try:
        transport = paramiko.Transport((config.FTP_HOST, config.FTP_PORT))
        transport.connect(username=config.FTP_USER, password=config.FTP_PASS)
        sftp = paramiko.SFTPClient.from_transport(transport)
        logging.info(f"Conectado a SFTP: {config.FTP_HOST}")
        return sftp, transport
    except Exception as e:
        logging.error(f"Error conectando a SFTP: {e}")
        return None, None

def download_latest_file(sftp):
    """Descarga el archivo más reciente del directorio SFTP (/Salida)."""
    try:
        sftp.chdir(config.FTP_DIR)
        files = sftp.listdir_attr()
        
        files = [f for f in files if not f.filename.startswith(".")]
        if not files:
            logging.info("No se encontraron archivos en /Salida.")
            return None
        
        latest_file = max(files, key=lambda f: f.st_mtime)
        remote_path = latest_file.filename
        local_path = os.path.join("downloads", latest_file.filename)
        
        logging.info(f"Descargando de /Salida: {remote_path}")
        sftp.get(remote_path, local_path)
        return local_path
    except Exception as e:
        logging.error(f"Error descargando archivo de /Salida: {e}")
        return None

def upload_database_sftp(local_path):
    """Sube el archivo de base de datos extraído de WispHub al SFTP (/Entrada)."""
    sftp, transport = connect_sftp()
    if not sftp:
        return False
    try:
        sftp.chdir(config.FTP_DIR_ENTRY)
        remote_filename = os.path.basename(local_path)
        logging.info(f"Subiendo DB a SFTP: {remote_filename} en {config.FTP_DIR_ENTRY}")
        sftp.put(local_path, remote_filename)
        logging.info("Subida a SFTP (/Entrada) exitosa.")
        return True
    except Exception as e:
        logging.error(f"Error subiendo DB a SFTP: {e}")
        return False
    finally:
        sftp.close()
        transport.close()

def send_email_report(subject, body):
    """Envía un correo electrónico con el reporte."""
    if not config.ENABLE_EMAIL: return
    import smtplib
    from email.mime.text import MIMEText
    from email.mime.multipart import MIMEMultipart
    try:
        msg = MIMEMultipart()
        msg['From'] = config.EMAIL_SENDER
        msg['To'] = config.EMAIL_RECIPIENT
        msg['Subject'] = subject
        msg.attach(MIMEText(body, 'plain'))
        with smtplib.SMTP(config.SMTP_SERVER, config.SMTP_PORT) as server:
            server.starttls()
            server.login(config.EMAIL_SENDER, config.EMAIL_PASSWORD)
            server.send_message(msg)
        logging.info("Correo enviado exitosamente.")
    except Exception as e:
        logging.error(f"Fallo al enviar correo: {e}")

def save_report(text_content):
    """Guarda el reporte local y lo envía por correo."""
    filename = f"reportes/reporte_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
    try:
        with open(filename, "w", encoding="utf-8") as f:
            f.write(text_content)
    except: pass
    
    subject = f"Reporte Automatización - {datetime.now().strftime('%Y-%m-%d %H:%M')}"
    intro = "Detalle del robot:\n------------------------------------------------------------\n"
    send_email_report(subject, intro + text_content)

def download_database_wisphub(page):
    """Descarga el reporte TXT de facturas de WispHub."""
    logging.info(f"Accediendo a descarga de base de datos: {config.WISPHUB_DOWNLOAD_URL}")
    try:
        with page.expect_download(timeout=60000) as download_info:
            page.goto(config.WISPHUB_DOWNLOAD_URL)
        download = download_info.value
        timestamp = datetime.now().strftime("%Y%m%d_%H%M")
        local_path = os.path.join("downloads", f"BASE_WISPHUB_{timestamp}.txt")
        download.save_as(local_path)
        return local_path
    except Exception as e:
        logging.error(f"Error en descarga WispHub: {e}")
        return None

def upload_file_playwright(file_path):
    """Sube el archivo de pagos y gestiona la activación."""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=config.HEADLESS)
        page = browser.new_page()
        try:
            # 1. Login
            page.goto(config.WISPHUB_LOGIN_URL)
            page.fill('input[name="username"]', config.WISPHUB_USER)
            page.fill('input[name="password"]', config.WISPHUB_PASS)
            page.click('button[type="submit"]')
            page.wait_for_url("**/panel/**", timeout=20000)

            # 2. Upload
            page.goto(config.WISPHUB_IMPORT_URL)
            page.set_input_files('input[type="file"]', file_path)
            page.click("button:has-text('Subir'), button:has-text('Importar')")

            # 3. Paso 2 (Elegir Clientes)
            user_names = []
            try:
                page.wait_for_selector("text='Por favor, indique a que clientes', button:has-text('Registrar Pago')", timeout=20000)
                if page.locator("button:has-text('Registrar Pago')").count() > 0:
                    logging.info("Paso 2 detected. Activating users...")
                    rows = page.locator("table tbody tr")
                    for i in range(rows.count()):
                        try:
                            td_name = rows.nth(i).locator("td").nth(1).inner_text().strip()
                            if td_name and len(td_name) > 2: user_names.append(td_name)
                        except: continue
                    
                    check_all = "input[type='checkbox'].check-all, #check_all, table thead input[type='checkbox']"
                    if page.locator(check_all).count() > 0: page.locator(check_all).first.click()
                    page.click("button:has-text('Registrar Pago')")
                    page.wait_for_load_state('networkidle')
                    time.sleep(10)
            except: pass

            # 4. Reporte
            alerts = page.locator(".alert, .alert-success, .alert-danger, #messages")
            msg = ""
            if alerts.count() > 0:
                for i in range(alerts.count()): msg += alerts.nth(i).inner_text().strip() + "\n"
            else:
                msg = page.locator(".content").first.inner_text() if page.locator(".content").count() > 0 else "Procesado."

            report = ""
            if user_names:
                report += "PROCESADOS:\n" + "\n".join([f"✅ {n}" for n in user_names]) + "\n\n"
            report += "RESULTADO:\n" + msg
            save_report(report)
        finally:
            browser.close()

def cycle_payments(reason="Programado"):
    """Tarea 1: Descarga SFTP /Salida -> WispHub."""
    logging.info(f"--- Iniciando Ciclo Pagos ({reason}) ---")
    setup_directories()
    sftp, transport = connect_sftp()
    if sftp:
        file_path = download_latest_file(sftp)
        sftp.close()
        transport.close()
        if file_path:
            if not config.DRY_RUN: upload_file_playwright(file_path)
            else: logging.info("[DRY_RUN] No se sube nada.")
        else:
            logging.info("No hay archivos nuevos en /Salida.")

def cycle_reverse_sync():
    """Tarea 2: WispHub DB -> SFTP /Entrada."""
    logging.info("--- Iniciando Ciclo Sincronización (WispHub -> /Entrada) ---")
    setup_directories()
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=config.HEADLESS)
        page = browser.new_page()
        try:
            # Login
            page.goto(config.WISPHUB_LOGIN_URL)
            page.fill('input[name="username"]', config.WISPHUB_USER)
            page.fill('input[name="password"]', config.WISPHUB_PASS)
            page.click('button[type="submit"]')
            page.wait_for_url("**/panel/**", timeout=20000)

            # Descarga
            db_file = download_database_wisphub(page)
            if db_file:
                upload_database_sftp(db_file)
        finally:
            browser.close()

def main():
    if not config.ENABLE_LOOP:
        cycle_payments("Ejecución única")
        cycle_reverse_sync()
        return

    # Tiempos de última ejecución (Unix timestamps)
    last_sync = 0
    last_payment_primary = 0
    secondary_due = False

    logging.info(f"Planificador iniciado. Sync: {config.SYNC_INTERVAL_MINUTES}m | Pagos: {config.LOOP_INTERVAL_MINUTES}m + {config.SECONDARY_INTERVAL_MINUTES}m")

    while True:
        now = time.time()

        # 1. Sincronización Inversa (Cada 5 min)
        if now - last_sync >= (config.SYNC_INTERVAL_MINUTES * 60):
            cycle_reverse_sync()
            last_sync = time.time()

        # 2. Ciclo de Pagos (Primario - Cada 65 min)
        if now - last_payment_primary >= (config.LOOP_INTERVAL_MINUTES * 60):
            cycle_payments("Carrera 1 de 2")
            last_payment_primary = time.time()
            secondary_due = True

        # 3. Ciclo de Pagos (Secundario - 2 min después del Primario)
        if secondary_due and (now - last_payment_primary >= (config.SECONDARY_INTERVAL_MINUTES * 60)):
            cycle_payments("Carrera 2 de 2")
            secondary_due = False

        time.sleep(10) # Revisión cada 10 segundos

if __name__ == "__main__":
    main()
