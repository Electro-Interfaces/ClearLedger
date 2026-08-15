# Состав конкретных объектов конфигурации: реквизиты, измерения, ресурсы, табличные части.
# Список объектов читается из файла (UTF-8, по строке «Тип.Имя»), потому что кириллицу
# в параметр из bash передать нельзя — она приезжает битой.
#
# Usage (только x86 PowerShell!):
#   meta-of.ps1 -List objects.txt -Out meta.txt -Base "D:\temp\rti-1c"
param(
    [Parameter(Mandatory = $true)][string]$List,
    [string]$Out = 'meta.txt',
    [string]$Base,
    [string]$Srvr,
    [string]$Ref,
    [string]$User = '',
    [string]$Password,
    [string]$Conn
)

[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8

function Prop($obj, $name) {
    return [System.__ComObject].InvokeMember($name, [System.Reflection.BindingFlags]::GetProperty, $null, $obj, $null)
}

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

$kinds = @{
    'Document' = 'Documents'; 'Catalog' = 'Catalogs'
    'InformationRegister' = 'InformationRegisters'; 'AccumulationRegister' = 'AccumulationRegisters'
    'AccountingRegister' = 'AccountingRegisters'; 'ChartOfAccounts' = 'ChartsOfAccounts'
    'ChartOfCharacteristicTypes' = 'ChartsOfCharacteristicTypes'
}

$c = New-Object -ComObject 'V83.COMConnector'
$cn = $c.Connect($Conn)
$md = Prop $cn 'Metadata'

$sw = New-Object System.IO.StreamWriter($Out, $false, [System.Text.UTF8Encoding]::new($false))
foreach ($line in [System.IO.File]::ReadAllLines($List, [System.Text.Encoding]::UTF8)) {
    $line = $line.Trim()
    if (-not $line -or $line.StartsWith('#')) { continue }
    $parts = $line.Split('.')
    if ($parts.Count -lt 2) { continue }
    $coll = $kinds[$parts[0]]
    if (-not $coll) { $sw.WriteLine("== $line | неизвестный тип"); continue }
    $found = $null
    foreach ($it in (Prop $md $coll)) {
        if ((Prop $it 'Name') -eq $parts[1]) { $found = $it; break }
    }
    if (-not $found) { $sw.WriteLine("== $line | НЕ НАЙДЕН"); continue }
    $syn = ''
    try { $syn = Prop $found 'Synonym' } catch { }
    $sw.WriteLine("== $line | $syn")
    foreach ($group in @('Dimensions', 'Resources', 'Attributes')) {
        $names = @()
        try { foreach ($f in (Prop $found $group)) { $names += (Prop $f 'Name') } } catch { continue }
        if ($names.Count) { $sw.WriteLine("   ${group}: " + ($names -join ', ')) }
    }
    try {
        foreach ($ts in (Prop $found 'TabularSections')) {
            $cols = @()
            foreach ($f in (Prop $ts 'Attributes')) { $cols += (Prop $f 'Name') }
            $sw.WriteLine("   TS " + (Prop $ts 'Name') + ": " + ($cols -join ', '))
        }
    } catch { }
}
$sw.Close()
Write-Output "done -> $Out"
