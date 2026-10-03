# The Android app (2026-10-03, owner). Builds the APK that wraps the site
# (Trusted Web Activity) and publishes it on the website:
#   live/static/owlnest.apk          the file members download
#   live/static/apk.json             its version (the app and the landing read it)
#   live/static/assetlinks.json      the proof the APK may own the site
#
#   .\build_apk.ps1                  # same version, rebuild
#   .\build_apk.ps1 -Bump            # new version (versionCode + 1): the app
#                                    # on members' phones offers the update
#
# Nothing here has to change when the website changes: the app shows the
# live site. A new APK is only needed for the icon, the name, or Android
# itself. The signing key (owlnest.jks + keystore.env) must stay the same
# forever: an APK signed with another key cannot install over the old one.
param([switch]$Bump)
$ErrorActionPreference = "Stop"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$live = Split-Path -Parent $here
Set-Location $here
$env:JAVA_HOME = "C:\tools\jdk-17.0.20.1+1"
$env:ANDROID_HOME = "C:\tools\android"
$env:Path = "$env:JAVA_HOME\bin;$env:ANDROID_HOME\platform-tools;$env:Path"
foreach ($ln in Get-Content (Join-Path $here "keystore.env")) {
    if ($ln -match '^KEYSTORE_PASSWORD=(.+)$') { $env:BUBBLEWRAP_KEYSTORE_PASSWORD = $Matches[1] }
    if ($ln -match '^KEY_PASSWORD=(.+)$') { $env:BUBBLEWRAP_KEY_PASSWORD = $Matches[1] }
}
$mf = Join-Path $here "twa-manifest.json"
$m = Get-Content $mf -Raw | ConvertFrom-Json
if ($Bump) {
    $m.appVersionCode = [int]$m.appVersionCode + 1
    $m.appVersionName = "1." + ($m.appVersionCode - 1)
    $m.appVersion = $m.appVersionName
}
# the app starts on /app?v=<versionCode>: that is how the site knows which
# APK is running and can offer a newer one
$m.startUrl = "/app?v=" + $m.appVersionCode
# no BOM: bubblewrap's JSON reader chokes on the one Set-Content -Encoding utf8 writes
[System.IO.File]::WriteAllText($mf, ($m | ConvertTo-Json -Depth 6), (New-Object System.Text.UTF8Encoding($false)))
Write-Host ("building OwlNest " + $m.appVersionName + " (code " + $m.appVersionCode + ")")
$bw = Join-Path $env:APPDATA "npm\bubblewrap.cmd"
# Two steps, both without prompts: `update --skipVersionUpgrade` regenerates
# the Android project from the manifest (the version is already the
# manifest's), then `build` compiles and signs (passwords from the env).
# (bubblewrap writes progress to stderr; under "Stop" PowerShell 5.1 would
# treat that as a failure, so the strict mode is lifted around the calls)
$ErrorActionPreference = "Continue"
& $bw update --skipVersionUpgrade --manifest $mf 2>&1 | ForEach-Object { "$_" }
$rc = $LASTEXITCODE
$ErrorActionPreference = "Stop"
if ($rc -ne 0) { throw "bubblewrap update failed ($rc)" }
# `bubblewrap build` cannot find gradlew.bat on this box (it runs it with a
# trimmed environment), so the same three steps are run here by hand:
# gradle, zipalign, apksigner - exactly what bubblewrap would do.
$ErrorActionPreference = "Continue"
& .\gradlew.bat assembleRelease --stacktrace 2>&1 | ForEach-Object { "$_" } | Select-Object -Last 15
$rc = $LASTEXITCODE
$ErrorActionPreference = "Stop"
if ($rc -ne 0) { throw "gradle failed ($rc)" }
$unsigned = Join-Path $here "app\build\outputs\apk\release\app-release-unsigned.apk"
if (-not (Test-Path $unsigned)) { throw "no unsigned APK produced" }
$bt = Join-Path $env:ANDROID_HOME "build-tools\34.0.0"
$aligned = Join-Path $here "app-release-aligned.apk"
$apk = Join-Path $here "app-release-signed.apk"
& (Join-Path $bt "zipalign.exe") -f -p 4 $unsigned $aligned
if ($LASTEXITCODE -ne 0) { throw "zipalign failed" }
& (Join-Path $bt "apksigner.bat") sign --ks (Join-Path $here "owlnest.jks") --ks-key-alias owlnest --ks-pass ("pass:" + $env:BUBBLEWRAP_KEYSTORE_PASSWORD) --key-pass ("pass:" + $env:BUBBLEWRAP_KEY_PASSWORD) --out $apk $aligned
if ($LASTEXITCODE -ne 0) { throw "apksigner failed" }
& (Join-Path $bt "apksigner.bat") verify --print-certs $apk | Select-Object -First 2
if (-not (Test-Path $apk)) { throw "no signed APK produced" }
$static = Join-Path $live "static"
Copy-Item $apk (Join-Path $static "owlnest.apk") -Force
# the proof: the SHA-256 of the signing certificate
$fp = (& keytool -list -v -keystore (Join-Path $here "owlnest.jks") -alias owlnest -storepass $env:BUBBLEWRAP_KEYSTORE_PASSWORD 2>$null | Select-String "SHA256:" | Select-Object -First 1).ToString().Split(":", 2)[1].Trim()
$al = @(@{ relation = @("delegate_permission/common.handle_all_urls"); target = @{ namespace = "android_app"; package_name = $m.packageId; sha256_cert_fingerprints = @($fp) } })
ConvertTo-Json $al -Depth 6 | Set-Content -Path (Join-Path $static "assetlinks.json") -Encoding ascii
$sha = (Get-FileHash $apk -Algorithm SHA256).Hash.ToLower()
$info = @{ version = $m.appVersionName; versionCode = [int]$m.appVersionCode; size = (Get-Item $apk).Length; sha256 = $sha
           date = (Get-Date).ToUniversalTime().ToString("yyyy-MM-dd"); package = $m.packageId; url = "/owlnest.apk" }
ConvertTo-Json $info | Set-Content -Path (Join-Path $static "apk.json") -Encoding ascii
Write-Host ("published: static/owlnest.apk " + [math]::Round($info.size / 1MB, 1) + " MB, version " + $info.version + ", cert " + $fp.Substring(0, 23) + "...")
