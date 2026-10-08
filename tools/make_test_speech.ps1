Add-Type -AssemblyName System.Speech
$voice = New-Object System.Speech.Synthesis.SpeechSynthesizer
$out = Join-Path $PSScriptRoot "voice_test_speech.wav"
$voice.SetOutputToWaveFile($out)
$voice.Speak("Hello Zyra, this is a voice pipeline test. Open Chrome and analyze example dot com.")
$voice.Dispose()
Write-Output "WROTE $out"
