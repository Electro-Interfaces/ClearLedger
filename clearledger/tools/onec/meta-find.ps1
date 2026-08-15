# Find metadata objects by name pattern and print their tables/fields.
# Строка соединения — как у q1c.ps1: -Base <путь> либо -Srvr/-Ref, либо готовая -Conn.
param(
    [string]$Pattern = 'Zarplat',
    [string]$Out = 'find.txt',
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

$sw = New-Object System.IO.StreamWriter($Out, $false, [System.Text.UTF8Encoding]::new($false))
$colls = @('Documents', 'Catalogs', 'InformationRegisters', 'AccumulationRegisters', 'ChartsOfCalculationTypes')
foreach ($coll in $colls) {
    foreach ($it in (Prop $md $coll)) {
        $name = Prop $it 'Name'
        if ($name -notmatch $Pattern) { continue }
        $syn = ''
        try { $syn = Prop $it 'Synonym' } catch { }
        $sw.WriteLine("== $coll.$name | $syn")
        foreach ($group in @('Dimensions', 'Resources', 'Attributes', 'TabularSections')) {
            $names = @()
            try { foreach ($f in (Prop $it $group)) { $names += (Prop $f 'Name') } } catch { continue }
            if ($names.Count) { $sw.WriteLine("   ${group}: " + ($names -join ', ')) }
        }
        try {
            foreach ($ts in (Prop $it 'TabularSections')) {
                $cols = @()
                foreach ($f in (Prop $ts 'Attributes')) { $cols += (Prop $f 'Name') }
                $sw.WriteLine("   TS " + (Prop $ts 'Name') + ": " + ($cols -join ', '))
            }
        } catch { }
    }
}
$sw.Close()
Write-Output "done -> $Out"
