from fastapi import FastAPI, File, UploadFile, Form, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
import os
import tempfile
import asyncio
from datetime import datetime
import uuid
import json
from typing import Dict, List, Optional
from pydantic import BaseModel
from openpyxl import load_workbook, Workbook
from selenium_processor import MarriottProcessor
import uvicorn
import pandas as pd

# === CONFIGURACIÓN ===
app = FastAPI(title="Marriott Automation API", version="2.0.0")

# CORS para comunicación con frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # En producción: ["https://tu-frontend.vercel.app"]
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# === MODELOS DE DATOS ===
class TaskStatus(BaseModel):
    task_id: str
    status: str  # "pending", "processing", "completed", "error"
    progress: int  # 0-100
    total_records: int
    processed_records: int
    successful_records: int
    error_records: int
    current_processing: str  # Persona que se está procesando actualmente
    message: str
    logs: List[str]  # Últimos logs
    result_file_url: Optional[str] = None
    created_at: str

# === ALMACENAMIENTO EN MEMORIA DE TAREAS ===
tasks_storage: Dict[str, Dict] = {}
temp_files_dir = "temp_results"

# Crear directorio temporal si no existe
os.makedirs(temp_files_dir, exist_ok=True)

# === FUNCIONES AUXILIARES ===
def leer_archivo_excel(file_path: str) -> List[Dict]:
    """
    Leer archivo Excel con diagnóstico completo
    """
    try:
        import os
        
        # === DIAGNÓSTICO COMPLETO ===
        print(f"[DEBUG] Ruta del archivo: {file_path}")
        print(f"[DEBUG] ¿Archivo existe? {os.path.exists(file_path)}")
        
        if os.path.exists(file_path):
            file_size = os.path.getsize(file_path)
            print(f"[DEBUG] Tamaño del archivo: {file_size} bytes")
            
            # Leer primeros bytes para verificar formato
            with open(file_path, 'rb') as f:
                primeros_bytes = f.read(10)
                print(f"[DEBUG] Primeros 10 bytes (hex): {primeros_bytes.hex()}")
                print(f"[DEBUG] Primeros 10 bytes (texto): {primeros_bytes}")
        else:
            raise ValueError("El archivo temporal no existe")
        
        # Intentar diferentes engines de lectura
        engines_to_try = ['openpyxl', 'xlrd']
        
        for engine in engines_to_try:
            try:
                print(f"[DEBUG] Intentando leer con engine: {engine}")
                
                # Leer archivo sin asumir headers automáticos
                df = pd.read_excel(file_path, header=None, engine=engine)
                
                print(f"[DEBUG] ¡ÉXITO! Archivo leído con {engine}")
                print(f"[DEBUG] Dimensiones: {len(df)} filas, {len(df.columns)} columnas")
                break
                
            except Exception as e:
                print(f"[DEBUG] Engine {engine} falló: {str(e)}")
                if engine == engines_to_try[-1]:  # Si es el último engine
                    raise e
                continue
        
        # === RESTO DEL CÓDIGO ORIGINAL ===
        
        # Verificar que el archivo tiene suficientes filas y columnas
        if len(df) <= 4:
            raise ValueError("El archivo Excel debe tener al menos 5 filas (incluyendo headers en fila 4)")
        
        if len(df.columns) < 9:
            raise ValueError("El archivo Excel debe tener al menos 9 columnas (hasta columna I)")
        
        # Verificar headers en fila 4 (índice 3)
        headers_row = df.iloc[3]
        print(f"[DEBUG] Headers en fila 4: {headers_row.tolist()}")
        
        # Posiciones fijas
        COL_RESERVA = 2   # Columna C
        COL_NOMBRE = 6    # Columna G 
        COL_CORREO = 8    # Columna I
        
        # Verificar headers específicos
        header_reserva = str(headers_row.iloc[COL_RESERVA]).strip()
        header_nombre = str(headers_row.iloc[COL_NOMBRE]).strip()
        header_correo = str(headers_row.iloc[COL_CORREO]).strip()
        
        print(f"[DEBUG] Headers encontrados:")
        print(f"  - Columna C (Reserva): '{header_reserva}'")
        print(f"  - Columna G (Nombre): '{header_nombre}'")
        print(f"  - Columna I (Correo): '{header_correo}'")
        
        # Extraer datos desde fila 5
        registros = []
        filas_procesadas = 0
        filas_validas = 0
        
        for index in range(4, min(len(df), 10)):  # Solo primeras 6 filas para debug
            try:
                fila = df.iloc[index]
                filas_procesadas += 1
                
                reserva_raw = fila.iloc[COL_RESERVA]
                nombre_raw = fila.iloc[COL_NOMBRE]
                correo_raw = fila.iloc[COL_CORREO]
                
                print(f"[DEBUG] Fila {index + 1}: '{reserva_raw}' | '{nombre_raw}' | '{correo_raw}'")
                
                # Limpiar datos
                reserva = str(reserva_raw).strip() if pd.notna(reserva_raw) else "N/A"
                nombre = str(nombre_raw).strip() if pd.notna(nombre_raw) else ""
                correo = str(correo_raw).strip().lower() if pd.notna(correo_raw) else ""
                
                # Validar
                if not nombre or nombre.lower() in ['nan', 'none', '']:
                    print(f"[DEBUG] Fila {index + 1} saltada: nombre vacío")
                    continue
                    
                if not correo or correo.lower() in ['nan', 'none', ''] or '@' not in correo:
                    print(f"[DEBUG] Fila {index + 1} saltada: correo inválido")
                    continue
                
                registros.append({
                    "reserva": reserva,
                    "nombre": nombre,
                    "correo": correo,
                    "fila": index + 1
                })
                filas_validas += 1
                print(f"[DEBUG] ✅ Registro válido {filas_validas}: {nombre} | {correo}")
                
            except Exception as e:
                print(f"[DEBUG] Error en fila {index + 1}: {e}")
                continue
        
        # Procesar el resto de las filas si las primeras 6 funcionaron
        if filas_validas > 0 and len(df) > 10:
            print(f"[DEBUG] Procesando el resto de filas ({len(df) - 10} restantes)...")
            
            for index in range(10, len(df)):
                try:
                    fila = df.iloc[index]
                    
                    reserva_raw = fila.iloc[COL_RESERVA]
                    nombre_raw = fila.iloc[COL_NOMBRE]
                    correo_raw = fila.iloc[COL_CORREO]
                    
                    reserva = str(reserva_raw).strip() if pd.notna(reserva_raw) else "N/A"
                    nombre = str(nombre_raw).strip() if pd.notna(nombre_raw) else ""
                    correo = str(correo_raw).strip().lower() if pd.notna(correo_raw) else ""
                    
                    if nombre and nombre.lower() not in ['nan', 'none', ''] and correo and '@' in correo:
                        registros.append({
                            "reserva": reserva,
                            "nombre": nombre,
                            "correo": correo,
                            "fila": index + 1
                        })
                        filas_validas += 1
                
                except Exception as e:
                    continue
        
        print(f"[DEBUG] RESUMEN: {filas_validas} registros válidos de {len(df)} filas totales")
        
        if not registros:
            raise ValueError("No se encontraron registros válidos")
        
        return registros
        
    except Exception as e:
        print(f"[ERROR] Error completo: {str(e)}")
        raise ValueError(f"Error leyendo archivo Excel: {str(e)}")
    """
    Leer archivo Excel con posiciones exactas conocidas
    Fila 4 (índice 3): Headers
    Columna C (índice 2): No. Rsrv
    Columna G (índice 6): Nombre del Huésped  
    Columna I (índice 8): Correo Electrónico
    """
    try:
        # Leer archivo sin asumir headers automáticos
        df = pd.read_excel(file_path, header=None, engine="openpyxl")
        
        print(f"[DEBUG] Archivo Excel leído: {len(df)} filas, {len(df.columns)} columnas")
        
        # Verificar que el archivo tiene suficientes filas y columnas
        if len(df) <= 4:
            raise ValueError("El archivo Excel debe tener al menos 5 filas (incluyendo headers en fila 4)")
        
        if len(df.columns) < 9:  # Necesitamos al menos columna I (índice 8)
            raise ValueError("El archivo Excel debe tener al menos 9 columnas (hasta columna I)")
        
        # Verificar headers en fila 4 (índice 3)
        headers_row = df.iloc[3]
        print(f"[DEBUG] Headers en fila 4: {headers_row.tolist()}")
        
        # Posiciones fijas basadas en tu información
        COL_RESERVA = 2   # Columna C (índice 2)
        COL_NOMBRE = 6    # Columna G (índice 6) 
        COL_CORREO = 8    # Columna I (índice 8)
        
        # Verificar que los headers son los esperados (opcional)
        header_reserva = str(headers_row.iloc[COL_RESERVA]).strip()
        header_nombre = str(headers_row.iloc[COL_NOMBRE]).strip()
        header_correo = str(headers_row.iloc[COL_CORREO]).strip()
        
        print(f"[DEBUG] Headers encontrados:")
        print(f"  - Columna C (Reserva): '{header_reserva}'")
        print(f"  - Columna G (Nombre): '{header_nombre}'")
        print(f"  - Columna I (Correo): '{header_correo}'")
        
        # Extraer datos desde fila 5 en adelante (índice 4+)
        registros = []
        filas_procesadas = 0
        filas_validas = 0
        
        for index in range(4, len(df)):  # Desde fila 5 (índice 4)
            try:
                fila = df.iloc[index]
                filas_procesadas += 1
                
                # Extraer valores de las columnas específicas
                reserva_raw = fila.iloc[COL_RESERVA]
                nombre_raw = fila.iloc[COL_NOMBRE]
                correo_raw = fila.iloc[COL_CORREO]
                
                # Limpiar y validar datos
                reserva = str(reserva_raw).strip() if pd.notna(reserva_raw) else "N/A"
                nombre = str(nombre_raw).strip() if pd.notna(nombre_raw) else ""
                correo = str(correo_raw).strip().lower() if pd.notna(correo_raw) else ""
                
                # Validar que tenemos datos esenciales
                if not nombre or nombre.lower() in ['nan', 'none', '']:
                    continue
                    
                if not correo or correo.lower() in ['nan', 'none', ''] or '@' not in correo:
                    continue
                
                # Agregar registro válido
                registros.append({
                    "reserva": reserva,
                    "nombre": nombre,
                    "correo": correo,
                    "fila": index + 1  # +1 porque Excel empieza en 1
                })
                filas_validas += 1
                
                # Debug cada 10 registros
                if filas_validas <= 5 or filas_validas % 10 == 0:
                    print(f"[DEBUG] Registro {filas_validas}: {nombre} | {correo} | {reserva}")
                
            except Exception as e:
                print(f"[WARNING] Error procesando fila {index + 1}: {e}")
                continue
        
        print(f"[DEBUG] Resumen procesamiento:")
        print(f"  - Filas procesadas: {filas_procesadas}")
        print(f"  - Registros válidos: {filas_validas}")
        
        if not registros:
            raise ValueError("No se encontraron registros válidos en el archivo. Verifica que:")
            raise ValueError("1. La fila 4 contenga los headers")
            raise ValueError("2. Las columnas C, G, I contengan datos")
            raise ValueError("3. Hay datos desde la fila 5 en adelante")
        
        return registros
        
    except Exception as e:
        print(f"[ERROR] Error completo: {str(e)}")
        raise ValueError(f"Error leyendo archivo Excel: {str(e)}")
    """
    Leer archivo Excel y extraer datos relevantes
    """
    try:
        # Detectar columnas automáticamente
        col_reserva, col_nombre, col_correo = detectar_columnas_excel(file_path)
        
        if not all([col_reserva, col_nombre, col_correo]):
            missing = []
            if not col_reserva: missing.append("Número de Reserva")
            if not col_nombre: missing.append("Nombre del Huésped")
            if not col_correo: missing.append("Correo Electrónico")
            raise ValueError(f"No se pudieron encontrar las columnas: {', '.join(missing)}")
        
        # Leer archivo completo
        df = pd.read_excel(file_path)
        
        # Extraer solo las filas que tienen datos en las 3 columnas importantes
        registros = []
        for index, row in df.iterrows():
            reserva = row.get(col_reserva)
            nombre = row.get(col_nombre)
            correo = row.get(col_correo)
            
            # Validar que tenemos datos esenciales
            if pd.notna(nombre) and pd.notna(correo) and str(nombre).strip() and str(correo).strip():
                registros.append({
                    "reserva": str(reserva).strip() if pd.notna(reserva) else "N/A",
                    "nombre": str(nombre).strip(),
                    "correo": str(correo).strip().lower(),
                    "fila": index + 2  # +2 porque Excel empieza en 1 y tenemos header
                })
        
        return registros
        
    except Exception as e:
        raise ValueError(f"Error leyendo archivo Excel: {str(e)}")

