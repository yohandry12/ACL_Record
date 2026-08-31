; =====================================================
; Lumina Recorder - Script d'Installation NSIS
; Crée un programme d'installation professionnel
; =====================================================

!include "MUI2.nsh"
!include "FileFunc.nsh"
; x64.nsh fournit ${RunningX64}, utilisé dans .onInit — sans cette
; inclusion le script ne compile pas
!include "x64.nsh"

; Informations de base.
; APP_VERSION vient du script de build : makensis /DAPP_VERSION=x.y.z,
; lu depuis src\version.py — seule source de vérité. La valeur ci-dessous
; n'est qu'un filet si le .nsi est compilé à la main.
!ifndef APP_VERSION
  !define APP_VERSION "1.1.0"
!endif
!define APP_NAME "Lumina Recorder"
!define APP_PUBLISHER "Votre Entreprise"
!define APP_URL "https://lumina-recorder.com"
!define OUTPUT_FILE "dist_installer\Lumina_Setup_${APP_VERSION}.exe"
!define UNINSTALL_KEY "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APP_NAME}"

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
    
    ; Enregistrement dans la base de registre. DisplayVersion sert de
    ; référence à .onInit pour détecter et proposer les mises à jour.
    WriteRegStr HKLM "Software\${APP_NAME}" "" $INSTDIR
    WriteRegStr HKLM "${UNINSTALL_KEY}" "DisplayName" "${APP_NAME}"
    WriteRegStr HKLM "${UNINSTALL_KEY}" "UninstallString" "$INSTDIR\uninstall.exe"
    WriteRegStr HKLM "${UNINSTALL_KEY}" "DisplayVersion" "${APP_VERSION}"
    WriteRegStr HKLM "${UNINSTALL_KEY}" "Publisher" "${APP_PUBLISHER}"
    WriteRegStr HKLM "${UNINSTALL_KEY}" "URLInfoAbout" "${APP_URL}"
    WriteRegStr HKLM "${UNINSTALL_KEY}" "DisplayIcon" "$INSTDIR\LuminaRecorder.exe"
    ; Taille affichée dans « Applications installées »
    ${GetSize} "$INSTDIR" "/S=0K" $0 $1 $2
    IntFmt $0 "0x%08X" $0
    WriteRegDWORD HKLM "${UNINSTALL_KEY}" "EstimatedSize" "$0"
    
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
    ; L'application ne doit pas tourner pendant qu'on efface ses fichiers
    ExecWait 'taskkill /F /IM LuminaRecorder.exe' $R2

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
    
    ; /SD IDOK : en désinstallation silencieuse (mise à jour), cette
    ; boîte se validerait toute seule au lieu de bloquer le processus
    MessageBox MB_OK "Lumina Recorder a été désinstallé avec succès." /SD IDOK
    
SectionEnd

; Fonctions personnalisées
Function .onInit
    ; Vérification de la version Windows
    ${If} ${RunningX64}
        StrCpy $INSTDIR "$PROGRAMFILES64\LuminaRecorder"
    ${Else}
        StrCpy $INSTDIR "$PROGRAMFILES\LuminaRecorder"
    ${EndIf}

    ; ---- Mise à jour d'une installation existante ----
    ; Le registre fait foi : s'il contient un désinstalleur, une version
    ; est déjà en place. On propose la mise à jour, on ferme l'application
    ; si elle tourne, puis on désinstalle l'ancienne version en silence
    ; AVANT de copier la nouvelle — sinon des fichiers retirés d'une
    ; version à l'autre resteraient orphelins dans le dossier.
    ; Les réglages (AppData) et les clés API (coffre Windows) ne sont pas
    ; touchés par la désinstallation : ils survivent à la mise à jour.
    ReadRegStr $R0 HKLM "${UNINSTALL_KEY}" "UninstallString"
    StrCmp $R0 "" fin_maj

    ReadRegStr $R1 HKLM "${UNINSTALL_KEY}" "DisplayVersion"
    MessageBox MB_YESNO|MB_ICONQUESTION \
        "${APP_NAME} $R1 est déjà installé.$\n$\nMettre à jour vers la version ${APP_VERSION} ?$\n(Vos réglages et clés API seront conservés.)" \
        IDYES faire_maj
    Abort

    faire_maj:
    ; Fermer l'application si elle tourne : ses fichiers seraient
    ; verrouillés et la copie échouerait à moitié
    ExecWait 'taskkill /F /IM LuminaRecorder.exe' $R2

    ; Réutiliser le dossier de l'installation existante
    ReadRegStr $R3 HKLM "Software\${APP_NAME}" ""
    StrCmp $R3 "" +2
    StrCpy $INSTDIR $R3

    ; _?= force le désinstalleur à travailler dans ce dossier et à
    ; s'exécuter de façon synchrone ; il ne peut alors pas s'effacer
    ; lui-même, d'où le Delete qui suit
    ExecWait '"$R0" /S _?=$INSTDIR'
    Delete "$R0"

    fin_maj:
FunctionEnd

Function .onInstSuccess
    ; Option: Lancer l'application après installation
    ; Exec "$INSTDIR\LuminaRecorder.exe"
FunctionEnd
