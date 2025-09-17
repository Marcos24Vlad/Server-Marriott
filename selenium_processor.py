import os
import time
import re
import asyncio
import subprocess
import shutil
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
        """Configuración MEJORADA para Render con detección inteligente"""
        try:
            print("[🔧] Configurando ChromeDriver para entorno de producción...")
            
            # Detectar entorno
            is_render = os.getenv('RENDER') or 'render.com' in os.getenv('RENDER_EXTERNAL_URL', '')
            is_production = is_render or os.getenv('PRODUCTION') or os.getenv('DYNO')
            
            print(f"[📍] Entorno detectado - Render: {is_render}, Producción: {is_production}")
            
            # Configurar opciones de Chrome
            options = self._get_chrome_options(is_production)
            
            if is_production:
                driver = await self._setup_production_chrome(options)
            else:
                driver = await self._setup_local_chrome(options)
            
            if driver:
                self.driver = driver
                self.wait = WebDriverWait(self.driver, 30)
                
                # Test de conectividad
                await self._test_browser_connection()
                
                # Anti-detección
                await self._setup_anti_detection()
                
                print("[✅] ChromeDriver configurado exitosamente!")
                return True
            
            raise Exception("❌ No se pudo configurar ChromeDriver")
            
        except Exception as e:
            print(f"[🚨] Error configurando ChromeDriver: {e}")
            return False

    async def _setup_production_chrome(self, options):
        """Configuración para producción con múltiples estrategias"""
        print("[🏭] Configurando Chrome para producción...")
        
        # Lista de configuraciones a probar en orden de prioridad
        configs = [
            # Config 1: Buildpack estándar de Heroku/Render
            {
                'name': 'Buildpack Chrome',
                'chrome_bin': os.getenv('CHROME_BIN', '/opt/render/.cache/chrome/bin/chrome'),
                'driver_path': os.getenv('CHROMEDRIVER_PATH', '/opt/render/.cache/chromedriver/bin/chromedriver')
            },
            # Config 2: Google Chrome instalado por buildpack
            {
                'name': 'Google Chrome Buildpack',
                'chrome_bin': '/opt/google/chrome/chrome',
                'driver_path': '/opt/chromedriver/chromedriver'
            },
            # Config 3: Chrome estable del sistema
            {
                'name': 'Sistema Chrome',
                'chrome_bin': '/usr/bin/google-chrome-stable',
                'driver_path': '/usr/bin/chromedriver'
            },
            # Config 4: Chrome genérico
            {
                'name': 'Chrome genérico',
                'chrome_bin': '/usr/bin/google-chrome',
                'driver_path': '/usr/local/bin/chromedriver'
            }
        ]
        
        for config in configs:
            try:
                print(f"[🔄] Probando {config['name']}...")
                
                # Verificar binarios
                chrome_exists = os.path.isfile(config['chrome_bin'])
                driver_exists = os.path.isfile(config['driver_path'])
                
                print(f"[📍] Chrome: {config['chrome_bin']} ({'✅' if chrome_exists else '❌'})")
                print(f"[📍] Driver: {config['driver_path']} ({'✅' if driver_exists else '❌'})")
                
                if chrome_exists and driver_exists:
                    # Hacer ejecutables
                    os.chmod(config['chrome_bin'], 0o755)
                    os.chmod(config['driver_path'], 0o755)
                    
                    # Configurar binario de Chrome
                    options.binary_location = config['chrome_bin']
                    
                    # Crear servicio
                    service = Service(config['driver_path'])
                    
                    # Intentar crear driver
                    driver = webdriver.Chrome(service=service, options=options)
                    print(f"[🎉] {config['name']} configurado exitosamente!")
                    return driver
                
            except Exception as e:
                print(f"[⚠️] {config['name']} falló: {str(e)[:100]}...")
                continue
        
        # Estrategia de respaldo: webdriver-manager
        try:
            print("[🔄] Intentando webdriver-manager como respaldo...")
            from webdriver_manager.chrome import ChromeDriverManager
            
            # Instalar ChromeDriver
            driver_path = ChromeDriverManager().install()
            service = Service(driver_path)
            
            # Buscar Chrome automáticamente
            chrome_paths = [
                '/usr/bin/google-chrome-stable',
                '/usr/bin/google-chrome',
                '/usr/bin/chromium-browser',
                '/opt/google/chrome/chrome'
            ]
            
            for chrome_path in chrome_paths:
                if os.path.isfile(chrome_path):
                    options.binary_location = chrome_path
                    break
            
            driver = webdriver.Chrome(service=service, options=options)
            print("[✅] webdriver-manager exitoso!")
            return driver
            
        except Exception as e:
            print(f"[❌] webdriver-manager falló: {e}")
        
        raise Exception("Todas las configuraciones de producción fallaron")

    async def _setup_local_chrome(self, options):
        """Configuración para desarrollo local"""
        print("[🏠] Configurando Chrome para desarrollo local...")
        
        try:
            # Intentar ChromeDriver del sistema
            service = Service()
            driver = webdriver.Chrome(service=service, options=options)
            print("[✅] Chrome local configurado!")
            return driver
            
        except Exception:
            # Usar webdriver-manager para local
            try:
                from webdriver_manager.chrome import ChromeDriverManager
                service = Service(ChromeDriverManager().install())
                driver = webdriver.Chrome(service=service, options=options)
                print("[✅] Chrome local con webdriver-manager configurado!")
                return driver
            except Exception as e:
                raise Exception(f"No se pudo configurar Chrome local: {e}")

    def _get_chrome_options(self, is_production=True):
        """Opciones optimizadas de Chrome"""
        options = webdriver.ChromeOptions()
        
        # Opciones básicas (siempre necesarias)
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--disable-gpu")
        options.add_argument("--window-size=1920,1080")
        
        if is_production:
            # Opciones específicas para producción
            options.add_argument("--headless=new")
            options.add_argument("--disable-software-rasterizer")
            options.add_argument("--disable-background-timer-throttling")
            options.add_argument("--disable-backgrounding-occluded-windows")
            options.add_argument("--disable-renderer-backgrounding")
            options.add_argument("--disable-features=TranslateUI,VizDisplayCompositor")
            options.add_argument("--disable-extensions")
            options.add_argument("--disable-plugins")
            options.add_argument("--disable-images")
            options.add_argument("--disable-javascript")  # Comentar si necesitas JS
            options.add_argument("--memory-pressure-off")
            options.add_argument("--aggressive-cache-discard")
        else:
            # Opciones para desarrollo (más permisivas)
            print("[💻] Configurando opciones de desarrollo")
            # options.add_argument("--headless=new")  # Comentar para ver navegador
        
        # Anti-detección
        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_argument("--disable-web-security")
        options.add_argument("--allow-running-insecure-content")
        
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
                "images": 2 if is_production else 1
            },
            "profile.managed_default_content_settings": {
                "images": 2 if is_production else 1
            }
        }
        
        options.add_experimental_option("prefs", prefs)
        options.add_experimental_option("excludeSwitches", ["enable-automation"])
        options.add_experimental_option("useAutomationExtension", False)
        
        return options

    async def _test_browser_connection(self):
        """Probar conexión del navegador"""
        try:
            print("[🧪] Probando conexión del navegador...")
            self.driver.get("https://httpbin.org/ip")
            await asyncio.sleep(2)
            
            # Verificar que la página cargó
            page_title = self.driver.title
            if page_title:
                print(f"[✅] Navegador funcionando - Título: {page_title}")
            else:
                print("[⚠️] Navegador funciona pero sin título de página")
                
        except Exception as e:
            print(f"[⚠️] Test de navegador parcialmente fallido: {e}")

    async def _setup_anti_detection(self):
        """Configurar anti-detección"""
        try:
            # Script para ocultar automatización
            self.driver.execute_script("""
                Object.defineProperty(navigator, 'webdriver', {
                    get: () => undefined
                });
                
                // Ocultar Chrome automation
                delete navigator.__proto__.webdriver;
                
                // Simular plugins
                Object.defineProperty(navigator, 'plugins', {
                    get: () => [1, 2, 3, 4, 5]
                });
                
                // Simular idiomas
                Object.defineProperty(navigator, 'languages', {
                    get: () => ['es-ES', 'es', 'en']
                });
            """)
            print("[🥷] Anti-detección configurada")
            
        except Exception as e:
            print(f"[⚠️] Anti-detección falló: {e}")

    # [Resto de métodos permanecen iguales...]
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
            time.sleep(0.3)
            
            # Focus y limpiar
            self.driver.execute_script("arguments[0].focus();", campo)
            campo.clear()
            time.sleep(0.1)
            
            # Llenar con múltiples métodos
            success = False
            try:
                campo.send_keys(valor)
                success = True
            except Exception:
                try:
                    self.driver.execute_script("arguments[0].value = arguments[1];", campo, valor)
                    self.driver.execute_script("arguments[0].dispatchEvent(new Event('input', { bubbles: true }));", campo)
                    success = True
                except Exception as e:
                    print(f"[❌] Error llenando campo: {e}")
            
            # Verificar que se llenó
            if success:
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
        for i in range(20):  # Aumentado el tiempo de espera
            try:
                url_actual = self.driver.current_url.lower()
                if "confirmation" in url_actual or "success" in url_actual:
                    break
                
                page_text = self.driver.page_source.lower()
                if any(keyword in page_text for keyword in ["confirmation", "member", "congratulations", "bienvenido"]):
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
            "//*[contains(text(), 'código')]/following-sibling::*",
            "//h1//text()[string-length(.) >= 8]",
            "//h2//text()[string-length(.) >= 8]",
            "//p//strong[string-length(text()) >= 8]"
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
            await asyncio.sleep(3)  # Espera fija inicial
            
            try:
                self.wait.until(EC.presence_of_element_located((By.ID, "partial_enroll_form")))
            except TimeoutException:
                print("[⚠️] Formulario tardó en cargar, continuando...")
            
            await asyncio.sleep(1)
            
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
            
            # Pequeña pausa antes de enviar
            await asyncio.sleep(2)
            
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
                await asyncio.sleep(0.5)
                self.driver.execute_script("arguments[0].click();", boton_submit)
            except Exception:
                boton_submit.click()
            
            print("[📤] Formulario enviado")
            
            # 7. Buscar código
            await asyncio.sleep(3)  # Esperar respuesta del servidor
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