def actualizar_estado_tarea(task_id: str, **kwargs):
    """Actualizar el estado de una tarea"""
    if task_id in tasks_storage:
        for key, value in kwargs.items():
            tasks_storage[task_id][key] = value
        tasks_storage[task_id]["last_updated"] = datetime.now().isoformat()

def agregar_log_tarea(task_id: str, mensaje: str):
    """Agregar un log a la tarea"""
    if task_id in tasks_storage:
        timestamp = datetime.now().strftime("%H:%M:%S")
        log_con_timestamp = f"[{timestamp}] {mensaje}"
        tasks_storage[task_id]["logs"].append(log_con_timestamp)
        
        # Mantener solo los últimos 20 logs para no sobrecargar memoria
        if len(tasks_storage[task_id]["logs"]) > 20:
            tasks_storage[task_id]["logs"] = tasks_storage[task_id]["logs"][-20:]

async def procesar_afiliaciones_background(
    task_id: str, 
    registros: List[Dict], 
    tipo_afiliacion: str, 
    nombre_afiliador: str
):
    """
    Proceso en segundo plano para automatización secuencial de Marriott
    """
    processor = None
    
    try:
        agregar_log_tarea(task_id, f"Iniciando procesamiento de {len(registros)} registros")
        actualizar_estado_tarea(task_id, status="processing", total_records=len(registros))
        
        # Crear procesador
        processor = MarriottProcessor(tipo_afiliacion, nombre_afiliador)
        
        # Configurar navegador
        agregar_log_tarea(task_id, "Configurando navegador...")
        if not await processor.setup_chrome_driver():
            raise Exception("Error configurando ChromeDriver")
        
        agregar_log_tarea(task_id, "Navegador configurado correctamente")
        
        # Crear archivo de resultados
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        result_filename = f"afiliaciones_{tipo_afiliacion}_{timestamp}.xlsx"
        result_path = os.path.join(temp_files_dir, result_filename)
        
        # Crear Excel de resultados
        wb_result = Workbook()
        ws_result = wb_result.active
        ws_result.title = "Afiliaciones"
        
        # Headers del Excel
        headers = [
            "No. Fila Original", "No. Reserva", "Nombre Completo", 
            "Correo", "Código Afiliación", "Afiliador", "Estado", 
            "Observaciones", "Fecha Proceso"
        ]
        ws_result.append(headers)
        
        resultados_exitosos = 0
        resultados_error = 0
        
        # PROCESAR FILA POR FILA
        for idx, registro in enumerate(registros):
            try:
                # Actualizar estado
                progress = int((idx + 1) / len(registros) * 100)
                actualizar_estado_tarea(
                    task_id,
                    processed_records=idx + 1,
                    progress=progress,
                    current_processing=f"{registro['nombre']} ({registro['correo']})"
                )
                
                agregar_log_tarea(
                    task_id, 
                    f"[{idx+1}/{len(registros)}] Procesando: {registro['nombre']} - {registro['correo']}"
                )
                
                # Procesar afiliación individual
                resultado = await processor.procesar_afiliacion(
                    registro['nombre'],
                    registro['correo'], 
                    registro['reserva']
                )
                
                # Preparar datos para Excel
                if resultado['success']:
                    estado = "EXITOSO"
                    codigo = resultado['codigo']
                    observaciones = "Afiliación completada correctamente"
                    resultados_exitosos += 1
                    agregar_log_tarea(task_id, f"✅ ÉXITO: {registro['nombre']} - Código: {codigo}")
                else:
                    estado = "ERROR"
                    codigo = "N/A"
                    observaciones = resultado['error']
                    resultados_error += 1
                    agregar_log_tarea(task_id, f"❌ ERROR: {registro['nombre']} - {resultado['error']}")
                
                # Agregar fila al Excel
                fila_resultado = [
                    registro['fila'],              # Fila original del Excel
                    registro['reserva'],           # Número de reserva
                    registro['nombre'],            # Nombre completo
                    registro['correo'],            # Correo electrónico
                    codigo,                        # Código de afiliación o N/A
                    nombre_afiliador,              # Nombre del afiliador
                    estado,                        # EXITOSO o ERROR
                    observaciones,                 # Detalles/observaciones
                    datetime.now().strftime("%Y-%m-%d %H:%M:%S")  # Fecha de proceso
                ]
                ws_result.append(fila_resultado)
                
                # Guardar progreso cada 5 registros
                if (idx + 1) % 5 == 0:
                    wb_result.save(result_path)
                    agregar_log_tarea(task_id, f"Progreso guardado: {idx + 1}/{len(registros)}")
                
                # Pausa entre procesos (importante para no ser detectado)
                await asyncio.sleep(2)
                
            except Exception as e:
                # Error en registro individual
                resultados_error += 1
                agregar_log_tarea(task_id, f"🚨 ERROR CRÍTICO: {registro['nombre']} - {str(e)}")
                
                # Agregar error al Excel
                fila_error = [
                    registro['fila'],
                    registro['reserva'],
                    registro['nombre'],
                    registro['correo'], 
                    "N/A",
                    nombre_afiliador,
                    "ERROR CRÍTICO",
                    f"Error procesando: {str(e)[:100]}",
                    datetime.now().strftime("%Y-%m-%d %H:%M%S")
                ]
                ws_result.append(fila_error)
                
                # Continuar con el siguiente registro
                continue
        
        # Guardar archivo final
        wb_result.save(result_path)
        agregar_log_tarea(task_id, "Archivo Excel de resultados guardado")
        
        # Actualizar estado final
        actualizar_estado_tarea(
            task_id,
            status="completed",
            progress=100,
            successful_records=resultados_exitosos,
            error_records=resultados_error,
            result_file_url=f"/download/{result_filename}",
            current_processing="Proceso completado"
        )
        
        mensaje_final = f"✅ Proceso completado exitosamente. Resultados: {resultados_exitosos} exitosos, {resultados_error} errores"
        agregar_log_tarea(task_id, mensaje_final)
        actualizar_estado_tarea(task_id, message=mensaje_final)
        
    except Exception as e:
        # Error crítico del proceso completo
        error_msg = f"🚨 Error crítico en procesamiento: {str(e)}"
        actualizar_estado_tarea(task_id, status="error", message=error_msg)
        
    finally:
        # Cerrar navegador
        if processor:
            try:
                await processor.close()
                agregar_log_tarea(task_id, "Navegador cerrado")
            except Exception:
                pass

