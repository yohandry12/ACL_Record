; =====================================================
; Lumina Recorder - Script d'Installation NSIS
; Crée un programme d'installation professionnel
; =====================================================

!include "MUI2.nsh"
!include "FileFunc.nsh"

; Informations de base
!define APP_NAME "Lumina Recorder"
!define APP_VERSION "1.0.0"
!define APP_PUBLISHER "Votre Entreprise"
!define APP_URL "https://lumina-recorder.com"
!define OUTPUT_FILE "dist_installer\Lumina_Setup_${APP_VERSION}.exe"

; Configuration de l'installateur
Name "${APP_NAME}"
OutFile "${OUTPUT_FILE}"
InstallDir "$PROGRAMFILES64\LuminaRecorder"
InstallDirRegKey HKLM "Software\${APP_NAME}" ""
RequestExecutionLevel admin
ShowInstDetails show
ShowUnInstDetails show

; Pages d'installation
!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_LICENSE "LICENSE"
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH

; Pages de désinstallation
!insertmacro MUI_UNPAGE_WELCOME
!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES
!insertmacro MUI_UNPAGE_FINISH

; Langues
!insertmacro MUI_LANGUAGE "French"
!insertmacro MUI_LANGUAGE "English"

; Section principale d'installation
Section "Lumina Recorder (Requis)" SecMain
    SetOutPath "$INSTDIR"
    
    ; Fichiers principaux
    File "dist_installer\LuminaRecorder.exe"
    File "dist_installer\README.md"
    File "dist_installer\LICENSE"
    
    ; Création des raccourcis
    CreateDirectory "$SMPROGRAMS\Lumina Recorder"
    CreateShortCut "$SMPROGRAMS\Lumina Recorder\Lumina Recorder.lnk" "$INSTDIR\LuminaRecorder.exe"
    CreateShortCut "$SMPROGRAMS\Lumina Recorder\Désinstaller.lnk" "$INSTDIR\uninstall.exe"
    
    CreateShortCut "$DESKTOP\Lumina Recorder.lnk" "$INSTDIR\LuminaRecorder.exe"
    
    ; Enregistrement dans la base de registre
    WriteRegStr HKLM "Software\${APP_NAME}" "" $INSTDIR
    WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APP_NAME}" "DisplayName" "${APP_NAME}"
    WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APP_NAME}" "UninstallString" "$INSTDIR\uninstall.exe"
    WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APP_NAME}" "DisplayVersion" "${APP_VERSION}"
    WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APP_NAME}" "Publisher" "${APP_PUBLISHER}"
    WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APP_NAME}" "URLInfoAbout" "${APP_URL}"
    
    ; Création du désinstalleur
    WriteUninstaller "$INSTDIR\uninstall.exe"
    
SectionEnd

; Section pour FFmpeg (optionnelle)
Section /o "FFmpeg (Codec vidéo)" SecFFmpeg
    ; Cette section pourrait télécharger FFmpeg automatiquement
    ; Pour l'instant, on affiche juste une note
    MessageBox MB_OK "Note: Assurez-vous d'avoir installé FFmpeg séparément.$\n$\nTéléchargement: https://www.gyan.dev/ffmpeg/builds/"
SectionEnd

; Section de désinstallation
Section "Uninstall"
    ; Suppression des fichiers
    Delete "$INSTDIR\LuminaRecorder.exe"
    Delete "$INSTDIR\README.md"
    Delete "$INSTDIR\LICENSE"
    Delete "$INSTDIR\uninstall.exe"
    
    ; Suppression des raccourcis
    Delete "$DESKTOP\Lumina Recorder.lnk"
    Delete "$SMPROGRAMS\Lumina Recorder\Lumina Recorder.lnk"
    Delete "$SMPROGRAMS\Lumina Recorder\Désinstaller.lnk"
    RMDir "$SMPROGRAMS\Lumina Recorder"
    
    ; Suppression des clés de registre
    DeleteRegKey HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APP_NAME}"
    DeleteRegKey HKLM "Software\${APP_NAME}"
    
    ; Tentative de suppression du dossier (seulement si vide)
    RMDir "$INSTDIR"
    
    MessageBox MB_OK "Lumina Recorder a été désinstallé avec succès."
    
SectionEnd

; Fonctions personnalisées
Function .onInit
    ; Vérification de la version Windows
    ${If} ${RunningX64}
        StrCpy $INSTDIR "$PROGRAMFILES64\LuminaRecorder"
    ${Else}
        StrCpy $INSTDIR "$PROGRAMFILES\LuminaRecorder"
    ${EndIf}
FunctionEnd

Function .onInstSuccess
    ; Option: Lancer l'application après installation
    ; Exec "$INSTDIR\LuminaRecorder.exe"
FunctionEnd
