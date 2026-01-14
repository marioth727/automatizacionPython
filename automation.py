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
    """Descarga el archivo más reciente del directorio SFTP."""
    try:
        sftp.chdir(config.FTP_DIR)
        files = sftp.listdir_attr()
        
        # Filtrar solo archivos y ordenar por fecha de modificación
        files = [f for f in files if not f.filename.startswith(".")]
        if not files:
            logging.info("No se encontraron archivos en el servidor SFTP.")
            return None
        
        latest_file = max(files, key=lambda f: f.st_mtime)
        remote_path = latest_file.filename
        local_path = os.path.join("downloads", latest_file.filename)
        
        logging.info(f"Descargando archivo más reciente: {remote_path}")
        sftp.get(remote_path, local_path)
        logging.info(f"Archivo descargado: {local_path}")
        return local_path
    except Exception as e:
        logging.error(f"Error descargando archivo: {e}")
        return None

def send_email_report(subject, body):
    """Envía un correo electrónico con el reporte."""
    import smtplib
    from email.mime.text import MIMEText
    from email.mime.multipart import MIMEMultipart

    try:
        msg = MIMEMultipart()
        msg['From'] = config.EMAIL_SENDER
        msg['To'] = config.EMAIL_RECIPIENT
        msg['Subject'] = subject

        msg.attach(MIMEText(body, 'plain'))

        with smtplib.SMTP("smtp.gmail.com", 587) as server:
            server.starttls()
            server.login(config.EMAIL_SENDER, config.EMAIL_PASSWORD)
            server.send_message(msg)
            
        logging.info("Correo enviado exitosamente.")
    except Exception as e:
        logging.error(f"Fallo al enviar correo: {e}")