# === ENDPOINTS API ===

@app.get("/")
async def root():
    """Endpoint de información general"""
    return {
        "message": "Marriott Automation API v2.0", 
        "status": "active",
        "endpoints": {
            "POST /procesar": "Iniciar procesamiento de afiliaciones",
            "GET /status/{task_id}": "Obtener estado de tarea en tiempo real", 
            "GET /download/{filename}": "Descargar archivo Excel con resultados",
            "GET /health": "Health check",
            "GET /tasks": "Listar todas las tareas activas"
        },
        "supported_files": [".xlsx", ".xls"],
        "affiliations": ["express", "junior"]
    }

@app.get("/health")
async def health_check():
    """Health check para servicios de despliegue como Render"""
    return {
        "status": "healthy", 
        "timestamp": datetime.now().isoformat(),
        "active_tasks": len(tasks_storage),
        "temp_files": len([f for f in os.listdir(temp_files_dir) if f.endswith('.xlsx')])
    }

@app.post("/procesar")
async def procesar_afiliaciones(
    background_tasks: BackgroundTasks,
    archivo_excel: UploadFile = File(..., description="Archivo Excel con huéspedes"),
    tipo_afiliacion: str = Form(..., description="Tipo: 'express' o 'junior'"),
    nombre_afiliador: str = Form(..., description="Nombre del afiliador")
):
    """
    Endpoint principal para iniciar procesamiento de afiliaciones Marriott
    """
    try:
        # === VALIDACIONES INICIALES ===
        if not archivo_excel.filename.endswith(('.xlsx', '.xls')):
            raise HTTPException(
                status_code=400, 
                detail="Solo se permiten archivos Excel (.xlsx, .xls)"
            )
        
        if tipo_afiliacion.lower() not in ["express", "junior"]:
            raise HTTPException(
                status_code=400, 
                detail="tipo_afiliacion debe ser 'express' o 'junior'"
            )
        
        if not nombre_afiliador.strip():
            raise HTTPException(
                status_code=400, 
                detail="nombre_afiliador es requerido y no puede estar vacío"
            )
        
        # === PROCESAR ARCHIVO EXCEL ===
        # Generar ID único para la tarea
        task_id = str(uuid.uuid4())
        
        # Guardar archivo temporal
        with tempfile.NamedTemporaryFile(delete=False, suffix='.xlsx') as tmp_file:
            content = await archivo_excel.read()
            tmp_file.write(content)
            tmp_path = tmp_file.name
        
        # Leer y validar Excel
        try:
            registros = leer_archivo_excel(tmp_path)
            if not registros:
                raise ValueError("No se encontraron registros válidos en el archivo Excel")
                
        except Exception as e:
            os.unlink(tmp_path)  # Limpiar archivo temporal
            raise HTTPException(status_code=400, detail=str(e))
        finally:
            # Limpiar archivo temporal después de leerlo
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)
        
        # === CREAR ESTADO INICIAL DE TAREA ===
        tasks_storage[task_id] = {
            "task_id": task_id,
            "status": "pending",
            "progress": 0,
            "total_records": len(registros),
            "processed_records": 0,
            "successful_records": 0,
            "error_records": 0,
            "current_processing": "Preparando...",
            "message": f"Tarea creada. {len(registros)} registros para procesar.",
            "logs": [f"Tarea iniciada con {len(registros)} registros"],
            "result_file_url": None,
            "created_at": datetime.now().isoformat(),
            "last_updated": datetime.now().isoformat(),
            "tipo_afiliacion": tipo_afiliacion.lower(),
            "nombre_afiliador": nombre_afiliador.strip()
        }
        
        # === INICIAR PROCESAMIENTO EN SEGUNDO PLANO ===
        background_tasks.add_task(
            procesar_afiliaciones_background,
            task_id,
            registros,
            tipo_afiliacion.lower(),
            nombre_afiliador.strip()
        )
        
        return JSONResponse(
            status_code=202,  # Accepted
            content={
                "success": True,
                "message": "Procesamiento iniciado exitosamente",
                "task_id": task_id,
                "total_records": len(registros),
                "status_url": f"/status/{task_id}",
                "estimated_time_minutes": len(registros) * 0.5,  # Estimación: 30 segundos por registro
                "next_steps": [
                    f"1. Monitorea el progreso en: GET /status/{task_id}",
                    f"2. Descarga los resultados cuando termine: GET /download/[filename]"
                ]
            }
        )
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error interno del servidor: {str(e)}")

