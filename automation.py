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
file_handler = logging.FileHandler(config.LOG_FILE)
file_handler.setFormatter(log_formatter)
root_logger.addHandler(file_handler)

# Handler para consola (Para ver en Dokploy)
console_handler = logging.StreamHandler()
console_handler.setFormatter(log_formatter)
root_logger.addHandler(console_handler)

logging.getLogger("paramiko").setLevel(logging.WARNING)


def setup_directories():
    """Crea los directorios necesarios si no existen."""
    if not os.path.exists(config.DOWNLOAD_DIR):
        os.makedirs(config.DOWNLOAD_DIR)
    
    # Crear carpeta de reportes
    reports_dir = os.path.join(os.getcwd(), "reportes")
    if not os.path.exists(reports_dir):
        os.makedirs(reports_dir)
    return reports_dir

def connect_sftp():
    """Conecta al servidor SFTP y retorna el cliente."""
    try:
        transport = paramiko.Transport((config.FTP_HOST, config.FTP_PORT))
        transport.connect(username=config.FTP_USER, password=config.FTP_PASS)
        sftp = paramiko.SFTPClient.from_transport(transport)
        logging.info(f"Conectado exitosamente al SFTP: {config.FTP_HOST}")
        return sftp, transport
    except Exception as e:
        logging.warning(f"No se pudo conectar al SFTP ({e}). Continuaremos para prueba de navegador.")
        return None, None

def download_latest_file(sftp):
    """Descarga el archivo más reciente del directorio SFTP."""
    if not sftp:
        return None

    try:
        sftp.chdir(config.FTP_DIR)
        files = sftp.listdir_attr()
        
        # Filtramos para que sean solo archivos (no directorios)
        import stat
        files = [f for f in files if stat.S_ISREG(f.st_mode)]
        
        if not files:
            logging.warning("No se encontraron archivos en el directorio SFTP.")
            return None
        
        files.sort(key=lambda f: f.st_mtime)
        
        latest_file_attr = files[-1]
        latest_filename = latest_file_attr.filename
        
        # Opcional: Verificar si el archivo es reciente (eg. de hoy)
        # file_date = datetime.fromtimestamp(latest_file_attr.st_mtime)
        # logging.info(f"Archivo encontrado: {latest_filename} ({file_date})")

        logging.info(f"Archivo más reciente encontrado: {latest_filename}")
        
        local_path = os.path.join(config.DOWNLOAD_DIR, latest_filename)
        
        sftp.get(latest_filename, local_path)
        
        logging.info(f"Archivo descargado: {local_path}")
        return local_path
    except Exception as e:
        logging.error(f"Error descargando archivo: {e}")
        return None


def send_email_report(subject, body):
    """Envía un correo electrónico con el reporte."""
    if not config.ENABLE_EMAIL:
        return

    import smtplib
    from email.mime.text import MIMEText
    from email.mime.multipart import MIMEMultipart

    try:
        msg = MIMEMultipart()
        msg['From'] = config.EMAIL_SENDER
        msg['To'] = config.EMAIL_RECIPIENT
        msg['Subject'] = subject

        msg.attach(MIMEText(body, 'plain'))

        server = smtplib.SMTP(config.SMTP_SERVER, config.SMTP_PORT)
        server.starttls()
        server.login(config.EMAIL_SENDER, config.EMAIL_PASSWORD)
        text = msg.as_string()
        server.sendmail(config.EMAIL_SENDER, config.EMAIL_RECIPIENT.split(','), text)
        server.quit()
        logging.info(f"Correo enviado a {config.EMAIL_RECIPIENT}")
    except Exception as e:
        logging.error(f"Error enviando correo: {e}")

def save_report(text_content):
    """Guarda el resultado de la importación en un archivo de texto y lo envía por correo."""
    reports_dir = os.path.join(os.getcwd(), "reportes")
    filename = f"reporte_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
    filepath = os.path.join(reports_dir, filename)
    
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(f"REPORTE DE IMPORTACIÓN - {datetime.now()}\n")
        f.write("=========================================\n\n")
        f.write(text_content)
    
    logging.info(f"Reporte guardado en: {filepath}")
    
    # Enviar por correo
    subject = f"Reporte de subida de pago Efecty - {datetime.now().strftime('%Y-%m-%d %H:%M')}"
    
    intro_text = (
        "Hola equipo,\n\n"
        "Se ha ejecutado el proceso de carga automática de pagos de Efecty.\n"
        "A continuación, el detalle reportado por la plataforma WispHub:\n\n"
        "------------------------------------------------------------\n"
    )
    
    full_body = intro_text + text_content
    
    send_email_report(subject, full_body)