def save_report(text_content):
    """Guarda el resultado de la importación en un archivo de texto y lo envía por correo."""
    filename = f"reportes/reporte_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
    try:
        with open(filename, "w", encoding="utf-8") as f:
            f.write(text_content)
        logging.info(f"Reporte guardado localmente: {filename}")
    except Exception as e:
        logging.error(f"Error guardando reporte: {e}")
    
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
    Usa Playwright para loguearse en WispHub, subir el archivo y manejar el proceso multi-paso.
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
                 
                 try:
                     # Clic en el botón inicial de Importar/Subir
                     page.click("button:has-text('Subir'), button:has-text('Importar'), button[type='submit'].btn-primary")
                     logging.info("Botón clickeado. Esperando página de selección...")
                 except Exception as click_error:
                     logging.warning(f"No se pudo dar click inicial: {click_error}")

                 user_names = []
                 # MANEJO DEL PASO 2 (Elegir Clientes)
                 try:
                     logging.info("Esperando carga del Paso 2 (Selección de Clientes)...")
                     
                     # Selectores para detectar que estamos en la página de selección
                     txt_instruccion = "text='Por favor, indique a que clientes se actualizaran los datos'"
                     btn_final = "button:has-text('Registrar Pago y Activar Servicio')"
                     check_all = "input[type='checkbox'].check-all, #check_all, table thead input[type='checkbox']"

                     # Esperamos a que aparezca la instrucción o el botón azul
                     try:
                         page.wait_for_selector(f"{txt_instruccion}, {btn_final}", timeout=25000)
                         logging.info("Página de selección detectada!")
                     except:
                         logging.info("No se detectaron elementos clave rápido, revisando conteo manual...")

                     # Si vemos el botón azul o el título, procedemos
                     if page.locator(btn_final).count() > 0 or page.locator("h3:has-text('Elegir Clientes')").count() > 0:
                         logging.info("Confirmado: Paso 2 Activo. Raspando nombres...")
                         
                         rows = page.locator("table tbody tr")
                         count = rows.count()
                         for i in range(count):
                             try:
                                 # El nombre suele estar en la 2da columna
                                 row_tds = rows.nth(i).locator("td")
                                 if row_tds.count() >= 2:
                                     name = row_tds.nth(1).inner_text().strip()
                                     # Si es muy corto, probamos la 3ra columna
                                     if len(name) < 3 and row_tds.count() >= 3:
                                         name = row_tds.nth(2).inner_text().strip()
                                     
                                     if name and len(name) > 2:
                                         user_names.append(name.replace('\n', ' '))
                             except:
                                 continue
                         
                         logging.info(f"Usuarios encontrados: {user_names}")
                         
                         # Seleccionar todos
                         if page.locator(check_all).count() > 0:
                             logging.info("Marcando checkbox global...")
                             page.locator(check_all).first.click()
                         else:
                             logging.info("Marcando checkboxes individuales...")
                             checks = page.locator("table tbody input[type='checkbox']")
                             for i in range(checks.count()):
                                 checks.nth(i).check()

                         # Click FINAL
                         logging.info("Haciendo clic en 'Registrar Pago y Activar Servicio'...")
                         page.click(btn_final)
                         
                         # Esperar a que la página procese
                         logging.info("Esperando confirmación final tras activación...")
                         page.wait_for_load_state('networkidle')
                         time.sleep(10) # 10 segundos para estar seguros
                     else:
                         logging.info("No se detectó pantalla de selección. Procesamiento directo.")

                 except Exception as step2_err:
                     logging.warning(f"Error en el Paso 2: {step2_err}")
                     page.screenshot(path="debug_step2_error.png")

                 # REPORTE FINAL CONSOLIDADO
                 logging.info("Generando reporte para el correo...")
                 try:
                     # Prioridad a las alertas de Bootstrap que usa WispHub
                     alerts = page.locator(".alert, .alert-success, .alert-danger, #messages")
                     
                     final_msg = ""
                     if alerts.count() > 0:
                         for i in range(alerts.count()):
                             msg = alerts.nth(i).inner_text().strip()
                             if msg:
                                 final_msg += f"{msg}\n"
                     
                     if len(final_msg) < 5:
                         container = page.locator(".content, #content, .container-fluid, #container")
                         final_msg = container.first.inner_text() if container.count() > 0 else page.inner_text("body")

                     # Armar reporte
                     report_body = ""
                     if user_names:
                         report_body += "RESUMEN DE PROCESAMIENTO:\n"
                         for name in user_names:
                             report_body += f"✅ {name}\n"
                         report_body += "\n"
                     
                     report_body += "DETALLES DE WISPHUB:\n" + ("-"*30) + "\n" + final_msg
                     
                     logging.info("Reporte consolidado listo.") 
                     save_report(report_body)
                     
                 except Exception as scrape_err:
                     logging.error(f"Error leyendo resultado final: {scrape_err}")
                     send_email_report("WispHub: Error de Lectura", f"El proceso terminó pero no pude leer el mensaje final: {scrape_err}")
            
            else:
                logging.info("[DRY_RUN] Fin de la simulación.")

        except Exception as e:
            logging.error(f"Error en Playwright: {e}")
            page.screenshot(path="error_screenshot.png")
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
        print(f"Modo Bucle ACTIVADO.")
        print(f"Configuración: Ejecutar -> Esperar {config.SECONDARY_INTERVAL_MINUTES} min -> Ejecutar -> Esperar {config.LOOP_INTERVAL_MINUTES} min.")
        
        while True:
            # --- CARRERA 1 ---
            logging.info(">>> INICIANDO CARRERA 1 de 2")
            run_automation_cycle()
            
            # --- ESPERA INTERMEDIA ---
            wait_sec_1 = config.SECONDARY_INTERVAL_MINUTES * 60
            logging.info(f"Carrera 1 terminada. Esperando {config.SECONDARY_INTERVAL_MINUTES} min para Carrera 2...")
            try:
                time.sleep(wait_sec_1)
            except KeyboardInterrupt:
                break
                
            # --- CARRERA 2 ---
            logging.info(">>> INICIANDO CARRERA 2 de 2")
            run_automation_cycle()
            
            # --- ESPERA LARGA ---
            wait_sec_2 = config.LOOP_INTERVAL_MINUTES * 60
            logging.info(f"Carrera 2 terminada. Esperando {config.LOOP_INTERVAL_MINUTES} min para el próximo ciclo...")
            try:
                time.sleep(wait_sec_2)
            except KeyboardInterrupt:
                break
    else:
        run_automation_cycle()

if __name__ == "__main__":
    main()
