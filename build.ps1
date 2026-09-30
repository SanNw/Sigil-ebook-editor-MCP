$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
$csc = Get-ChildItem "$env:WINDIR\Microsoft.NET\Framework*\v4.0.30319\csc.exe" |
    Sort-Object FullName -Descending | Select-Object -First 1
if (-not $csc) { throw ".NET Framework C# compiler not found" }
& $csc.FullName /nologo /target:winexe "/out:$root\SigilMCPExternal.exe" `
    /reference:System.Management.dll /reference:System.Windows.Forms.dll `
    "$root\SigilMCPExternal.cs"
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
