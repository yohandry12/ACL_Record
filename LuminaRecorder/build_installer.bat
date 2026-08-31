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

REM Version unique, lue depuis src\version.py : elle nomme le setup et
REM alimente le registre Windows via /DAPP_VERSION plus bas
set APP_VERSION=
for /f tokens^=2^ delims^=^" %%v in ('findstr /C:"__version__" src\version.py') do set APP_VERSION=%%v
if "%APP_VERSION%"=="" (
    echo [ERREUR] Version introuvable dans src\version.py
    pause
    exit /b 1
)
echo [INFO] Version : %APP_VERSION%
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
REM pkg_resources (tire par keyring) exige jaraco.* a l'execution de
REM l'exe ; ces paquets ne viennent pas toujours avec setuptools
pip install jaraco.text jaraco.functools jaraco.context more_itertools --quiet

REM L'icone est optionnelle : si assets\icons\lumina.ico n'existe pas,
REM PyInstaller echouerait sur --icon. On adapte la commande.
set ICON_OPT=
if exist "assets\icons\lumina.ico" set ICON_OPT=--icon=assets\icons\lumina.ico

REM src\ est embarque comme donnee : main.py l'ajoute au sys.path via
REM sys._MEIPASS quand l'application est empaquetee.
REM Les --exclude-module ecartent la pile IA lourde (PyTorch & cie,
REM plusieurs Go) : elle est optionnelle par conception (requirements-ai),
REM et l'embarquer rendrait le onefile enorme et lent a demarrer. Dans
REM l'exe, sous-titres Whisper et OCR se declarent indisponibles ; l'IA
REM via Ollama et les API distantes fonctionne normalement (HTTP).
REM Les --hidden-import de modules standard (wave, audioop...) ne sont pas
REM superflus : PyInstaller ne les detecte pas a travers les imports
REM indirects de src\, et l'exe plante alors a l'import sans afficher la
REM moindre fenetre -- le bootloader onefile reste vivant, ce qui donne
REM l'illusion d'une application lancee mais invisible.
REM Les jaraco.* et more_itertools sont exiges par pkg_resources (tire
REM par keyring) : sans eux l'exe meurt au demarrage sur
REM " The 'jaraco.text' package is required ".
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
    --exclude-module=torch ^
    --exclude-module=torchvision ^
    --exclude-module=torchaudio ^
    --exclude-module=transformers ^
    --exclude-module=easyocr ^
    --exclude-module=faster_whisper ^
    --exclude-module=ctranslate2 ^
    --exclude-module=tensorboard ^
    --hidden-import=psutil ^
    --hidden-import=mss ^
    --hidden-import=cv2 ^
    --hidden-import=pyaudio ^
    --hidden-import=numpy ^
    --hidden-import=packaging ^
    --hidden-import=pyaudiowpatch ^
    --hidden-import=win32gui ^
    --hidden-import=wave ^
    --hidden-import=audioop ^
    --hidden-import=configparser ^
    --hidden-import=subprocess ^
    --hidden-import=shutil ^
    --hidden-import=json ^
    --collect-submodules=core ^
    --collect-submodules=ui ^
    --collect-submodules=utils ^
    --collect-submodules=filters ^
    --collect-submodules=postprocess ^
    --collect-submodules=services ^
    --collect-submodules=ai ^
    --collect-submodules=webui ^
    --hidden-import=webview ^
    --hidden-import=keyring ^
    --hidden-import=keyring.backends.Windows ^
    --hidden-import=jaraco.text ^
    --hidden-import=jaraco.functools ^
    --hidden-import=jaraco.context ^
    --hidden-import=more_itertools ^
    --hidden-import=clr ^
    --collect-submodules=webview ^
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

REM Compilation du setup NSIS si makensis est disponible.
REM /DAPP_VERSION transmet la version de src\version.py : le .nsi ne
REM porte qu'un filet de secours, jamais la vraie valeur.
set MAKENSIS=
if exist "%ProgramFiles(x86)%\NSIS\makensis.exe" set MAKENSIS="%ProgramFiles(x86)%\NSIS\makensis.exe"
if exist "%ProgramFiles%\NSIS\makensis.exe" set MAKENSIS="%ProgramFiles%\NSIS\makensis.exe"

if defined MAKENSIS (
    echo [INSTALLATEUR] Compilation du setup NSIS...
    %MAKENSIS% /DAPP_VERSION=%APP_VERSION% setup_installer.nsi
    if errorlevel 1 (
        echo [ERREUR] La compilation NSIS a échoué.
        pause
        exit /b 1
    )
    echo [OK] Setup généré : dist_installer\Lumina_Setup_%APP_VERSION%.exe
) else (
    echo [NOTE] NSIS introuvable : setup non généré.
    echo Installez NSIS puis lancez :
    echo   makensis /DAPP_VERSION=%APP_VERSION% setup_installer.nsi
)

echo.
echo ╔═══════════════════════════════════════════════╗
echo ║           BUILD TERMINE AVEC SUCCES           ║
echo ╚═══════════════════════════════════════════════╝
echo.
echo Fichiers générés :
echo   - dist\LuminaRecorder.exe (exécutable portable)
echo   - dist_installer\Lumina_Setup_%APP_VERSION%.exe (installateur)
echo Relancer ce setup sur un poste déjà équipé propose la mise à jour.
echo.

pause
