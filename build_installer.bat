@echo off
REM Script de Build et Création de l'Installateur pour Screen Recorder Pro
REM Ce script automatise la création de l'exécutable et du setup d'installation

echo ============================================================
echo   BUILD SCREEN RECORDER PRO - WINDOWS INSTALLER
echo ============================================================
echo.

REM 1. Vérification des prérequis
echo [1/4] Verification des pre-requis...

python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo ERREUR: Python n'est pas installe ou n'est pas dans le PATH.
    echo Veuillez installer Python depuis https://www.python.org/downloads/
    pause
    exit /b 1
)

pip show pyinstaller >nul 2>&1
if %errorlevel% neq 0 (
    echo Installation de PyInstaller en cours...
    pip install pyinstaller
)

REM Vérification optionnelle de NSIS (pour le compilateur final)
where makensis >nul 2>&1
if %errorlevel% neq 0 (
    echo ATTENTION: NSIS (makensis) n'est pas trouve dans le PATH.
    echo L'installateur .exe ne sera pas genere automatiquement.
    echo Vous devrez compiler manuellement le fichier setup_installer.nsi avec NSIS.
    echo Telechargez NSIS ici: https://nsis.sourceforge.io/Download
    set NSIS_AVAILABLE=false
) else (
    set NSIS_AVAILABLE=true
)
echo.

REM 2. Installation des dépendances
echo [2/4] Installation des dependances Python...
pip install -r requirements.txt
if %errorlevel% neq 0 (
    echo ERREUR lors de l'installation des dependances.
    pause
    exit /b 1
)
echo.

REM 3. Création de l'exécutable avec PyInstaller
echo [3/4] Creation de l'executable avec PyInstaller...
REM Nettoyage des anciens builds
if exist "dist" rmdir /s /q dist
if exist "build" rmdir /s /q build

REM Commande PyInstaller optimisée pour une application desktop professionnelle
pyinstaller --onefile ^
    --windowed ^
    --name "screen_recorder" ^
    --icon="NONE" ^
    --add-data "README.md;." ^
    --hidden-import=mss ^
    --hidden-import=cv2 ^
    --hidden-import=pyaudio ^
    --hidden-import=numpy ^
    --hidden-import=psutil ^
    screen_recorder.py

if %errorlevel% neq 0 (
    echo ERREUR lors de la compilation PyInstaller.
    pause
    exit /b 1
)

echo Executable cree avec succes dans le dossier 'dist'.
echo.

REM 4. Création de l'installateur (si NSIS est disponible)
echo [4/4] Creation de l'installateur...
if "%NSIS_AVAILABLE%"=="true" (
    if not exist "dist_installer" mkdir dist_installer
    
    echo Compilation du script NSIS en cours...
    makensis /V3 setup_installer.nsi
    
    if %errorlevel% equ 0 (
        echo.
        echo ============================================================
        echo   SUCCES! Installateur genere avec succes.
        echo   Fichier: dist_installer\ScreenRecorderPro_Setup_1.0.0.exe
        echo ============================================================
    ) else (
        echo ERREUR lors de la compilation NSIS.
    )
) else (
    echo.
    echo ============================================================
    echo   ETAPE MANUELLE REQUISE POUR L'INSTALLATEUR
    echo ============================================================
    echo L'executable est pret dans: dist\screen_recorder.exe
    echo.
    echo Pour creer le vrai programme d'installation (.msi ou .exe):
    echo 1. Installez NSIS depuis https://nsis.sourceforge.io/Download
    echo 2. Lancez la commande: makensis setup_installer.nsi
    echo OU utilisez le fichier .nsis fourni avec l'interface graphique de NSIS.
    echo.
    echo Alternative simple: Vous pouvez deja copier manuellement
    echo le fichier 'dist\screen_recorder.exe' n'importe ou sur votre PC.
    echo ============================================================
)

echo.
pause