@app.get("/status/{task_id}")
async def obtener_estado(task_id: str):
    """
    Obtener estado en tiempo real del procesamiento
    """
    if task_id not in tasks_storage:
        raise HTTPException(status_code=404, detail="Tarea no encontrada")
    
    task_data = tasks_storage[task_id]
    
    # Calcular estadísticas adicionales
    if task_data["total_records"] > 0:
        success_rate = (task_data["successful_records"] / task_data["processed_records"] * 100) if task_data["processed_records"] > 0 else 0
        remaining_records = task_data["total_records"] - task_data["processed_records"]
        estimated_remaining_minutes = remaining_records * 0.5  # 30 seg por registro
    else:
        success_rate = 0
        remaining_records = 0
        estimated_remaining_minutes = 0
    
    return TaskStatus(
        task_id=task_data["task_id"],
        status=task_data["status"],
        progress=task_data["progress"],
        total_records=task_data["total_records"],
        processed_records=task_data["processed_records"],
        successful_records=task_data["successful_records"],
        error_records=task_data["error_records"],
        current_processing=task_data["current_processing"],
        message=task_data["message"],
        logs=task_data["logs"][-10:],  # Solo los últimos 10 logs
        result_file_url=task_data["result_file_url"],
        created_at=task_data["created_at"]
    ).dict(exclude_none=True) | {
        "success_rate": round(success_rate, 2),
        "remaining_records": remaining_records,
        "estimated_remaining_minutes": round(estimated_remaining_minutes, 1),
        "last_updated": task_data["last_updated"]
    }

