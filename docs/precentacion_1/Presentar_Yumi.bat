@echo off
setlocal
cd /d "%~dp0"
echo.
echo  Yumi - presentacion HTML (HyperFrames)
echo  Abriendo http://localhost:8765/index.html
echo  Teclas: flechas o Espacio = avanzar/retroceder, P = modo presentador, L = Yumi en vivo
echo  Para detener: cierra esta ventana o pulsa Ctrl+C
echo.
start "" /min cmd /c "ping -n 3 127.0.0.1 >nul & start http://localhost:8765/index.html"
where python >nul 2>nul && (python -m http.server 8765 --bind 127.0.0.1 & goto :eof)
where py >nul 2>nul && (py -m http.server 8765 --bind 127.0.0.1 & goto :eof)
echo No se encontro Python. Alternativa: instala Node.js y ejecuta: npx hyperframes present composition
pause