def upload_file_playwright(file_path):
    """
    Usa Playwright para loguearse en WispHub y subir el archivo.
    """
    if config.DRY_RUN:
        logging.info(f"[DRY_RUN] Iniciando simulación de subida para: {file_path}")
    
    logging.info("Iniciando Playwright...")
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=config.HEADLESS)
        context = browser.new_context()
        page = context.new_page()

        try:
            # 1. Login
            logging.info(f"Navegando al Login: {config.WISPHUB_LOGIN_URL}")
            page.goto(config.WISPHUB_LOGIN_URL)
            
            page.fill('input[name="username"], input[id*="user"], input[id*="login"]', config.WISPHUB_USER)
            page.fill('input[name="password"], input[id*="pass"]', config.WISPHUB_PASS)
            page.click('button[type="submit"], input[type="submit"]')
            
            logging.info("Credenciales enviadas. Esperando Dashboard...")
            try:
                page.wait_for_url("**/panel/**", timeout=25000)
                logging.info(f"Dashboard detectado: {page.url}")
            except:
                actual_url = page.url
                logging.warning(f"No se detectó /panel/ en URL. URL actual: {actual_url}")
                page.screenshot(path="debug_login_result.png")
                logging.info("Captura de pantalla de login guardada como debug_login_result.png")
                page.wait_for_load_state('domcontentloaded')

            # 2. Ir a Importación
            logging.info(f"Navegando a URL de Importación: {config.WISPHUB_IMPORT_URL}")
            page.goto(config.WISPHUB_IMPORT_URL)
            
            # 3. Subir Archivo
            logging.info(f"Adjuntando archivo: {file_path}")
            try:
                page.wait_for_selector('input[type="file"]', state='attached', timeout=20000)
            except Exception as e:
                logging.error(f"No se encontró el input de archivo. URL actual: {page.url}")
                page.screenshot(path="error_input_not_found.png")
                raise e
            
            page.set_input_files('input[type="file"]', file_path)
            logging.info("Archivo puesto en el input.")

            # 4. Confirmar Subida e Intentar Leer Respuesta
            if not config.DRY_RUN:
                 logging.info("Ejecutando subida real: Dando click en botón Importar/Subir...")
                 
                 # Intentamos varios selectores comunes para el botón de enviar en WispHub
                 try:
                     # Buscamos el botón por texto o por clase primaria de envío
                     page.click("button:has-text('Subir'), button:has-text('Importar'), button[type='submit'].btn-primary")
                     logging.info("Botón clickeado. Esperando respuesta del servidor...")
                 except Exception as click_error:
                     logging.warning(f"No se pudo dar click en el botón con los selectores estándar: {click_error}")

                 # ESPERA INTELIGENTE PARA RESULTADOS
                 logging.info("Esperando respuesta del sistema (máximo 30s)...")
                 page.wait_for_load_state('networkidle')
                 time.sleep(7) # Espera extra para que el mensaje de éxito aparezca

                 try:
                     # Intentamos ser específicos buscando alertas o mensajes de éxito/error
                     # .alert-success, .alert-danger son típicos de Django/Bootstrap que usa WispHub
                     alerts = page.locator(".alert, .alert-success, .alert-danger, .toastr, .swal2-content, #messages")
                     
                     if alerts.count() > 0:
                         result_text = ""
                         for i in range(alerts.count()):
                             result_text += alerts.nth(i).inner_text() + "\n"
                     else:
                         # Si no hay alertas específicas, buscamos el contenido principal
                         # Generalmente dentro de un contenedor .content o #content
                         content_main = page.locator(".content, #content, .container-fluid")
                         if content_main.count() > 0:
                             result_text = content_main.first.inner_text()
                         else:
                             result_text = page.inner_text("body")
                     
                     logging.info(f"Texto capturado (Resumen): {result_text[:300]}...") 
                     save_report(result_text)
                     
                 except Exception as scrape_error:
                     logging.error(f"No se pudo extraer texto del resultado: {scrape_error}")
                     send_email_report("WispHub: Error leyendo reporte", f"Se intentó subir el archivo pero falló la lectura del mensaje: {scrape_error}")

            
            else:
                logging.info("[DRY_RUN] Fin de la simulación. No se busca respuesta.")
                # En DRY_RUN no mandamos correo para no hacer spam, o podríamos descomentarlo:
                # save_report("Prueba de reporte en modo DRY RUN.")

        except Exception as e:
            logging.error(f"Error en Playwright: {e}")
            page.screenshot(path="error_screenshot.png")
            print(f"Ocurrió un error. Ver 'error_screenshot.png'")
            send_email_report("WispHub: Error Crítico", f"Ocurrió un error ejecutando el script:\n\n{str(e)}")
        finally:
            browser.close()

def run_automation_cycle():
    """Ejecuta un ciclo completo de la automatización."""
    print(f"\n--- Iniciando ciclo a las {datetime.now()} ---")
    setup_directories()
    
    # 1. Conexión SFTP y Descarga
    sftp, transport = connect_sftp()
    file_path = None
    
    if sftp:
        file_path = download_latest_file(sftp)
        sftp.close()
        transport.close()
    
    # 2. Subir a WispHub
    if file_path:
        upload_file_playwright(file_path)
    else:
        logging.warning("No se procesó ningún archivo en este ciclo (Fallo descarga o no hay archivos).")
    
    print(f"--- Ciclo finalizado a las {datetime.now()} ---")

def main():
    if config.ENABLE_LOOP:
        print(f"Modo Bucle ACTIVADO. Intervalo: {config.LOOP_INTERVAL_MINUTES} minutos.")
        while True:
            run_automation_cycle()
            
            wait_seconds = config.LOOP_INTERVAL_MINUTES * 60
            print(f"Esperando {config.LOOP_INTERVAL_MINUTES} minutos para la próxima ejecución...")
            try:
                time.sleep(wait_seconds)
            except KeyboardInterrupt:
                print("Ejecución detenida por el usuario.")
                break
    else:
        run_automation_cycle()

if __name__ == "__main__":
    main()
