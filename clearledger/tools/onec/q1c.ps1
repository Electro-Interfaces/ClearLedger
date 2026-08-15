# Выполнить запросы 1С через COM и напечатать строки как JSON.
# Usage (только x86 PowerShell!):
#   q1c.ps1 -QueryDir <каталог с *.txt> -Base <путь к файловой базе> [-Limit N]
#   q1c.ps1 -QueryDir <каталог> -Srvr <сервер[:порт]> -Ref <имя базы> -User <логин> [-Limit N]
#   q1c.ps1 -QueryDir <каталог> -Conn 'Srvr="...";Ref="...";Usr="...";Pwd="...";'
#
# Пароль лучше не писать в командной строке (остаётся в истории и в логах задач) —
# скрипт берёт его из переменной окружения ONEC_PWD, если -Password не задан.
#
# Текст запроса лежит в отдельном UTF-8 файле: кириллицы в самом .ps1 нет, поэтому
# возни с BOM/ANSI не возникает. Строки печатаются МАССИВАМИ значений — имена колонок
# у COM-коллекции 1С доступны только через русскоязычные свойства; порядок значений
# равен порядку полей в тексте запроса, имена подставляет разбирающая сторона.
param(
    [string]$QueryFile,
    [string]$QueryDir,
    [int]$Limit = 0,
    [string]$Base,          # файловая база: путь к каталогу
    [string]$Srvr,          # клиент-серверная: адрес сервера 1С, напр. 1c-dev-01:1541
    [string]$Ref,           # клиент-серверная: имя информационной базы в кластере
    [string]$User = '',
    [string]$Password,
    [string]$Conn           # готовая строка соединения — если задана, остальное игнорируется
)

[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8

$files = @()
if ($QueryDir) { $files = Get-ChildItem -Path $QueryDir -Filter '*.txt' | Sort-Object Name | ForEach-Object { $_.FullName } }
if ($QueryFile) { $files += $QueryFile }
if (-not $files) { Write-Output 'no query files'; exit 1 }

if (-not $Password) { $Password = $env:ONEC_PWD }
if (-not $Conn) {
    if ($Srvr -and $Ref) {
        $Conn = 'Srvr="' + $Srvr + '";Ref="' + $Ref + '";Usr="' + $User + '";Pwd="' + $Password + '";'
    } elseif ($Base) {
        $Conn = 'File="' + $Base + '";Usr="' + $User + '";Pwd="' + $Password + '";'
    } else {
        Write-Output 'нужна база: -Base <путь> либо -Srvr <сервер> -Ref <имя базы> либо -Conn <строка>'
        exit 1
    }
}
# В лог печатаем строку БЕЗ пароля: файл выгрузки живёт дольше сессии.
Write-Output ('#### connect ' + ($Conn -replace 'Pwd="[^"]*"', 'Pwd="***"'))

$c = New-Object -ComObject 'V83.COMConnector'
$cn = $c.Connect($Conn)

foreach ($f in $files) {
    $name = [System.IO.Path]::GetFileNameWithoutExtension($f)
    try {
        $q = $cn.NewObject('Query')
        $q.Text = [System.IO.File]::ReadAllText($f, [System.Text.Encoding]::UTF8)
        $t = $q.Execute().Unload()
        $total = $t.Count()
        $n = $total
        if ($Limit -gt 0 -and $n -gt $Limit) { $n = $Limit }
        $rows = @()
        for ($i = 0; $i -lt $n; $i++) {
            $r = $t.Get($i)
            $vals = @()
            $col = 0
            while ($true) {
                try { $v = $r.Get($col) } catch { break }
                if ($null -ne $v -and $v.GetType().Name -eq '__ComObject') { $v = [string]$cn.String($v) }
                $vals += $v
                $col++
            }
            $rows += , $vals
        }
        $out = [ordered]@{ query = $name; total = $total; rows = $rows }
        Write-Output ('#### ' + $name + ' total=' + $total)
        Write-Output (ConvertTo-Json $out -Depth 6 -Compress)
    } catch {
        Write-Output ('#### ' + $name + ' FAILED: ' + $_.Exception.Message)
    }
}
