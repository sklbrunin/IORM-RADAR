<#
  Agenda (ou remove / consulta) a rotina diária de enriquecimento no Agendador de Tarefas do Windows.

  Instalar (uma vez, na pasta do projeto):
      powershell -ExecutionPolicy Bypass -File coleta\agendar_enriquecimento_windows.ps1
      powershell -ExecutionPolicy Bypass -File coleta\agendar_enriquecimento_windows.ps1 -Horario 07:30
  Ver situação:   ... -Status
  Remover:        ... -Remover

  A tarefa roda com o SEU usuário (não precisa de administrador), só enquanto você estiver
  logado. Se o computador estiver desligado no horário, roda assim que ligar
  (StartWhenAvailable). Saída de cada execução: dados\logs\agendado.out.log.
#>
param(
    [string]$Horario = "07:30",
    [int]$Meta = 30,
    [switch]$Status,
    [switch]$Remover
)

$nome = "IORM Radar - Enriquecimento diário"
$raiz = Split-Path -Parent $PSScriptRoot

if ($Status) {
    $t = Get-ScheduledTask -TaskName $nome -ErrorAction SilentlyContinue
    if (-not $t) { Write-Output "NÃO INSTALADA: a tarefa '$nome' não existe."; exit 1 }
    $i = Get-ScheduledTaskInfo -TaskName $nome
    Write-Output "Tarefa: $nome  |  Estado: $($t.State)"
    Write-Output "Última execução: $($i.LastRunTime)  |  Resultado: $($i.LastTaskResult) (0 = sucesso)"
    Write-Output "Próxima execução: $($i.NextRunTime)"
    exit 0
}
if ($Remover) {
    Unregister-ScheduledTask -TaskName $nome -Confirm:$false -ErrorAction SilentlyContinue
    Write-Output "Tarefa '$nome' removida."
    exit 0
}

$python = (Get-Command python -ErrorAction Stop).Source
New-Item -ItemType Directory -Force -Path (Join-Path $raiz "dados\logs") | Out-Null
$comando = "/c cd /d `"$raiz`" && `"$python`" coleta\enriquecimento_diario.py --agendada --meta $Meta >> dados\logs\agendado.out.log 2>&1"
$acao = New-ScheduledTaskAction -Execute "cmd.exe" -Argument $comando -WorkingDirectory $raiz
$gatilho = New-ScheduledTaskTrigger -Daily -At $Horario
$config = New-ScheduledTaskSettingsSet -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Hours 1) `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
Register-ScheduledTask -TaskName $nome -Action $acao -Trigger $gatilho -Settings $config `
    -Description "IORM Radar: enriquece ate $Meta empresas por dia (Receita Federal + busca web dentro da cota)." -Force | Out-Null
Write-Output "Tarefa '$nome' instalada: todos os dias às $Horario (meta $Meta)."
Write-Output "Conferir:  powershell -ExecutionPolicy Bypass -File coleta\agendar_enriquecimento_windows.ps1 -Status"
Write-Output "Testar já: Start-ScheduledTask -TaskName '$nome'"