@app.get("/download/{filename}")
async def descargar_archivo(filename: str):
    """
    Descargar archivo Excel con resultados
    """
    file_path = os.path.join(temp_files_dir, filename)
    
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="Archivo no encontrado")
    
    if not filename.endswith('.xlsx'):
        raise HTTPException(status_code=400, detail="Solo se pueden descargar archivos Excel")
    
    return FileResponse(
        path=file_path,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        filename=filename,
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )

@app.get("/tasks")
async def listar_tareas():
    """
    Listar todas las tareas activas (útil para debugging y monitoreo)
    """
    tasks_summary = []
    
    for task_id, task_data in tasks_storage.items():
        tasks_summary.append({
            "task_id": task_id,
            "status": task_data["status"],
            "progress": task_data["progress"],
            "total_records": task_data["total_records"],
            "processed_records": task_data["processed_records"],
            "successful_records": task_data["successful_records"],
            "created_at": task_data["created_at"],
            "tipo_afiliacion": task_data.get("tipo_afiliacion", "unknown"),
            "nombre_afiliador": task_data.get("nombre_afiliador", "unknown")
        })
    
    return {
        "total_active_tasks": len(tasks_storage),
        "tasks": tasks_summary,
        "server_time": datetime.now().isoformat()
    }

@app.delete("/task/{task_id}")
async def eliminar_tarea(task_id: str):
    """
    Eliminar una tarea específica (limpieza manual)
    """
    if task_id not in tasks_storage:
        raise HTTPException(status_code=404, detail="Tarea no encontrada")
    
    task_status = tasks_storage[task_id]["status"]
    
    if task_status == "processing":
        raise HTTPException(
            status_code=400, 
            detail="No se puede eliminar una tarea en procesamiento"
        )
    
    del tasks_storage[task_id]
    
    return {
        "message": f"Tarea {task_id} eliminada exitosamente",
        "task_id": task_id
    }

