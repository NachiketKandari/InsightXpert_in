"use client";

import { useRef, useState, useCallback, useEffect } from "react";

export type VoiceState = "idle" | "requesting" | "listening";

function getWsBaseUrl(): string {
  // Voice auth rides on the signed `ix_session` cookie which is HttpOnly +
  // SameSite=Lax — so it WON'T travel on a cross-origin WS handshake. Use
  // the page origin and let Next's dev `rewrites()` proxy `/api/transcribe`
  // through to the backend (it preserves the cookie because, to the browser,
  // the WS is same-origin). In prod the FE/BE are colocated behind the same
  // domain so this is also correct there. Do NOT branch on NEXT_PUBLIC_API_URL.
  const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
  const base = `${proto}//${window.location.host}`;
  console.debug("[voice] WS base URL:", base);
  return base;
}

/**
 * Streams mic audio to /api/transcribe (backend WS proxy → Deepgram Nova-3).
 *
 * Accepts an `onTranscript` callback that receives the full accumulated
 * transcript (prefix + committed + interim) as it updates in real-time.
 * The consumer wires this to its textarea setter — no useEffect needed.
 */
export function useVoiceInput(onTranscript?: (text: string) => void) {
  const [voiceState, setVoiceState] = useState<VoiceState>("idle");
  const [voiceError, setVoiceError] = useState<string | null>(null);

  // Stable ref so WS handlers always see the latest callback without re-creating
  const onTranscriptRef = useRef(onTranscript);
  useEffect(() => {
    onTranscriptRef.current = onTranscript;
  });

  const wsRef = useRef<WebSocket | null>(null);
  const recorderRef = useRef<MediaRecorder | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const committedRef = useRef("");
  const interimRef = useRef("");
  const prefixRef = useRef("");
  const silenceTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const SILENCE_TIMEOUT_MS = 10_000;

  /** Recompute full transcript from prefix + committed + interim and push to consumer. */
  const emit = useCallback(() => {
    const p = prefixRef.current;
    const c = committedRef.current;
    const i = interimRef.current;
    const session = i ? (c ? `${c} ${i}` : i) : c;
    const full = session ? (p ? `${p} ${session}` : session) : p;
    onTranscriptRef.current?.(full);
  }, []);

  const clearSilenceTimer = useCallback(() => {
    if (silenceTimerRef.current) {
      clearTimeout(silenceTimerRef.current);
      silenceTimerRef.current = null;
    }
  }, []);

  const stop = useCallback(() => {
    clearSilenceTimer();

    recorderRef.current?.stop();
    streamRef.current?.getTracks().forEach((t) => t.stop());
    recorderRef.current = null;
    streamRef.current = null;

    // Absorb any in-flight interim so nothing is lost
    if (interimRef.current) {
      committedRef.current +=
        (committedRef.current ? " " : "") + interimRef.current;
      interimRef.current = "";
    }

    // Merge this session's text into the running prefix so the next
    // voice session appends rather than replacing.
    const session = committedRef.current;
    if (session) {
      prefixRef.current = prefixRef.current
        ? `${prefixRef.current} ${session}`
        : session;
    }
    committedRef.current = "";

    console.debug("[voice] stop — prefix:", prefixRef.current);

    // Final state push — full accumulated text across all sessions
    onTranscriptRef.current?.(prefixRef.current);

    wsRef.current?.close();
    wsRef.current = null;
    setVoiceState("idle");
  }, [clearSilenceTimer]);

  const start = useCallback(async () => {
    // Reset session-local state but keep prefixRef (accumulated prior text)
    committedRef.current = "";
    interimRef.current = "";
    setVoiceError(null);
    setVoiceState("requesting");

    console.debug("[voice] start — requesting mic");
    let stream: MediaStream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    } catch {
      setVoiceError("Microphone access denied");
      setVoiceState("idle");
      return;
    }

    streamRef.current = stream;

    // Build WS URL — auth is handled via session cookie sent by the browser.
    const wsUrl = new URL(`${getWsBaseUrl()}/api/transcribe`);
    console.debug("[voice] WS URL:", wsUrl.toString());

    const ws = new WebSocket(wsUrl.toString());
    wsRef.current = ws;
    ws.binaryType = "arraybuffer";

    ws.onopen = () => {
      console.debug("[voice] WS open");
      setVoiceState("listening");

      const mimeType = MediaRecorder.isTypeSupported("audio/webm;codecs=opus")
        ? "audio/webm;codecs=opus"
        : "audio/webm";
      const recorder = new MediaRecorder(stream, { mimeType });
      recorderRef.current = recorder;
      console.debug("[voice] MediaRecorder started, mimeType:", mimeType);

      recorder.addEventListener("dataavailable", (e) => {
        if (e.data.size > 0 && ws.readyState === WebSocket.OPEN) {
          ws.send(e.data);
        }
      });
      recorder.start(250);

      // Start silence timer — auto-stop if no speech within timeout
      silenceTimerRef.current = setTimeout(() => stop(), SILENCE_TIMEOUT_MS);
    };

    ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data as string);

        if (data.error) {
          setVoiceError(data.error as string);
          stop();
          return;
        }

        const transcript =
          (data?.channel?.alternatives?.[0]?.transcript as string) ?? "";

        console.debug(
          "[voice] DG message — is_final:", data.is_final,
          "speech_final:", data.speech_final,
          "transcript:", transcript.slice(0, 60),
        );

        if (data.is_final) {
          if (transcript) {
            committedRef.current +=
              (committedRef.current ? " " : "") + transcript;
          }
          interimRef.current = "";
          emit();

          // Reset silence timer — speech was detected
          if (transcript) {
            clearSilenceTimer();
            silenceTimerRef.current = setTimeout(() => stop(), SILENCE_TIMEOUT_MS);
          }
        } else if (transcript) {
          interimRef.current = transcript;
          emit();

          // Any interim speech resets the silence clock
          clearSilenceTimer();
          silenceTimerRef.current = setTimeout(() => stop(), SILENCE_TIMEOUT_MS);
        }
      } catch {
        // ignore keepalive / non-JSON frames
      }
    };

    ws.onerror = (ev) => {
      console.debug("[voice] WS error:", ev);
      setVoiceError("Voice connection failed");
      stop();
    };

    ws.onclose = (event) => {
      console.debug("[voice] WS close — code:", event.code, "reason:", event.reason);
      clearSilenceTimer();
      recorderRef.current?.stop();
      streamRef.current?.getTracks().forEach((t) => t.stop());
      recorderRef.current = null;
      streamRef.current = null;
      wsRef.current = null;
      setVoiceState("idle");

      if (event.code === 4001) {
        setVoiceError("Not authenticated — please log in again");
      } else if (event.code === 4002) {
        setVoiceError("Speech-to-text is not configured");
      }
    };
  }, [stop, emit, clearSilenceTimer]);

  /** Reset accumulated voice text — call after sending the message. */
  const clearVoiceText = useCallback(() => {
    prefixRef.current = "";
    committedRef.current = "";
    interimRef.current = "";
  }, []);

  const toggleVoice = useCallback(() => {
    if (voiceState === "idle") start();
    else stop();
  }, [voiceState, start, stop]);

  return { voiceState, voiceError, toggleVoice, clearVoiceText };
}
