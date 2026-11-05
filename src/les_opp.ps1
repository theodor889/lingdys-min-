param(
    [Parameter(Mandatory = $true)][string]$TextFile,
    [Parameter(Mandatory = $true)][string]$LogFile,
    [string]$Language = 'nb'
)
# Skriveflyt: read text aloud with a Norwegian voice when Windows has one.
# 1) Modern Windows voices (for example "Microsoft Jon", Norwegian)
# 2) Older SAPI voices with Norwegian language
# 3) Default voice

function Write-Log([string]$message) {
    try {
        $line = (Get-Date -Format 'HH:mm:ss') + '  [stemme] ' + $message
        Add-Content -LiteralPath $LogFile -Value $line -Encoding UTF8
    } catch {}
}

$text = Get-Content -Raw -Encoding UTF8 -LiteralPath $TextFile
Remove-Item -LiteralPath $TextFile -ErrorAction SilentlyContinue
if (-not $text) { exit 0 }

function Test-Norwegian([string]$lang) {
    # Name kept for simplicity: true when the voice matches the chosen language.
    if ($Language -eq 'en') { return ($lang -like 'en*') }
    return ($lang -like 'nb*' -or $lang -like 'no*' -or $lang -like 'nn*')
}
Write-Log ('sprak: ' + $Language)

# ---------- 1) Modern Windows voices (WinRT) ----------
try {
    Add-Type -AssemblyName System.Runtime.WindowsRuntime
    $null = [Windows.Media.SpeechSynthesis.SpeechSynthesizer, Windows.Media.SpeechSynthesis, ContentType = WindowsRuntime]
    $null = [Windows.Storage.Streams.DataReader, Windows.Storage.Streams, ContentType = WindowsRuntime]

    $all = [Windows.Media.SpeechSynthesis.SpeechSynthesizer]::AllVoices
    Write-Log ('nye stemmer: ' + (($all | ForEach-Object { $_.DisplayName + ' (' + $_.Language + ')' }) -join ', '))
    $voice = $all | Where-Object { Test-Norwegian $_.Language } | Select-Object -First 1

    if ($voice) {
        $asTask = ([System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {
            $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and
            $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1'
        })[0]
        function Await($operation, [Type]$type) {
            $task = $asTask.MakeGenericMethod($type).Invoke($null, @($operation))
            $null = $task.Wait(-1)
            return $task.Result
        }

        $synth = New-Object Windows.Media.SpeechSynthesis.SpeechSynthesizer
        $synth.Voice = $voice
        $stream = Await ($synth.SynthesizeTextToStreamAsync($text)) ([Windows.Media.SpeechSynthesis.SpeechSynthesisStream])
        $size = [uint32]$stream.Size
        $reader = New-Object Windows.Storage.Streams.DataReader($stream.GetInputStreamAt(0))
        $null = Await ($reader.LoadAsync($size)) ([uint32])
        $bytes = New-Object byte[] $size
        $reader.ReadBytes($bytes)

        $wav = Join-Path $env:TEMP ('skriveflyt-' + [guid]::NewGuid().ToString() + '.wav')
        [System.IO.File]::WriteAllBytes($wav, $bytes)
        Write-Log ('bruker ' + $voice.DisplayName)
        try {
            (New-Object System.Media.SoundPlayer $wav).PlaySync()
        } finally {
            Remove-Item -LiteralPath $wav -ErrorAction SilentlyContinue
        }
        exit 0
    }
} catch {
    Write-Log ('nye stemmer feilet: ' + $_.Exception.Message)
}

# ---------- 2) and 3) Older SAPI voices ----------
try {
    Add-Type -AssemblyName System.Speech
    $speaker = New-Object System.Speech.Synthesis.SpeechSynthesizer
    $installed = $speaker.GetInstalledVoices() | Where-Object { $_.Enabled }
    Write-Log ('gamle stemmer: ' + (($installed | ForEach-Object { $_.VoiceInfo.Name + ' (' + $_.VoiceInfo.Culture.Name + ')' }) -join ', '))
    # Microsoft voices first. Lingit/Cerence voices belong to Lingdys and may
    # stay silent outside it, so they are used last.
    $old = $installed | Where-Object { Test-Norwegian $_.VoiceInfo.Culture.Name } |
        Sort-Object { if ($_.VoiceInfo.Name -like 'Microsoft*') { 0 } elseif ($_.VoiceInfo.Name -match 'Lingit|Cerence|CereProc') { 2 } else { 1 } } |
        Select-Object -First 1
    if ($old) {
        $speaker.SelectVoice($old.VoiceInfo.Name)
        Write-Log ('bruker ' + $old.VoiceInfo.Name)
    } else {
        Write-Log ('INGEN STEMME FOR ' + $Language + ' - bruker standardstemmen')
    }
    $speaker.Speak($text)
} catch {
    Write-Log ('opplesing feilet: ' + $_.Exception.Message)
}
