; Script d'installation NSIS pour Screen Recorder Pro
; Nécessite NSIS (Nullsoft Scriptable Install System) installé sur la machine de build

!define APP_NAME "ScreenRecorderPro"
!define APP_VERSION "1.0.0"
!define COMPANY_NAME "MonEntreprise"
!define OUTPUT_DIR "dist_installer"

; Fichier exécutable généré par PyInstaller
!define MAIN_EXE "dist\screen_recorder.exe"

Unicode True
SetCompressor /SOLID lzma
Name "${APP_NAME}"
OutFile "${OUTPUT_DIR}\${APP_NAME}_Setup_${APP_VERSION}.exe"
InstallDir "$PROGRAMFILES64\${COMPANY_NAME}\${APP_NAME}"
InstallDirRegKey HKLM "Software\${COMPANY_NAME}\${APP_NAME}" ""
RequestExecutionLevel admin ; Demande les droits administrateur

; Pages
Page components
Page directory
Page instfiles

; Sections
Section "Application Principale" SecApp
    SetOutPath "$INSTDIR"
    
    ; Copier l'exécutable principal
    File "${MAIN_EXE}"
    
    ; Copier FFmpeg si présent dans le dossier dist (optionnel mais recommandé)
    ; File "dist\ffmpeg.exe" 
    
    ; Créer le lien de désinstallation
    WriteUninstaller "$INSTDIR\uninstall.exe"
    
    ; Créer les clés de registre pour "Ajouter/Supprimer des programmes"
    WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APP_NAME}" "DisplayName" "${APP_NAME}"
    WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APP_NAME}" "UninstallString" "$\"$INSTDIR\uninstall.exe$\""
    WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APP_NAME}" "DisplayIcon" "$INSTDIR\screen_recorder.exe"
    WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APP_NAME}" "DisplayVersion" "${APP_VERSION}"
    WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APP_NAME}" "Publisher" "${COMPANY_NAME}"
SectionEnd

Section "Raccourci Bureau" SecDesktop
    SetOutPath "$INSTDIR"
    CreateShortCut "$DESKTOP\${APP_NAME}.lnk" "$INSTDIR\screen_recorder.exe" "" "$INSTDIR\screen_recorder.exe" 0
SectionEnd

Section "Menu Démarrer" SecStartMenu
    SetOutPath "$INSTDIR"
    CreateDirectory "$SMPROGRAMS\${COMPANY_NAME}"
    CreateShortCut "$SMPROGRAMS\${COMPANY_NAME}\${APP_NAME}.lnk" "$INSTDIR\screen_recorder.exe" "" "$INSTDIR\screen_recorder.exe" 0
    CreateShortCut "$SMPROGRAMS\${COMPANY_NAME}\Désinstaller.lnk" "$INSTDIR\uninstall.exe"
SectionEnd

; Section de désinstallation
Section "Uninstall"
    ; Supprimer les fichiers
    Delete "$INSTDIR\screen_recorder.exe"
    Delete "$INSTDIR\uninstall.exe"
    
    ; Supprimer les raccourcis
    Delete "$DESKTOP\${APP_NAME}.lnk"
    Delete "$SMPROGRAMS\${COMPANY_NAME}\${APP_NAME}.lnk"
    Delete "$SMPROGRAMS\${COMPANY_NAME}\Désinstaller.lnk"
    RMDir "$SMPROGRAMS\${COMPANY_NAME}"
    
    ; Supprimer le dossier d'installation (seulement s'il est vide)
    RMDir "$INSTDIR"
    
    ; Supprimer les clés de registre
    DeleteRegKey HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APP_NAME}"
    DeleteRegKey HKLM "Software\${COMPANY_NAME}\${APP_NAME}"
SectionEnd

; Langues
LoadLanguageFile "${NSISDIR}\Contrib\Language files\French.nlf"
LangString ^SecApp ${LANG_FRENCH} "Application Principale"
LangString ^SecDesktop ${LANG_FRENCH} "Créer un raccourci sur le Bureau"
LangString ^SecStartMenu ${LANG_FRENCH} "Créer un dossier dans le Menu Démarrer"
