$ErrorActionPreference = 'Stop'
$root = Join-Path $PSScriptRoot '.build-tools'
New-Item -ItemType Directory -Force -Path $root | Out-Null
function Fetch($url, $path, $hash) {
    if (!(Test-Path -LiteralPath $path)) { Invoke-WebRequest -Uri $url -OutFile $path }
    if ($hash -and (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash -ne $hash) {
        throw "Checksum mismatch: $path"
    }
}
$assets = Invoke-RestMethod 'https://api.adoptium.net/v3/assets/latest/17/hotspot?architecture=x64&image_type=jdk&os=windows'
$package = $assets[0].binary.package
Fetch $package.link (Join-Path $root 'jdk.zip') $package.checksum
if (!(Test-Path (Join-Path $root 'jdk'))) {
    Expand-Archive -LiteralPath (Join-Path $root 'jdk.zip') -DestinationPath (Join-Path $root 'jdk')
}
$env:JAVA_HOME = (Get-ChildItem (Join-Path $root 'jdk') -Directory | Select-Object -First 1).FullName
$env:PATH = "$env:JAVA_HOME\bin;$env:PATH"
[xml]$repository = (Invoke-WebRequest 'https://dl.google.com/android/repository/repository2-1.xml').Content
$tool = $repository.SelectNodes("//*[local-name()='remotePackage']") | Where-Object {
    $_.path -eq 'cmdline-tools;latest'
} | Select-Object -First 1
$archive = $tool.SelectNodes(".//*[local-name()='archive']") | Where-Object { $_.'host-os' -eq 'windows' } | Select-Object -First 1
$sdk = Join-Path $root 'sdk'
Fetch ('https://dl.google.com/android/repository/'+$archive.complete.url) (Join-Path $root 'sdk-tools.zip') $null
if (!(Test-Path (Join-Path $sdk 'cmdline-tools/bin/sdkmanager.bat'))) {
    Expand-Archive -LiteralPath (Join-Path $root 'sdk-tools.zip') -DestinationPath $sdk
}
$manager = Join-Path $sdk 'cmdline-tools/bin/android.exe'
foreach ($name in @('platforms/android-36', 'build-tools/35.0.0', 'platform-tools')) {
    & $manager "--sdk=$sdk" sdk install $name
    if ($LASTEXITCODE -ne 0) { throw "Android SDK installation failed: $name" }
}
Fetch 'https://services.gradle.org/distributions/gradle-8.13-bin.zip' (Join-Path $root 'gradle.zip') $null
if (!(Test-Path (Join-Path $root 'gradle/gradle-8.13/bin/gradle.bat'))) {
    Expand-Archive -LiteralPath (Join-Path $root 'gradle.zip') -DestinationPath (Join-Path $root 'gradle')
}
$env:ANDROID_HOME = $sdk
$env:GRADLE_USER_HOME = Join-Path $env:TEMP 'casorin-fountain-gradle'
# Gradle test worker argument files do not reliably support Cyrillic paths on Windows.
$buildRoot = Join-Path $env:TEMP ('casorin-fountain-build-'+[guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Force -Path (Join-Path $buildRoot 'app') | Out-Null
foreach ($file in @('build.gradle','settings.gradle','gradle.properties')) {
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot $file) -Destination $buildRoot
}
Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'app/build.gradle') -Destination (Join-Path $buildRoot 'app')
Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'app/src') -Destination (Join-Path $buildRoot 'app') -Recurse
& (Join-Path $root 'gradle/gradle-8.13/bin/gradle.bat') -p $buildRoot --no-daemon testDebugUnitTest assembleDebug
if ($LASTEXITCODE -ne 0) { throw 'Android build failed' }
$output = Join-Path $PSScriptRoot 'dist'
New-Item -ItemType Directory -Force -Path $output | Out-Null
Copy-Item -LiteralPath (Join-Path $buildRoot 'app/build/outputs/apk/debug/app-debug.apk') -Destination (Join-Path $output 'Fountain-History-0.5.1-test.apk') -Force
Write-Host "APK: $output\Fountain-History-0.5.1-test.apk"
