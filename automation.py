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
    """Conecta al servidor SFTP y retorna el cliente con timeout."""
    for attempt in range(config.FTP_MAX_RETRIES):
        transport = None
        try:
            # Crear socket con timeout
            import socket
            sock = socket.create_connection((config.FTP_HOST, config.FTP_PORT), timeout=config.FTP_TIMEOUT)
            
            transport = paramiko.Transport(sock)
            transport.connect(username=config.FTP_USER, password=config.FTP_PASS)
            sftp = paramiko.SFTPClient.from_transport(transport)
            logging.info(f"Conectado a SFTP: {config.FTP_HOST}")
            return sftp, transport
        except Exception as e:
            logging.error(f"Error conectando a SFTP (intento {attempt + 1}/{config.FTP_MAX_RETRIES}): {e}")
            if transport: transport.close()
            if attempt < config.FTP_MAX_RETRIES - 1:
                time.sleep(5) # Esperar antes de reintentar
    return None, None

def download_latest_file(sftp):
    """Descarga el archivo más reciente del directorio SFTP (/Salida) con reintentos."""
    for attempt in range(config.FTP_MAX_RETRIES):
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
            
            logging.info(f"Descargando de /Salida: {remote_path} (Intento {attempt + 1}/{config.FTP_MAX_RETRIES})")
            sftp.get(remote_path, local_path)
            return local_path
        except Exception as e:
            logging.error(f"Error en descarga SFTP (Intento {attempt + 1}/{config.FTP_MAX_RETRIES}): {e}")
            if attempt < config.FTP_MAX_RETRIES - 1:
                time.sleep(5)
            else:
                return None

def upload_database_sftp(local_path):
    """Sube el archivo de base de datos extraído de WispHub al SFTP (/Entrada) con reintentos."""
    for attempt in range(config.FTP_MAX_RETRIES):
        sftp, transport = connect_sftp()
        if not sftp:
            if attempt < config.FTP_MAX_RETRIES - 1:
                time.sleep(5)
                continue
            return False
            
        try:
            sftp.chdir(config.FTP_DIR_ENTRY)
            remote_filename = os.path.basename(local_path)
            logging.info(f"Subiendo DB a SFTP: {remote_filename} en {config.FTP_DIR_ENTRY} (Intento {attempt + 1})")
            sftp.put(local_path, remote_filename)
            logging.info("Subida a SFTP (/Entrada) exitosa.")
            return True
        except Exception as e:
            logging.error(f"Error subiendo DB a SFTP (Intento {attempt + 1}/{config.FTP_MAX_RETRIES}): {e}")
            if attempt < config.FTP_MAX_RETRIES - 1:
                time.sleep(5)
            else:
                return False
        finally:
            if sftp: sftp.close()
            if transport: transport.close()

def send_email_report(subject, body, attachment_paths=None):
    """Envía un correo electrónico con el reporte y adjuntos opcionales (lista)."""
    if not config.ENABLE_EMAIL: return
    import smtplib
    from email.mime.text import MIMEText
    from email.mime.multipart import MIMEMultipart
    from email.mime.application import MIMEApplication
    try:
        msg = MIMEMultipart()
        msg['From'] = config.EMAIL_SENDER
        msg['To'] = config.EMAIL_RECIPIENT
        msg['Subject'] = subject
        msg.attach(MIMEText(body, 'plain'))

        # Manejar múltiples adjuntos
        if attachment_paths:
            # Asegurar que sea una lista
            if isinstance(attachment_paths, str):
                attachment_paths = [attachment_paths]
            
            for path in attachment_paths:
                if os.path.exists(path):
                    with open(path, "rb") as f:
                        part = MIMEApplication(f.read(), Name=os.path.basename(path))
                    part['Content-Disposition'] = f'attachment; filename="{os.path.basename(path)}"'
                    msg.attach(part)
                    logging.info(f"Archivo adjuntado al correo: {path}")

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
    
    subject = f"Reporte de subida de pago Efecty - {datetime.now().strftime('%Y-%m-%d %H:%M')}"
    intro = "Detalle del robot:\n------------------------------------------------------------\n"
    send_email_report(subject, intro + text_content)

