#!/bin/bash

echo "🚀 Iniciando servidor Marriott Automation..."

# Verificar variables de entorno
if [ "$RENDER" = "true" ]; then
    echo "📍 Entorno: Render (Producción)"
    export PRODUCTION=true
else
    echo "📍 Entorno: Desarrollo"
fi

# Verificar Chrome y ChromeDriver
echo "🔍 Verificando instalaciones..."

# Buscar Chrome
CHROME_PATHS=(
    "/usr/bin/google-chrome-stable"
    "/usr/bin/google-chrome"
    "/usr/bin/chromium-browser"
    "/opt/google/chrome/chrome"
    "/opt/render/.cache/chrome/bin/chrome"
)

CHROME_FOUND=false
for path in "${CHROME_PATHS[@]}"; do
    if [ -f "$path" ]; then
        echo "✅ Chrome encontrado: $path"
        export CHROME_BIN="$path"
        CHROME_FOUND=true
        break
    fi
done

if [ "$CHROME_FOUND" = false ]; then
    echo "❌ Chrome no encontrado en ubicaciones estándar"
else
    # Verificar versión
    CHROME_VERSION=$("$CHROME_BIN" --version 2>/dev/null || echo "Versión desconocida")
    echo "📋 Versión Chrome: $CHROME_VERSION"
fi

# Buscar ChromeDriver
DRIVER_PATHS=(
    "/usr/local/bin/chromedriver"
    "/usr/bin/chromedriver"
    "/opt/chromedriver/chromedriver"
    "/opt/render/.cache/chromedriver/bin/chromedriver"
)

DRIVER_FOUND=false
for path in "${DRIVER_PATHS[@]}"; do
    if [ -f "$path" ]; then
        echo "✅ ChromeDriver encontrado: $path"
        export CHROMEDRIVER_PATH="$path"
        DRIVER_FOUND=true
        break
    fi
done

if [ "$DRIVER_FOUND" = false ]; then
    echo "❌ ChromeDriver no encontrado en ubicaciones estándar"
else
    # Verificar versión
    DRIVER_VERSION=$("$CHROMEDRIVER_PATH" --version 2>/dev/null || echo "Versión desconocida")
    echo "📋 Versión ChromeDriver: $DRIVER_VERSION"
fi

# Crear directorios necesarios
mkdir -p temp_results
mkdir -p logs

echo "📁 Estructura de directorios:"
ls -la

# Verificar permisos
if [ -n "$CHROME_BIN" ] && [ -f "$CHROME_BIN" ]; then
    chmod +x "$CHROME_BIN" 2>/dev/null || echo "⚠️ No se pudieron establecer permisos para Chrome"
fi

if [ -n "$CHROMEDRIVER_PATH" ] && [ -f "$CHROMEDRIVER_PATH" ]; then
    chmod +x "$CHROMEDRIVER_PATH" 2>/dev/null || echo "⚠️ No se pudieron establecer permisos para ChromeDriver"
fi

# Configurar display virtual si no existe
if [ -z "$DISPLAY" ]; then
    export DISPLAY=:99
fi

# Verificar Python y dependencias
echo "🐍 Verificando Python..."
python --version
pip list | grep -E "(selenium|fastapi|uvicorn)" || echo "⚠️ Algunas dependencias podrían faltar"

echo "🌐 Iniciando servidor FastAPI..."

# Determinar puerto
PORT=${PORT:-8000}
echo "📡 Puerto configurado: $PORT"

# Iniciar servidor
if [ "$RENDER" = "true" ]; then
    # Producción: Usar uvicorn con configuraciones optimizadas
    exec uvicorn main:app --host 0.0.0.0 --port $PORT --workers 1 --timeout-keep-alive 30 --access-log
else
    # Desarrollo: Usar uvicorn con reload
    exec uvicorn main:app --host 0.0.0.0 --port $PORT --reload
fi