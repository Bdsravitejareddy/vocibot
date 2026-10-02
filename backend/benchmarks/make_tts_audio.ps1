<#
  Speaks each line of the clinical benchmark cases with Windows' built-in
  voices (doctor and patient alternate voices) as 16 kHz mono WAV files:
  <OutDir>\<case>\<line>.wav. No recordings of real people are needed.
#>
param([string]$Cases = "$PSScriptRoot\clinical_note_cases.json", [string]$OutDir = "$PSScriptRoot\tts")
Add-Type -AssemblyName System.Speech
$synth = New-Object System.Speech.Synthesis.SpeechSynthesizer
$voices = $synth.GetInstalledVoices() | Where-Object { $_.Enabled } | ForEach-Object { $_.VoiceInfo.Name }
Write-Host "Voices: $($voices -join ', ')"
$doctor = ($voices | Where-Object { $_ -match "David|Mark|Guy" } | Select-Object -First 1); if (-not $doctor) { $doctor = $voices[0] }
$patient = ($voices | Where-Object { $_ -match "Zira|Hazel|Aria|Jenny" } | Select-Object -First 1); if (-not $patient) { $patient = $voices[-1] }
$format = New-Object System.Speech.AudioFormat.SpeechAudioFormatInfo(16000, [System.Speech.AudioFormat.AudioBitsPerSample]::Sixteen, [System.Speech.AudioFormat.AudioChannel]::Mono)
$cases = Get-Content $Cases -Raw | ConvertFrom-Json
foreach ($case in $cases) {
  $dir = Join-Path $OutDir $case.id
  New-Item -ItemType Directory -Force -Path $dir | Out-Null
  for ($i = 0; $i -lt $case.lines.Count; $i++) {
    # Benchmark cases alternate doctor (even lines) and patient (odd lines).
    $synth.SelectVoice($(if ($i % 2 -eq 0) { $doctor } else { $patient }))
    $synth.SetOutputToWaveFile((Join-Path $dir ("{0:D3}.wav" -f $i)), $format)
    $synth.Speak($case.lines[$i])
  }
  $synth.SetOutputToNull()
  Write-Host "$($case.id): $($case.lines.Count) lines"
}