def download_database_wisphub(page):
    """Descarga el reporte TXT de facturas de WispHub."""
    logging.info(f"Accediendo a descarga de base de datos: {config.WISPHUB_DOWNLOAD_URL}")
    try:
        # Iniciamos la escucha de la descarga
        with page.expect_download(timeout=60000) as download_info:
            try:
                # goto lanzará error si el link es una descarga directa ("Download is starting")
                # Lo capturamos y simplemente permitimos que el with continue
                page.goto(config.WISPHUB_DOWNLOAD_URL)
            except Exception as e:
                if "Download is starting" in str(e):
                    logging.info("La descarga inició correctamente (Mensaje de navegación omitido).")
                else:
                    raise e
                    
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
            # 1. Login con selectores robustos y tiempo extendido (90s para Cloudflare)
            logging.info("Navegando al Login...")
            page.goto(config.WISPHUB_LOGIN_URL, timeout=90000)
            
            page.fill('input[name="username"], input[id*="user"], input[id*="login"]', config.WISPHUB_USER)
            page.fill('input[name="password"], input[id*="pass"]', config.WISPHUB_PASS)
            page.click('button[type="submit"], input[type="submit"]')
            
            # WispHub a veces tiene Cloudflare o es lento redirigiendo
            logging.info("Esperando acceso al Dashboard...")
            try:
                page.wait_for_url("**/panel/**", timeout=45000)
            except Exception as url_err:
                # Si falla por URL, verificamos si hay elementos del panel presentes
                if page.locator(".sidebar, .navbar, a[href*='logout']").count() > 0:
                    logging.info("Dashboard detectado por elementos visuales (URL no cambió a tiempo).")
                else:
                    page.screenshot(path="fallo_login_vps.png")
                    raise url_err

            # 2. Upload
            page.goto(config.WISPHUB_IMPORT_URL)
            page.set_input_files('input[type="file"]', file_path)
            page.click("button:has-text('Subir'), button:has-text('Importar')")

            # 3. Paso 2 (Elegir Clientes)
            user_names = []
            try:
                logging.info("Esperando detección de Paso 2 (Elegir Clientes)...")
                # Mayor tolerancia y selectores separados para mejor diagnóstico
                btn_confirmar_text = "Registrar Pago y Activar Servicio"
                
                # Esperamos que cargue la tabla o el texto indicativo
                try:
                    page.wait_for_selector("text='Por favor, indique a que clientes'", timeout=30000)
                    logging.info("Texto de Paso 2 detectado.")
                except:
                    logging.warning("No se detectó el texto esperado del Paso 2, procediendo a buscar el botón.")

                # Buscar el botón por texto exacto o parcial
                btn_registrar = page.get_by_role("button", name=btn_confirmar_text)
                
                if btn_registrar.count() > 0:
                    logging.info("Botón de activación detectado.")
                    
                    # Raspado de nombres para el reporte
                    rows = page.locator("table tbody tr")
                    count = rows.count()
                    logging.info(f"Se encontraron {count} filas en la tabla de pagos.")
                    
                    for i in range(count):
                        try:
                            td_name = rows.nth(i).locator("td").nth(1).inner_text().strip()
                            if td_name and len(td_name) > 2: 
                                user_names.append(td_name)
                        except Exception as e:
                            logging.warning(f"Error raspando nombre en fila {i}: {e}")
                            continue
                    
                    logging.info(f"Clientes detectados: {user_names}")
                    
                    # Marcar todos los clientes
                    check_all = "input[type='checkbox'].check-all, #check_all, table thead input[type='checkbox']"
                    if page.locator(check_all).count() > 0:
                        logging.info("Marcando checkbox 'Seleccionar Todos'.")
                        page.locator(check_all).first.click()
                    else:
                        logging.warning("No se encontró checkbox general, intentando marcar individuales...")
                        checkboxes = page.locator("table tbody input[type='checkbox']")
                        for j in range(checkboxes.count()):
                            checkboxes.nth(j).check()

                    # Clic final
                    logging.info(f"Haciendo clic en '{btn_confirmar_text}'...")
                    btn_registrar.first.click()
                    
                    # Esperar procesamiento
                    page.wait_for_load_state('networkidle')
                    time.sleep(10)
                    logging.info("Procesamiento de activación completado.")
                else:
                    # Si no hay botón, verifiquemos si hay un mensaje de WispHub (ej: ya procesado)
                    msg_wisphub = ""
                    try:
                        alert_elements = page.locator(".alert, .alert-warning, .alert-info, .help-block")
                        if alert_elements.count() > 0:
                            msg_wisphub = alert_elements.first.inner_text().strip()
                    except: pass
                    
                    if msg_wisphub:
                        logging.warning(f"No se encontró el botón. WispHub dice: '{msg_wisphub}'")
                    else:
                        logging.warning(f"No se encontró el botón '{btn_confirmar_text}' ni mensajes de alerta.")
                    
                    page.screenshot(path="debug_paso2_not_found.png")
            except Exception as e:
                logging.error(f"Error durante el Paso 2 de WispHub: {e}")
                page.screenshot(path="error_paso2_critico.png")


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
    """Tarea 2: WispHub DB -> SFTP /Entrada (Retorna ruta para reporte horario)."""
    logging.info("--- Iniciando Ciclo Sincronización (WispHub -> /Entrada) ---")
    setup_directories()
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=config.headless) if hasattr(config, 'headless') else p.chromium.launch(headless=config.HEADLESS)
        context = browser.new_context()
        page = context.new_page()
        try:
            # Login con selectores robustos y tiempo extendido (90s)
            page.goto(config.WISPHUB_LOGIN_URL, timeout=90000)
            page.fill('input[name="username"], input[id*="user"], input[id*="login"]', config.WISPHUB_USER)
            page.fill('input[name="password"], input[id*="pass"]', config.WISPHUB_PASS)
            page.click('button[type="submit"], input[type="submit"]')
            
            try:
                page.wait_for_url("**/panel/**", timeout=45000)
            except:
                if page.locator(".sidebar, a[href*='logout']").count() == 0:
                    page.screenshot(path="fallo_sync_login.png")
                    raise Exception("Timeout esperando Dashboard en ciclo Sync")

            # Descarga de la base de datos
            db_file = download_database_wisphub(page)
            if db_file:
                upload_success = upload_database_sftp(db_file)
                if upload_success:
                    return db_file # Retornamos la ruta
            return None
        except Exception as e:
            logging.error(f"Error crítico en ciclo de sincronización: {e}")
            return "error"
        finally:
            browser.close()

