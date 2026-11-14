"""Read completed replies with the local Windows speech synthesizer."""
from base64 import b64encode
import os
from pathlib import Path
import sys

from PySide6.QtCore import QObject, QProcess, Signal


SCRIPT = r"""
$ErrorActionPreference = 'Stop'
[Console]::InputEncoding = New-Object System.Text.UTF8Encoding($false)
$text = [Console]::In.ReadToEnd()
Add-Type -AssemblyName System.Speech
$speaker = New-Object System.Speech.Synthesis.SpeechSynthesizer
try {
    if ($text -match '[\u3400-\u9fff]') {
        $voice = $speaker.GetInstalledVoices() | Where-Object {
            $_.Enabled -and $_.VoiceInfo.Culture.TwoLetterISOLanguageName -eq 'zh'
        } | Select-Object -First 1
        if ($voice) { $speaker.SelectVoice($voice.VoiceInfo.Name) }
    }
    $speaker.Speak($text)
} finally {
    $speaker.Dispose()
}
"""


class ReplySpeech(QObject):
    failed = Signal(str)

    def __init__(self, parent):
        super().__init__(parent)
        self.process = QProcess(self)
        self.process.setStandardOutputFile(QProcess.nullDevice())
        self.process.setStandardErrorFile(QProcess.nullDevice())
        self.process.started.connect(self.send_text)
        self.process.finished.connect(self.finished)
        self.process.errorOccurred.connect(self.process_error)
        self.text = b''
        self.stopping = False

    def speak(self, text):
        self.stop()
        if sys.platform != 'win32' or self.process.state() != QProcess.NotRunning:
            return
        self.text = text[:4000].encode('utf-8')
        self.stopping = False
        directory = Path(os.environ.get('SystemRoot', r'C:\Windows'))
        program = directory / 'System32/WindowsPowerShell/v1.0/powershell.exe'
        command = b64encode(SCRIPT.encode('utf-16-le')).decode('ascii')
        self.process.start(str(program), ['-NoLogo', '-NoProfile', '-NonInteractive',
                                          '-WindowStyle', 'Hidden', '-EncodedCommand', command])

    def send_text(self):
        self.process.write(self.text)
        self.text = b''
        self.process.closeWriteChannel()

    def finished(self, code, _status):
        if code and not self.stopping:
            self.failed.emit('朗读失败，请检查 Windows 语音设置。')

    def process_error(self, error):
        if error == QProcess.FailedToStart and not self.stopping:
            self.text = b''
            self.failed.emit('无法启动 Windows 本地语音。')

    def stop(self):
        self.stopping = True
        self.text = b''
        if self.process.state() != QProcess.NotRunning:
            self.process.kill()
            self.process.waitForFinished(150)
