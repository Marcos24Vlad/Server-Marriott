import os
import time
import re
import asyncio
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import Select
from selenium.common.exceptions import NoSuchElementException, TimeoutException

# === CONFIGURACIÓN ===
URLS_AFILIACION = {
    "express": "https://www.joinmarriottbonvoy.com/calaqr/s/ES/ch/cunxc",
    "junior": "https://www.joinmarriottbonvoy.com/calaqr/s/ES/ch/cunjc"
}

EXTENSIONES_PERMITIDAS = {
    'hotmail.com', 'hotmail.es', 'hotmail.mx',
    'gmail.com', 'gmail.mx',
    'outlook.com', 'outlook.es', 'outlook.mx',
    'icloud.com'
}

class MarriottProcessor:
    def __init__(self, tipo_afiliacion, nombre_afiliador):
        self.tipo_afiliacion = tipo_afiliacion.lower()
        self.nombre_afiliador = nombre_afiliador
        self.driver = None
        self.wait = None
        self.correos_procesados = set()

    async def setup_chrome_driver(self):
        """Configuración OPTIMIZADA para Render"""
        try:
            print("[🔧] Configurando ChromeDriver para Render...")
            
            # Detectar entorno
            is_render = os.getenv('RENDER') or 'render.com' in os.getenv('RENDER_EXTERNAL_URL', '')
            is_heroku = os.getenv('DYNO') is not None
            is_production = is_render or is_heroku or os.getenv('PRODUCTION')
            
            print(f"[📍] Entorno detectado - Render: {is_render}, Producción: {is_production}")
            
            if is_production:
                driver = await self._config_produccion_render()
            else:
                driver = await self._config_desarrollo_local()
            
            if driver:
                self.driver = driver
                self.wait = WebDriverWait(self.driver, 30)
                
                # Test de conectividad
                print("[🧪] Probando navegador...")
                self.driver.get("https://httpbin.org/ip")
                time.sleep(2)
                
                # Anti-detección
                self.driver.execute_script(
                    "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
                )
                
                print("[✅] ChromeDriver configurado exitosamente!")
                return True
            
            raise Exception("❌ No se pudo configurar ChromeDriver")
            
        except Exception as e:
            print(f"[🚨] Error configurando ChromeDriver: {e}")
            return False

    async def _config_produccion_render(self):
        """Configuración específica para Render/Producción"""
        print("[🏭] Configurando para entorno de producción...")
        
        # Configuración para Render con buildpacks
        options = self._get_production_chrome_options()
        
        # Intentar diferentes configuraciones para Render
        configuraciones_render = [
            # Config 1: Google Chrome instalado por buildpack
            {
                'binary': '/opt/chrome/chrome',
                'driver': '/opt/chromedriver/chromedriver'
            },
            # Config 2: Chrome en ubicaciones alternativas
            {
                'binary': '/usr/bin/google-chrome',
                'driver': '/usr/bin/chromedriver'
            },
            # Config 3: Chrome estable
            {
                'binary': '/usr/bin/google-chrome-stable',
                'driver': '/usr/local/bin/chromedriver'
            },
            # Config 4: Variables de entorno (tu config original)
            {
                'binary': os.getenv("CHROME_BIN", "/usr/bin/google-chrome"),
                'driver': os.getenv("CHROMEDRIVER_PATH", "/usr/bin/chromedriver")
            }
        ]
        
        for i, config in enumerate(configuraciones_render, 1):
            try:
                print(f"[🔄] Probando configuración Render {i}...")
                
                chrome_bin = config['binary']
                driver_path = config['driver']
                
                # Verificar que existan los archivos
                if os.path.exists(chrome_bin) and os.path.exists(driver_path):
                    print(f"[✅] Archivos encontrados - Chrome: {chrome_bin}, Driver: {driver_path}")
                    
                    # Hacer ejecutables
                    os.chmod(chrome_bin, 0o755)
                    os.chmod(driver_path, 0o755)
                    
                    options.binary_location = chrome_bin
                    service = Service(driver_path)
                    
                    driver = webdriver.Chrome(service=service, options=options)
                    print(f"[🎉] Configuración Render {i} EXITOSA!")
                    return driver
                else:
                    print(f"[⚠️] Archivos no encontrados - Chrome: {os.path.exists(chrome_bin)}, Driver: {os.path.exists(driver_path)}")
                    
            except Exception as e:
                print(f"[⚠️] Configuración Render {i} falló: {str(e)[:100]}")
                continue
        
        # Si todo falla, intentar con webdriver-manager
        try:
            print("[🔄] Intentando webdriver-manager como último recurso...")
            from webdriver_manager.chrome import ChromeDriverManager
            
            service = Service(ChromeDriverManager().install())
            driver = webdriver.Chrome(service=service, options=options)
            print("[✅] webdriver-manager exitoso!")
            return driver
            
        except Exception as e:
            print(f"[❌] webdriver-manager también falló: {e}")
        
        raise Exception("Todas las configuraciones de producción fallaron")

    async def _config_desarrollo_local(self):
        """Configuración para desarrollo local"""
        print("[🏠] Configurando para desarrollo local...")
        
        options = self._get_development_chrome_options()
        
        # Configuraciones para desarrollo
        configuraciones_dev = [
            # Config 1: webdriver-manager
            self._try_webdriver_manager,
            # Config 2: ChromeDriver del PATH
            self._try_system_chromedriver,
            # Config 3: ChromeDriver local
            self._try_local_chromedriver
        ]
        
        for i, config_func in enumerate(configuraciones_dev, 1):
            try:
                print(f"[🔄] Probando configuración local {i}...")
                driver = await config_func(options)
                if driver:
                    print(f"[✅] Configuración local {i} exitosa!")
                    return driver
            except Exception as e:
                print(f"[⚠️] Configuración local {i} falló: {str(e)[:100]}")
                continue
        
        raise Exception("Todas las configuraciones locales fallaron")

    async def _try_webdriver_manager(self, options):
        """Intentar webdriver-manager"""
        from webdriver_manager.chrome import ChromeDriverManager
        service = Service(ChromeDriverManager().install())
        return webdriver.Chrome(service=service, options=options)

    async def _try_system_chromedriver(self, options):
        """Intentar ChromeDriver del sistema"""
        import subprocess
        subprocess.run(['chromedriver', '--version'], capture_output=True, check=True, timeout=5)
        service = Service()
        return webdriver.Chrome(service=service, options=options)

    async def _try_local_chromedriver(self, options):
        """Intentar ChromeDriver local"""
        import platform
        driver_name = 'chromedriver.exe' if platform.system() == 'Windows' else 'chromedriver'
        
        ubicaciones = [
            driver_name,
            f'./{driver_name}',
            f'./drivers/{driver_name}',
            f'../drivers/{driver_name}'
        ]
        
        for ubicacion in ubicaciones:
            if os.path.exists(ubicacion):
                service = Service(ubicacion)
                return webdriver.Chrome(service=service, options=options)
        
        raise Exception(f"{driver_name} no encontrado")

    def _get_production_chrome_options(self):
        """Opciones de Chrome optimizadas para producción"""
        options = webdriver.ChromeOptions()
        
        # Configuración para Render/Heroku
        options.add_argument("--headless=new")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--disable-gpu")
        options.add_argument("--disable-software-rasterizer")
        options.add_argument("--disable-background-timer-throttling")
        options.add_argument("--disable-backgrounding-occluded-windows")
        options.add_argument("--disable-renderer-backgrounding")
        options.add_argument("--disable-features=TranslateUI")
        options.add_argument("--disable-ipc-flooding-protection")
        options.add_argument("--disable-background-networking")
        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_argument("--disable-web-security")
        options.add_argument("--allow-running-insecure-content")
        options.add_argument("--disable-extensions")
        options.add_argument("--disable-plugins")
        options.add_argument("--disable-images")
        options.add_argument("--disable-javascript") # OPCIONAL: descomenta si no necesitas JS
        
        # Configuración de memoria y rendimiento
        options.add_argument("--memory-pressure-off")
        options.add_argument("--max_old_space_size=4096")
        options.add_argument("--aggressive-cache-discard")
        
        # Tamaño de ventana
        options.add_argument("--window-size=1280,720")
        
        # User agent
        options.add_argument(
            "--user-agent=Mozilla/5.0 (Linux; x86_64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        )
        
        # Preferencias
        prefs = {
            "profile.default_content_setting_values": {
                "notifications": 2,
                "media_stream": 2,
                "geolocation": 2,
                "images": 2  # Deshabilitar imágenes
            },
            "profile.managed_default_content_settings": {
                "images": 2
            }
        }
        
        options.add_experimental_option("prefs", prefs)
        options.add_experimental_option("excludeSwitches", ["enable-automation"])
        options.add_experimental_option("useAutomationExtension", False)
        
        return options

    def _get_development_chrome_options(self):
        """Opciones de Chrome para desarrollo (más permisivas)"""
        options = webdriver.ChromeOptions()
        
        # Desarrollo puede no ser headless para debugging
        # options.add_argument("--headless=new")  # Comentar para ver el navegador
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_argument("--window-size=1280,720")
        
        options.add_experimental_option("excludeSwitches", ["enable-automation"])
        options.add_experimental_option("useAutomationExtension", False)
        
        return options

    # [Resto de métodos permanecen igual...]
    def es_correo_valido(self, correo):
        """Verifica extensión permitida y evita duplicados"""
        if not correo or '@' not in correo:
            return False, "Formato inválido"
        
        try:
            dominio = correo.split('@')[1].lower()
            
            if dominio not in EXTENSIONES_PERMITIDAS:
                return False, f"Extensión {dominio} no permitida"
                
            if correo in self.correos_procesados:
                return False, "Correo ya procesado (duplicado)"
            
            return True, "Válido"
            
        except IndexError:
            return False, "Error en formato"

    def llenar_campo_inteligente(self, campo, valor, nombre_campo="campo"):
        """Llenar campo con estrategias múltiples"""
        try:
            # Scroll al elemento
            self.driver.execute_script("arguments[0].scrollIntoView({block: 'center', behavior: 'smooth'});", campo)
            time.sleep(0.2)
            
            # Focus y limpiar
            self.driver.execute_script("arguments[0].focus();", campo)
            campo.clear()
            
            # Llenar con múltiples métodos
            try:
                campo.send_keys(valor)
            except Exception:
                self.driver.execute_script("arguments[0].value = arguments[1];", campo, valor)
                self.driver.execute_script("arguments[0].dispatchEvent(new Event('input', { bubbles: true }));", campo)
            
            # Verificar que se llenó
            valor_actual = campo.get_attribute('value')
            success = valor_actual == valor
            
            print(f"[{'✅' if success else '⚠️'}] {nombre_campo}: {valor}")
            return success
            
        except Exception as e:
            print(f"[❌] Error llenando {nombre_campo}: {e}")
            return False

    def encontrar_elemento_inteligente(self, localizadores, nombre_elemento):
        """Buscar elemento con múltiples localizadores"""
        for i, (tipo, valor) in enumerate(localizadores):
            try:
                elemento = self.wait.until(EC.element_to_be_clickable((tipo, valor)))
                print(f"[✅] {nombre_elemento} encontrado (método {i+1})")
                return elemento
            except TimeoutException:
                continue
        
        print(f"[❌] {nombre_elemento} no encontrado")
        return None

    def seleccionar_pais_inteligente(self, pais="MX"):
        """Seleccionar México en dropdown país"""
        localizadores_dropdown = [
            (By.ID, "country"),
            (By.NAME, "country"),
            (By.CSS_SELECTOR, "select[name*='country']"),
            (By.XPATH, "//select[contains(@id, 'country')]")
        ]
        
        dropdown_pais = self.encontrar_elemento_inteligente(localizadores_dropdown, "Dropdown país")
        if not dropdown_pais:
            return False
        
        try:
            select = Select(dropdown_pais)
            
            # Intentar por valor
            try:
                select.select_by_value(pais)
                print(f"[✅] País seleccionado: {pais}")
                return True
            except Exception:
                pass
            
            # Intentar por texto
            opciones_pais = ["mexico", "méxico", "mx"]
            for opcion in opciones_pais:
                try:
                    for option in select.options:
                        if opcion in option.text.lower():
                            select.select_by_value(option.get_attribute('value'))
                            print(f"[✅] País seleccionado: {option.text}")
                            return True
                except Exception:
                    continue
            
            print("[⚠️] No se pudo seleccionar México")
            return False
            
        except Exception as e:
            print(f"[❌] Error seleccionando país: {e}")
            return False

    def marcar_checkboxes_inteligente(self):
        """Marcar checkboxes requeridos"""
        try:
            script = """
            var checkboxes = [];
            
            // Buscar por IDs conocidos
            var checkbox1 = document.getElementById('ctlAgree');
            var checkbox2 = document.getElementById('chk_mi');
            
            if (checkbox1) checkboxes.push(checkbox1);
            if (checkbox2) checkboxes.push(checkbox2);
            
            // Buscar otros checkboxes no marcados
            var alternativeChecks = document.querySelectorAll('input[type="checkbox"]:not([checked])');
            for (var i = 0; i < alternativeChecks.length; i++) {
                checkboxes.push(alternativeChecks[i]);
            }
            
            // Marcar todos
            var marcados = 0;
            for (var i = 0; i < checkboxes.length; i++) {
                if (!checkboxes[i].checked) {
                    checkboxes[i].checked = true;
                    checkboxes[i].click();
                    marcados++;
                }
            }
            
            return marcados;
            """
            
            marcados = self.driver.execute_script(script)
            print(f"[✅] {marcados} checkboxes marcados")
            return True
            
        except Exception as e:
            print(f"[❌] Error marcando checkboxes: {e}")
            return False

    def buscar_codigo_afiliacion_inteligente(self):
        """Búsqueda exhaustiva del código de afiliación"""
        print("[🔍] Buscando código de afiliación...")
        
        # Espera inteligente para carga de página
        for i in range(15):
            try:
                url_actual = self.driver.current_url.lower()
                if "confirmation" in url_actual or "success" in url_actual:
                    break
                
                page_text = self.driver.page_source.lower()
                if any(keyword in page_text for keyword in ["confirmation", "member", "congratulations"]):
                    break
                    
            except Exception:
                pass
            
            time.sleep(1)
        
        # === ESTRATEGIA 1: BÚSQUEDA POR ELEMENTOS ===
        selectores_codigo = [
            "//strong[contains(text(), 'MB')]",
            "//strong[contains(text(), 'member')]//text()[string-length(.) >= 8]",
            "//strong[string-length(text()) >= 8 and string-length(text()) <= 15]",
            "//*[contains(text(), 'Member')]/following-sibling::*//strong",
            "//div[contains(@class, 'confirmation')]//strong",
            "//div[contains(@class, 'success')]//strong",
            "//span[string-length(text()) >= 8 and string-length(text()) <= 15]",
            "//*[contains(text(), 'number')]/following-sibling::*",
            "//*[contains(text(), 'código')]/following-sibling::*"
        ]
        
        for selector in selectores_codigo:
            try:
                elementos = self.driver.find_elements(By.XPATH, selector)
                for elemento in elementos:
                    codigo = elemento.text.strip()
                    if codigo and len(codigo) >= 6 and any(char.isdigit() for char in codigo):
                        print(f"[✅] Código encontrado (elemento): {codigo}")
                        return codigo
            except Exception:
                continue
        
        # === ESTRATEGIA 2: BÚSQUEDA POR PATRONES ===
        try:
            page_text = self.driver.page_source
            
            patrones = [
                r'MB\d{8,12}',           # Códigos MB + dígitos
                r'\b\d{10,12}\b',        # 10-12 dígitos exactos
                r'\b\d{9}\b',            # 9 dígitos exactos
                r'[A-Z]{2}\d{8,10}',     # 2 letras + 8-10 números
                r'\b\d{8}\b',            # 8 dígitos exactos
            ]
            
            for patron in patrones:
                matches = re.findall(patron, page_text)
                if matches:
                    for match in matches:
                        # Filtrar fechas
                        if not re.match(r'^(19|20)\d{2}', match):
                            print(f"[✅] Código encontrado (patrón): {match}")
                            return match
        
        except Exception as e:
            print(f"[⚠️] Error en búsqueda por patrones: {e}")
        
        print("[❌] Código de afiliación no encontrado")
        return None

    async def procesar_afiliacion(self, nombre_completo, correo, numero_reserva):
        """Procesar una afiliación individual"""
        try:
            print(f"[🔄] Procesando: {nombre_completo} ({correo})")
            
            # Validar correo
            es_valido, razon = self.es_correo_valido(correo)
            if not es_valido:
                return {"success": False, "error": f"Correo inválido: {razon}"}
            
            # Separar nombre
            partes = nombre_completo.strip().split()
            if len(partes) < 2:
                return {"success": False, "error": "Nombre completo debe tener al menos nombre y apellido"}
            
            nombre = partes[0]
            apellido = " ".join(partes[1:])
            
            # Marcar como procesado
            self.correos_procesados.add(correo)
            
            # Abrir página de afiliación
            url = URLS_AFILIACION[self.tipo_afiliacion]
            print(f"[🌐] Abriendo: {url}")
            self.driver.get(url)
            
            # Esperar formulario
            self.wait.until(EC.presence_of_element_located((By.ID, "partial_enroll_form")))
            time.sleep(1)
            
            # === LLENAR FORMULARIO ===
            
            # 1. Nombre
            localizadores_nombre = [
                (By.ID, "first_name"),
                (By.NAME, "first_name"),
                (By.CSS_SELECTOR, "input[name*='first']")
            ]
            campo_nombre = self.encontrar_elemento_inteligente(localizadores_nombre, "Campo nombre")
            if not campo_nombre or not self.llenar_campo_inteligente(campo_nombre, nombre, "Nombre"):
                return {"success": False, "error": "No se pudo llenar el nombre"}
            
            # 2. Apellido
            localizadores_apellido = [
                (By.ID, "last_name"),
                (By.NAME, "last_name"),
                (By.CSS_SELECTOR, "input[name*='last']")
            ]
            campo_apellido = self.encontrar_elemento_inteligente(localizadores_apellido, "Campo apellido")
            if not campo_apellido or not self.llenar_campo_inteligente(campo_apellido, apellido, "Apellido"):
                return {"success": False, "error": "No se pudo llenar el apellido"}
            
            # 3. Email
            localizadores_email = [
                (By.ID, "email_address"),
                (By.NAME, "email_address"),
                (By.CSS_SELECTOR, "input[type='email']")
            ]
            campo_email = self.encontrar_elemento_inteligente(localizadores_email, "Campo email")
            if not campo_email or not self.llenar_campo_inteligente(campo_email, correo, "Email"):
                return {"success": False, "error": "No se pudo llenar el email"}
            
            # 4. Seleccionar país
            self.seleccionar_pais_inteligente()
            
            # 5. Marcar checkboxes
            self.marcar_checkboxes_inteligente()
            
            # 6. Enviar formulario
            localizadores_submit = [
                (By.ID, "ctl00_PartialEnrollFormPlaceholder_partial_enroll_EnrollButton"),
                (By.CSS_SELECTOR, "a.css_button"),
                (By.XPATH, "//a[contains(@class, 'button')]"),
                (By.XPATH, "//input[@type='submit']")
            ]
            
            boton_submit = self.encontrar_elemento_inteligente(localizadores_submit, "Botón enviar")
            if not boton_submit:
                return {"success": False, "error": "Botón de envío no encontrado"}
            
            # Enviar
            try:
                self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", boton_submit)
                time.sleep(0.5)
                self.driver.execute_script("arguments[0].click();", boton_submit)
            except Exception:
                boton_submit.click()
            
            print("[📤] Formulario enviado")
            
            # 7. Buscar código
            codigo = self.buscar_codigo_afiliacion_inteligente()
            
            if codigo:
                print(f"[🎉] ¡ÉXITO! {nombre_completo} | Código: {codigo}")
                return {
                    "success": True,
                    "codigo": codigo,
                    "nombre": nombre_completo,
                    "correo": correo,
                    "reserva": numero_reserva
                }
            else:
                return {"success": False, "error": "Código no encontrado en la página"}
                
        except Exception as e:
            error_msg = f"Error procesando {nombre_completo}: {str(e)}"
            print(f"[🚨] {error_msg}")
            return {"success": False, "error": error_msg}

    async def close(self):
        """Cerrar navegador"""
        if self.driver:
            try:
                self.driver.quit()
                print("[✅] Navegador cerrado")
            except Exception as e:
                print(f"[⚠️] Error cerrando navegador: {e}")