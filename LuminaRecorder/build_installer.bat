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

REM L'icone est optionnelle : si assets\icons\lumina.ico n'existe pas,
REM PyInstaller echouerait sur --icon. On adapte la commande.
set ICON_OPT=
if exist "assets\icons\lumina.ico" set ICON_OPT=--icon=assets\icons\lumina.ico

REM src\ est embarque comme donnee : main.py l'ajoute au sys.path via
REM sys._MEIPASS quand l'application est empaquetee.
pyinstaller ^
    --name "LuminaRecorder" ^
    --windowed ^
    --onefile ^
    --noconfirm ^
    %ICON_OPT% ^
    --add-data "config;config" ^
    --add-data "assets;assets" ^
    --add-data "src;src" ^
    --paths "src" ^
    --hidden-import=psutil ^
    --hidden-import=mss ^
    --hidden-import=cv2 ^
    --hidden-import=pyaudio ^
    --hidden-import=numpy ^
    --hidden-import=packaging ^
    --hidden-import=pyaudiowpatch ^
    --collect-submodules=core ^
    --collect-submodules=ui ^
    --collect-submodules=utils ^
    --collect-submodules=filters ^
    --collect-submodules=postprocess ^
    --collect-submodules=services ^
    --collect-submodules=ai ^
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
