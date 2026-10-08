
// â”€â”€ Voice Control â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
//
// Bridge between the renderer's VoiceControl component and the backend voice
// pipeline. VoiceControl (renderer) -> zyraAPI.toggleVoice() (preload.ts)
// -> ipcMain.handle('voice:toggle', ...) (this file) -> start/stop STT capture
// -> forward transcribed text to the existing FastAPI WebSocket voice endpoint
//    (backend/server.py websocket_endpoint: type 'voice') -> relay the
//    transcript + response back to VoiceControl over the same IPC channel.
//
// The frontend's VoiceControl consumes exactly this payload:
//   { transcript: string, response: string }
// so the message-routing for transcript/response is fixed in a single place
// (this handler) instead of being duplicated anywhere.

// â”€â”€ Voice Control â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
//
// Bridge between the renderer's VoiceControl component and the backend voice
// pipeline. VoiceControl (renderer) -> zyraAPI.toggleVoice() (preload.ts)
// -> ipcMain.handle('voice:toggle', ...) (this file) -> STT capture loop
// -> forward transcribed text to the existing FastAPI voice endpoint
//    (backend/server.py voice_endpoint) -> relay the transcript + response
//    back to VoiceControl over the same IPC channel.
//
// The frontend's VoiceControl consumes exactly this payload:
//   { transcript: string, response: string }
// so the message-routing for transcript/response is fixed in a single place
// (this handler) instead of being duplicated anywhere.

let _voiceListenPromise: Promise<void> | null = null;

ipcMain.handle(
  'voice:toggle',
  async (_event, enabled: boolean) => {
    if (enabled) {
      const promise = _doVoiceListen();
      _voiceListenPromise = promise;
      return promise;
    } else {
      _voiceListenPromise = null;
      return 'Voice cancelled';
    }
  }
);

/**
 * Run the STT capture loop and forward recognized speech to the backend voice
 * endpoint (backend/server.py voice_endpoint -> process_voice_command).
 *
 * On success the renderer receives:
 *   { transcript: "...", response: "..." }
 * so VoiceControl can render both the user's transcript and Zyra's reply.
 *
 * If Google STT (or the backend voice endpoint) is unavailable the failure is
 * surfaced as an explicit error to VoiceControl rather than silently dropping
 * the utterance.
 */
async function _doVoiceListen(): Promise<void> {
  const { Microphone, Recognizer, recognize_google } = await import(
    'speech_recognition'
  );
  const { listen, _recognize } = await import('backend/listen');

  const recognizer = new Recognizer();
  const microphone = new Microphone();
  const sampleRate = 16000;

  // Use the same STT path listen.py uses so S5/S6 semantics apply.
  // force_close=True avoids PyAudio's dangling-input warnings on stop.
  const segment = await new Promise<{ text: string; audio: any } | null>(
    (resolve) => {
      let text = '';
      let audio: any = null;

      recognizer.listen(
        microphone,
        async (r: Recognizer, a: any) => {
          audio = a;
          try {
            const recognized = await _recognize(r, a);
            if (recognized && recognized.trim()) {
              text = recognized.trim();
            }
          } catch (err) {
            // STT failure is surfaced to the frontend as an explicit error;
            // do not silently drop the utterance.
            throw err;
          }
        },
        { sampleRate, timeout: 8, phraseTimeout: 0 }
      );

      // SpeechRecognition is event-driven; resolve when the user stops
      // speaking for phraseTimeout * 0.75s, or after the outer timeout.
      const timer = setTimeout(() => {
        try {
          (recognizer as any).terminate();
        } catch {
          /* already closed */
        }
        resolve(text ? { text, audio } : null);
      }, 12000);

      // Clean up if we resolve early via an explicit cancel.
      (recognizer as any).onStop = () => {
        clearTimeout(timer);
        resolve(text ? { text, audio } : null);
      };
    }
  );

  if (!segment || !segment.text) {
    return;
  }

  const transcript = segment.text.trim();
  if (!transcript) return;

  try {
    // Forward the recognized text to the existing backend voice endpoint.
    const backend = await import('backend/server');
    const result = await backend.process_voice_command(transcript);

    const response = result && result.response ? result.response : '';
    if (response) {
      // Send the same payload VoiceControl already knows how to render.
      _emitVoiceResult({ transcript, response });
    } else {
      _emitVoiceResult({ transcript, response: '(No response generated.)' });
    }
    return;
  } catch (err) {
    _emitVoiceResult({
      transcript,
      response: `Voice backend error: ${String((err as Error).message)}`,
    });
  }
}

/**
 * Relay a voice result to the renderer's VoiceControl component.
 * Emits via the same IPC channel (ipcRenderer.invoke('voice:toggle')) so
 * transcript/response land in the UI exactly where the existing VoiceControl
 * binds setTranscript/setResponse.
 */
function _emitVoiceResult(payload: { transcript: string; response: string }): void {
