# Troca a SUPABASE_KEY do .env sem mostrar a chave na tela nem gravá-la no histórico.
# Uso (na pasta do projeto):  powershell -ExecutionPolicy Bypass -File tools\trocar_chave_supabase.ps1
$ErrorActionPreference = 'Stop'
$envPath = Join-Path (Split-Path $PSScriptRoot -Parent) '.env'
if (-not (Test-Path $envPath)) { Write-Host "Nao achei $envPath" -ForegroundColor Red; exit 1 }

Write-Host "Cole a NOVA chave secreta (sb_secret_...) e aperte Enter. Ela nao aparece na tela." -ForegroundColor Cyan
$sec = Read-Host -AsSecureString "Chave"
$bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($sec)
try { $k = [Runtime.InteropServices.Marshal]::PtrToStringAuto($bstr).Trim() }
finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr) }

if ($k -notmatch '^sb_secret_\S{10,}$') { Write-Host "Isso nao parece uma chave sb_secret_. Nada foi alterado." -ForegroundColor Red; exit 1 }

$url = (Get-Content $envPath | Where-Object { $_ -like 'SUPABASE_URL=*' } | Select-Object -First 1) -replace '^SUPABASE_URL=', '' -replace '["'']', ''
if ($url) {
    try {
        # User-Agent neutro: o Supabase recusa chave secreta quando o pedido parece vir de navegador ("Mozilla/...").
        [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
        Invoke-WebRequest -UseBasicParsing -UserAgent 'quant-office-sync' -Uri "$($url.Trim())/rest/v1/agents_status?select=agent_id&limit=1" `
            -Headers @{ apikey = $k; Authorization = "Bearer $k" } | Out-Null
        Write-Host "Supabase aceitou a chave." -ForegroundColor Green
    } catch {
        $det = $_.ErrorDetails.Message
        Write-Host "Supabase RECUSOU a chave ($($_.Exception.Message)) $det" -ForegroundColor Red
        Write-Host "Nada foi alterado." -ForegroundColor Red; exit 1
    }
}

$found = $false
$linhas = Get-Content $envPath | ForEach-Object {
    if ($_ -like 'SUPABASE_KEY=*') { $found = $true; "SUPABASE_KEY=$k" } else { $_ }
}
if (-not $found) { $linhas = @($linhas) + "SUPABASE_KEY=$k" }
[IO.File]::WriteAllLines($envPath, [string[]]$linhas, (New-Object Text.UTF8Encoding $false))
$k = $null
Write-Host "OK: SUPABASE_KEY atualizada em $envPath" -ForegroundColor Green
