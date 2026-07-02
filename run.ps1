# Windows PowerShell launcher — no flags to remember.
#   .\run.ps1                                   # every site in the registry
#   .\run.ps1 Cohere                            # one site
#   .\run.ps1 Cohere -Account you@example.com   # pick the account
#   .\run.ps1 Cohere -Profile secondary         # use a second Chrome sub-profile
#   .\run.ps1 -Headless                         # run without a visible window
param(
    [string]$Site = "",
    [string]$Account = "",
    [string]$Profile = "",
    [switch]$Headless,
    [switch]$NoMap
)
$env:PYTHONUTF8 = "1"                       # emoji/arrows print fine on any console
if ($Account) { $env:SIGNUP_ACCOUNT = $Account }
if ($Profile) { $env:SIGNUP_PROFILE = $Profile }
if ($NoMap)   { $env:SIGNUP_NO_MAP  = "1" }

$argList = @()
if ($Headless) { $argList += "--headless" }
if ($Site)     { $argList += $Site }

python run.py @argList