# === EVENTOS DE APLICACIÓN ===
@app.on_event("startup")
async def startup_event():
    """
    Ejecutar al iniciar la aplicación
    """
    print("=== MARRIOTT AUTOMATION API INICIADA ===")
    print(f"Directorio temporal: {temp_files_dir}")
    
    # Limpiar archivos antiguos (más de 24 horas)
    try:
        current_time = datetime.now().timestamp()
        files_cleaned = 0
        
        for filename in os.listdir(temp_files_dir):
            file_path = os.path.join(temp_files_dir, filename)
            if os.path.getmtime(file_path) < current_time - 86400:  # 24 horas
                os.remove(file_path)
                files_cleaned += 1
        
        print(f"Limpieza inicial: {files_cleaned} archivos antiguos eliminados")
        
    except Exception as e:
        print(f"Error en limpieza inicial: {e}")
    
    print("API lista para recibir peticiones")

@app.on_event("shutdown")
async def shutdown_event():
    """
    Ejecutar al cerrar la aplicación
    """
    print("=== CERRANDO MARRIOTT AUTOMATION API ===")
    
    # Aquí podrías agregar lógica para cerrar navegadores activos
    # y limpiar recursos si fuera necesario
    
    print("API cerrada correctamente")

# === CONFIGURACIÓN PARA PRODUCCIÓN ===
if __name__ == "__main__":
    # Para desarrollo local
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=int(os.getenv("PORT", 8000)),
        reload=True,
        log_level="info"
    )