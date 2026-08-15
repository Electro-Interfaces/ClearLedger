# Перепись базы 1С: какие объекты конфигурации реально содержат данные.
# Отвечает на вопрос «всё ли мы забрали»: без неё полнота выгрузки проверяется
# перебором догадок, а незабранный непустой регистр не виден вовсе.
#
# Usage (только x86 PowerShell!):
#   census.ps1 -Base "D:\temp\rti-1c" [-Out census.txt]
#   census.ps1 -Srvr "srv:1541" -Ref "buh" -User "Читатель" [-Out census.txt]
#
# Печатает строки «ТипОбъекта.Имя<TAB>количество» только для непустых объектов.
param(
    [string]$Out = 'census.txt',
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

$c = New-Object -ComObject 'V83.COMConnector'
$cn = $c.Connect($Conn)
$md = Prop $cn 'Metadata'

# Коллекция метаданных → префикс таблицы в языке запросов.
$kinds = @(
    @('Documents', 'Document'),
    @('Catalogs', 'Catalog'),
    @('InformationRegisters', 'InformationRegister'),
    @('AccumulationRegisters', 'AccumulationRegister'),
    @('AccountingRegisters', 'AccountingRegister'),
    @('ChartsOfAccounts', 'ChartOfAccounts'),
    @('ChartsOfCharacteristicTypes', 'ChartOfCharacteristicTypes'),
    @('BusinessProcesses', 'BusinessProcess'),
    @('Tasks', 'Task')
)

$sw = New-Object System.IO.StreamWriter($Out, $false, [System.Text.UTF8Encoding]::new($false))
foreach ($k in $kinds) {
    $coll = $k[0]
    $prefix = $k[1]
    foreach ($it in (Prop $md $coll)) {
        $name = Prop $it 'Name'
        $table = $prefix + '.' + $name
        try {
            $q = $cn.NewObject('Query')
            # COUNT(*) по пустой таблице отрабатывает мгновенно, поэтому перебор
            # всей конфигурации укладывается в минуты.
            $q.Text = 'SELECT COUNT(*) AS N FROM ' + $table
            $t = $q.Execute().Unload()
            $n = $t.Get(0).Get(0)
            if ($n -gt 0) { $sw.WriteLine($table + "`t" + $n) }
        } catch {
            $sw.WriteLine($table + "`tFAILED " + $_.Exception.Message)
        }
    }
}
$sw.Close()
Write-Output "done -> $Out"
