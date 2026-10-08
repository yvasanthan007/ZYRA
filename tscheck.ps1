if (Test-Path desktop-ui/node_modules/typescript/bin/tsc) {
  $err = $null
  $out = desktop-ui/node_modules/typescript/bin/tsc --noEmit -p desktop-ui/tsconfig.json 2>&1
  if ($out) {
    $out | Select-Object -First 40
  } else {
    Write-Host 'tsc OK: no errors'
  }
} else {
  Write-Host 'tsc not installed'
}
