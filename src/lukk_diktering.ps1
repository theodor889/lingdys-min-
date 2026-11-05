param(
    [Parameter(Mandatory = $true)][string]$LogFile
)
# Skriveflyt: close the Windows voice typing window (Win+H) by pressing its
# close button through UI Automation. Windows has no key for this.

function Write-Log([string]$message) {
    try {
        $line = (Get-Date -Format 'HH:mm:ss') + '  [F7] ' + $message
        Add-Content -LiteralPath $LogFile -Value $line -Encoding UTF8
    } catch {}
}

try {
    Add-Type -AssemblyName UIAutomationClient
    Add-Type -AssemblyName UIAutomationTypes
} catch {
    Write-Log ('UI Automation mangler: ' + $_.Exception.Message)
    exit 1
}

$AE = [System.Windows.Automation.AutomationElement]
$Scope = [System.Windows.Automation.TreeScope]
$True_ = [System.Windows.Automation.Condition]::TrueCondition
$buttonCond = New-Object System.Windows.Automation.PropertyCondition(
    $AE::ControlTypeProperty, [System.Windows.Automation.ControlType]::Button)

# Processes that host the voice typing panel on Windows 10/11.
$hostIds = @(Get-Process -Name TextInputHost, ShellExperienceHost, VoiceAccess -ErrorAction SilentlyContinue |
    ForEach-Object { $_.Id })

# Log every visible top-level window once, so the voice typing window can be found.
foreach ($w in $AE::RootElement.FindAll($Scope::Children, $True_)) {
    try {
        $c = $w.Current
        $proc = (Get-Process -Id $c.ProcessId -ErrorAction SilentlyContinue).ProcessName
        Write-Log ('alle: "' + $c.Name + '" klasse=' + $c.ClassName + ' prosess=' + $proc)
    } catch {}
}

$closeNames = '^(Lukk|Close|Lukk taleinntasting|Close voice typing|Skjul|Hide)\b'
$closed = $false

foreach ($window in $AE::RootElement.FindAll($Scope::Children, $True_)) {
    $info = $window.Current
    $isVoice = ($hostIds -contains $info.ProcessId) -or
               ($info.Name -match 'tale|voice|dikt|dictat')
    if (-not $isVoice) { continue }
    Write-Log ('vindu: "' + $info.Name + '" klasse=' + $info.ClassName + ' pid=' + $info.ProcessId)

    $buttons = $window.FindAll($Scope::Descendants, $buttonCond)
    foreach ($button in $buttons) {
        $b = $button.Current
        Write-Log ('   knapp: "' + $b.Name + '" id=' + $b.AutomationId)
        if ($closed) { continue }
        if ($b.Name -match $closeNames -or $b.AutomationId -match 'Close|Dismiss') {
            try {
                $pattern = $button.GetCurrentPattern([System.Windows.Automation.InvokePattern]::Pattern)
                $pattern.Invoke()
                $closed = $true
                Write-Log ('   -> trykket "' + $b.Name + '"')
            } catch {
                Write-Log ('   -> kunne ikke trykke: ' + $_.Exception.Message)
            }
        }
    }
}

if (-not $closed) { Write-Log 'fant ingen lukk-knapp' }
