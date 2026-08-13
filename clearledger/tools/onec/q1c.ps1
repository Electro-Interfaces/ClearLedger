# Выполнить запросы 1С к файловой базе через COM и напечатать строки как JSON.
# Usage (только x86 PowerShell!):
#   q1c.ps1 -QueryDir <каталог с *.txt> [-Limit N]
#   q1c.ps1 -QueryFile <один .txt> [-Limit N]
#
# Текст запроса лежит в отдельном UTF-8 файле: кириллицы в самом .ps1 нет, поэтому
# возни с BOM/ANSI не возникает. Строки печатаются МАССИВАМИ значений — имена колонок
# у COM-коллекции 1С доступны только через русскоязычные свойства; порядок значений
# равен порядку полей в тексте запроса, имена подставляет разбирающая сторона.
param(
    [string]$QueryFile,
    [string]$QueryDir,
    [int]$Limit = 0,
    [string]$Base = 'D:\Users\magsp\1C-Bases\promizol-spb'
)

[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8

$files = @()
if ($QueryDir) { $files = Get-ChildItem -Path $QueryDir -Filter '*.txt' | Sort-Object Name | ForEach-Object { $_.FullName } }
if ($QueryFile) { $files += $QueryFile }
if (-not $files) { Write-Output 'no query files'; exit 1 }

$c = New-Object -ComObject 'V83.COMConnector'
$cn = $c.Connect('File="' + $Base + '";Usr="";Pwd="";')

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
