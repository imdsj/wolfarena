param(
  [Parameter(Mandatory = $true)]
  [string]$InputPath,

  [Parameter(Mandatory = $true)]
  [string]$OutputPath,

  [int]$Width = 390,
  [int]$Height = 844
)

Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing

$resolvedInput = (Resolve-Path -LiteralPath $InputPath).Path
$resolvedOutputParent = Split-Path -Parent $OutputPath
if (-not (Test-Path -LiteralPath $resolvedOutputParent)) {
  New-Item -ItemType Directory -Path $resolvedOutputParent -Force | Out-Null
}

$browser = [System.Windows.Forms.WebBrowser]::new()
$browser.ScriptErrorsSuppressed = $true
$browser.ScrollBarsEnabled = $true
$browser.Width = $Width
$browser.Height = $Height

$form = [System.Windows.Forms.Form]::new()
$form.ClientSize = [System.Drawing.Size]::new($Width, $Height)
$form.ShowInTaskbar = $false
$form.FormBorderStyle = [System.Windows.Forms.FormBorderStyle]::None
$form.Controls.Add($browser)

$completed = $false
$browser.add_DocumentCompleted({
  param($sender, $eventArgs)
  if ($eventArgs.Url.AbsoluteUri -eq $resolvedInputUri.AbsoluteUri) {
    $script:completed = $true
  }
})

$resolvedInputUri = [System.Uri]::new($resolvedInput)
$form.Show()
$browser.Navigate($resolvedInputUri)

$deadline = [DateTime]::UtcNow.AddSeconds(10)
while (-not $completed -and [DateTime]::UtcNow -lt $deadline) {
  [System.Windows.Forms.Application]::DoEvents()
  Start-Sleep -Milliseconds 50
}
if (-not $completed) {
  $form.Dispose()
  throw "Timed out while loading $resolvedInput"
}

for ($index = 0; $index -lt 20; $index++) {
  [System.Windows.Forms.Application]::DoEvents()
  Start-Sleep -Milliseconds 50
}

$bitmap = [System.Drawing.Bitmap]::new($Width, $Height)
$graphics = [System.Drawing.Graphics]::FromImage($bitmap)
$graphics.Clear([System.Drawing.Color]::White)
$browser.DrawToBitmap(
  $bitmap,
  [System.Drawing.Rectangle]::new(0, 0, $Width, $Height)
)
$bitmap.Save($OutputPath, [System.Drawing.Imaging.ImageFormat]::Png)
$graphics.Dispose()
$bitmap.Dispose()
$form.Dispose()

Write-Output "Rendered $OutputPath"
