# Find metadata objects by name pattern and print their tables/fields.
param([string]$Pattern = 'Zarplat', [string]$Out = 'find.txt')

[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8

function Prop($obj, $name) {
    return [System.__ComObject].InvokeMember($name, [System.Reflection.BindingFlags]::GetProperty, $null, $obj, $null)
}

$c = New-Object -ComObject 'V83.COMConnector'
$cn = $c.Connect('File="D:\Users\magsp\1C-Bases\promizol-spb";Usr="";Pwd="";')
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
