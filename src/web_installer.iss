; Скрипт Web Installer для RAG Chat Bot
; Программа вшита, Ollama и модели скачиваются из сети.

#define MyAppName "RAG Chat Bot"
#define MyAppVersion "1.0"
#define MyAppPublisher "My Company"
#define MyAppExeName "RAGChatBot.exe"

[Setup]
AppId={{A29C8288-E5F6-4A90-1234-567890ABCDEF}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\{#MyAppName}
DisableProgramGroupPage=yes
; Имя итогового файла установщика
OutputDir=Output
OutputBaseFilename=RAGChat_WebInstaller
Compression=lzma
SolidCompression=yes
WizardStyle=modern

[Languages]
Name: "russian"; MessagesFile: "compiler:Languages\Russian.isl"

[Files]
; ВШИВАЕМ твой EXE файл (он должен лежать в папке src/dist)
Source: "dist\{#MyAppExeName}"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Run]
; Запуск приложения после установки
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent

[Code]
// --- Глобальные переменные ---
var
  DownloadPage: TOutputProgressWizardPage;

// --- Вспомогательные функции ---

function ExecCmd(Command: String): Integer;
var
  ResultCode: Integer;
begin
  // Запуск скрытой консольной команды
  Exec(ExpandConstant('{cmd}'), '/C ' + Command, '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  Result := ResultCode;
end;

function ExecOllamaCmd(Command: String): Integer;
var
  ResultCode: Integer;
begin
  // Запуск команды с видимым окном (для скачивания моделей)
  Exec(ExpandConstant('{cmd}'), '/C ' + Command, '', SW_SHOW, ewWaitUntilTerminated, ResultCode);
  Result := ResultCode;
end;

// Проверка: Установлена ли Ollama?
function IsOllamaInstalled: Boolean;
var
  ResultCode: Integer;
begin
  if Exec(ExpandConstant('{cmd}'), '/C ollama --version', '', SW_HIDE, ewWaitUntilTerminated, ResultCode) then
    Result := (ResultCode = 0)
  else
    Result := False;
end;

// Проверка размера файла (чтобы не запускать битый инсталлер)
function GetFileSize(const Filename: String): Int64;
var
  FindRec: TFindRec;
begin
  Result := 0;
  if FindFirst(Filename, FindRec) then
  begin
    Result := FindRec.Size;
    FindClose(FindRec);
  end;
end;

// --- Основная логика ---

procedure CurStepChanged(CurStep: TSetupStep);
var
  InstallerPath: String;
  DownloadUrl: String;
  ResultCode: Integer;
  FileSize: Int64;
begin
  if CurStep = ssPostInstall then
  begin
    // 1. ПРОВЕРКА И СКАЧИВАНИЕ OLLAMA
    if not IsOllamaInstalled then
    begin
      if MsgBox('Для работы требуется Ollama. Скачать и установить сейчас?', mbConfirmation, MB_YESNO) = IDYES then
      begin
        DownloadPage := CreateOutputProgressPage('Загрузка компонентов', 'Подождите, идет скачивание...');
        DownloadPage.Show;
        try
          DownloadUrl := 'https://ollama.com/download/OllamaSetup.exe';
          InstallerPath := ExpandConstant('{tmp}\OllamaSetup.exe');
          
          DownloadPage.SetText('Скачивание Ollama (около 200 МБ)...', '');
          
          // Используем curl с флагами -L (редиректы) и -f (ошибка при 404)
          // Мы скачиваем во временную папку
          ExecCmd('curl -L -f -o "' + InstallerPath + '" ' + DownloadUrl);
          
          // Проверяем, скачался ли файл (размер > 10 МБ)
          FileSize := GetFileSize(InstallerPath);
          if FileSize < 10000000 then
          begin
             MsgBox('Ошибка скачивания: Файл OllamaSetup.exe слишком маленький или поврежден. Попробуйте установить Ollama вручную.', mbError, MB_OK);
          end
          else
          begin
             // Запускаем установку
             DownloadPage.SetText('Установка Ollama...', '');
             Exec(InstallerPath, '/silent', '', SW_SHOW, ewWaitUntilTerminated, ResultCode);
          end;
          
        finally
          DownloadPage.Hide;
        end;
      end;
    end;

    // 2. СКАЧИВАНИЕ МОДЕЛЕЙ
    // Спрашиваем пользователя
    if MsgBox('Скачать и настроить нейросети (Llama 3.1 + Embeddings)?' #13#10 'Это займет около 5 ГБ трафика.', mbConfirmation, MB_YESNO) = IDYES then
    begin
        // Запускаем сервер Ollama в фоне (обязательно)
        ExecCmd('start /B ollama serve');
        Sleep(4000); // Даем время на старт

        MsgBox('Сейчас откроется консоль для загрузки моделей.' #13#10 'Пожалуйста, дождитесь, пока окно закроется само.', mbInformation, MB_OK);

        // Скачиваем Llama 3.1
        ExecOllamaCmd('ollama pull llama3.1');
        
        // Скачиваем Nomic Embed Text
        ExecOllamaCmd('ollama pull nomic-embed-text');
    end;
  end;
end;