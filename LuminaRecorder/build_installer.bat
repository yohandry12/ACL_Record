@echo off
REM =====================================================
REM Lumina Recorder - Script de Build et d'Installation
REM Génère l'exécutable et le programme d'installation
REM =====================================================

echo ╔═══════════════════════════════════════════════╗
echo ║     ✨ LUMINA RECORDER - BUILD SCRIPT         ║
echo ║  Génération de l'installateur Windows         ║
echo ╚═══════════════════════════════════════════════╝
echo.

REM Vérification de Python
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERREUR] Python n'est pas installé ou pas dans le PATH.
    echo Téléchargez Python depuis https://www.python.org/downloads/
    pause
    exit /b 1
)

echo [INFO] Python détecté...
python --version
echo.

REM Nettoyage des anciens builds
echo [NETTOYAGE] Suppression des anciens builds...
if exist "dist" rmdir /s /q dist
if exist "build" rmdir /s /q build
if exist "dist_installer" rmdir /s /q dist_installer
if exist "*.spec" del /q *.spec
echo [OK] Nettoyage terminé
echo.

REM Installation des dépendances
echo [INSTALLATION] Installation des dépendances Python...
pip install --upgrade pip --quiet
pip install -r requirements.txt --quiet
echo [OK] Dépendances installées
echo.

REM Compilation avec PyInstaller
echo [COMPILATION] Création de l'exécutable avec PyInstaller...
pip install pyinstaller --quiet

pyinstaller ^
    --name "LuminaRecorder" ^
    --windowed ^
    --onefile ^
    --icon="assets\icons\lumina.ico" ^
    --add-data "config;config" ^
    --add-data "assets;assets" ^
    --hidden-import=src ^
    --hidden-import=src.core ^
    --hidden-import=src.ui ^
    --hidden-import=src.utils ^
    --hidden-import=psutil ^
    --hidden-import=mss ^
    --hidden-import=cv2 ^
    --hidden-import=pyaudio ^
    --hidden-import=numpy ^
    --hidden-import=packaging ^
    main.py

if errorlevel 1 (
    echo [ERREUR] La compilation a échoué. Vérifiez les erreurs ci-dessus.
    pause
    exit /b 1
)

echo [OK] Exécutable généré dans dist\LuminaRecorder.exe
echo.

REM Création du dossier installateur
echo [INSTALLATEUR] Préparation du programme d'installation...
mkdir dist_installer 2>nul
copy dist\LuminaRecorder.exe dist_installer\ >nul
copy README.md dist_installer\ >nul
copy LICENSE dist_installer\ >nul 2>nul

echo.
echo ╔═══════════════════════════════════════════════╗
echo ║           BUILD TERMINE AVEC SUCCES           ║
echo ╚═══════════════════════════════════════════════╝
echo.
echo Fichiers générés :
echo   - dist\LuminaRecorder.exe (exécutable portable)
echo   - dist_installer\ (fichiers pour NSIS)
echo.
echo Prochaine étape : Utiliser NSIS pour créer Setup.exe
echo Commande: makensis setup_installer.nsi
echo.

pause