def main():
    if not config.ENABLE_LOOP:
        try:
            cycle_payments("Ejecución única")
            cycle_reverse_sync()
        except Exception as e:
            logging.error(f"Error en ejecución única: {e}")
        return

    # Tiempos de última ejecución (Unix timestamps)
    last_sync = 0
    last_payment_primary = 0
    last_sync_report = time.time() # Timer para el reporte consolidado
    secondary_due = False
    pending_sync_files = [] # Lista para acumular archivos de sincronización

    logging.info(f"Planificador iniciado. Sync: {config.SYNC_INTERVAL_MINUTES}m | Pagos: {config.LOOP_INTERVAL_MINUTES}m + {config.SECONDARY_INTERVAL_MINUTES}m")
    logging.info(f"Reporte Consolidado Sync: cada {config.SYNC_REPORT_INTERVAL_MINUTES}m")
    logging.info(f"Horario Operativo: {config.OPERATING_HOUR_START}:00 - {config.OPERATING_HOUR_END}:00")

    while True:
        try:
            now_dt = datetime.now()
            
            # Verificación de Horario Operativo (Soporta cruce de medianoche)
            in_window = False
            if config.OPERATING_HOUR_START < config.OPERATING_HOUR_END:
                # Caso estándar (ej: 8 AM a 8 PM)
                if config.OPERATING_HOUR_START <= now_dt.hour < config.OPERATING_HOUR_END:
                    in_window = True
            else:
                # Caso cruce de medianoche (ej: 6 AM a 1 AM)
                if now_dt.hour >= config.OPERATING_HOUR_START or now_dt.hour < config.OPERATING_HOUR_END:
                    in_window = True

            if not in_window:
                logging.info(f"Fuera de horario operativo ({now_dt.hour}:00). Durmiendo 30 minutos...")
                time.sleep(1800) # Dormir 30 min y volver a chequear
                continue

            now = time.time()

            # 1. Sincronización Inversa (Cada 10 min) - SOLO SUBIDA AL SFTP
            if now - last_sync >= (config.SYNC_INTERVAL_MINUTES * 60):
                try:
                    res = cycle_reverse_sync()
                    if res and res != "error":
                        pending_sync_files.append(res)
                    time.sleep(config.TASK_DELAY_SECONDS) # Delay extendido para evitar Cloudflare
                except Exception as e:
                    logging.error(f"Fallo en Carrera de Sync: {e}")
                last_sync = time.time()
                now = time.time() # Refrescar tiempo tras la espera

            # 2. Reporte Consolidado de Sincronización (Cada 1 hora)
            if now - last_sync_report >= (config.SYNC_REPORT_INTERVAL_MINUTES * 60):
                if pending_sync_files:
                    try:
                        subject = f"Resumen Horario: Sincronización WispHub -> Efecty"
                        body = f"Se han procesado {len(pending_sync_files)} archivos de sincronización en la última hora.\n\n"
                        body += "Archivos subidos:\n" + "\n".join([f"- {os.path.basename(f)}" for f in pending_sync_files])
                        send_email_report(subject, body, attachment_paths=pending_sync_files)
                        pending_sync_files = [] # Limpiar para la siguiente hora
                    except Exception as e:
                        logging.error(f"Error enviando reporte consolidado: {e}")
                last_sync_report = time.time()
                now = time.time()

            # 3. Ciclo de Pagos (Primario - Cada 60 min)
            if now - last_payment_primary >= (config.LOOP_INTERVAL_MINUTES * 60):
                try:
                    cycle_payments("Carrera 1 de 2")
                    time.sleep(config.TASK_DELAY_SECONDS) 
                except Exception as e:
                    logging.error(f"Fallo en Carrera 1 de Pagos: {e}")
                last_payment_primary = time.time()
                secondary_due = True
                now = time.time()

            # 4. Ciclo de Pagos (Secundario - 5 min después)
            if secondary_due and (now - last_payment_primary >= (config.SECONDARY_INTERVAL_MINUTES * 60)):
                try:
                    cycle_payments("Carrera 2 de 2")
                except Exception as e:
                    logging.error(f"Fallo en Carrera 2 de Pagos: {e}")
                secondary_due = False # Reset
                
            time.sleep(10) # Pequeño sleep para no saturar CPU en el loop

        except KeyboardInterrupt:
            logging.info("Detenido por usuario.")
            break
        except Exception as e:
            logging.error(f"Error fatal en el loop principal: {e}")
            time.sleep(60)

if __name__ == "__main__":
    main()
