import { useRef, useCallback, useEffect } from 'react';

export function isSpeechRecognitionSupported() {
  return !!(window.SpeechRecognition || window.webkitSpeechRecognition);
}

export default function useSpeech({ lang = 'en-US', grammar = [], interim = true, onFinal } = {}) {
  const recognitionRef = useRef(null);
  const stateRef = useRef({
    listening: false,
    interimText: '',
    finalText: '',
  });
  const callbacksRef = useRef({ onFinal });
  callbacksRef.current.onFinal = onFinal;

  const buildGrammar = useCallback(() => {
    const SGL = window.SpeechGrammarList || window.webkitSpeechGrammarList;
    if (!SGL || !grammar?.length) return null;
    const gl = new SGL();
    const jsgf = `#JSGF V1.0; grammar sched; public <cmd> = ${grammar.map(p => p.replace(/\s+/g,' ')).join(' | ')} ;`;
    try {
      gl.addFromString(jsgf, 1);
      return gl;
    } catch { return null; }
  }, [grammar]);

  const stop = useCallback(() => {
    try {
      recognitionRef.current?.stop();
    } catch {}
  }, []);

  const start = useCallback(() => {
    const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SR) throw new Error('SpeechRecognition not supported in this browser.');
    if (stateRef.current.listening) return;

    // Abort any previous instance
    try { recognitionRef.current?.abort(); } catch {}

    const recognition = new SR();
    recognition.lang = lang;
    recognition.continuous = false;
    recognition.interimResults = !!interim;
    recognition.maxAlternatives = 1;

    const gl = buildGrammar();
    if (gl) recognition.grammars = gl;

    stateRef.current.listening = true;
    stateRef.current.interimText = '';
    stateRef.current.finalText = '';

    recognition.onresult = (e) => {
      let text = '';
      for (let i = e.resultIndex; i < e.results.length; i++) {
        const res = e.results[i];
        if (res.isFinal) {
          text += res[0].transcript;
          stateRef.current.finalText = (stateRef.current.finalText + ' ' + text).trim();
        } else {
          stateRef.current.interimText = res[0].transcript;
        }
      }
    };

    recognition.onerror = () => {};

    recognition.onend = () => {
      stateRef.current.listening = false;
      const text = (stateRef.current.finalText || stateRef.current.interimText || '').trim();
      if (text && typeof callbacksRef.current.onFinal === 'function') {
        callbacksRef.current.onFinal(text);
      }
    };

    recognitionRef.current = recognition;
    recognition.start();
  }, [lang, interim, buildGrammar]);

  useEffect(() => {
    return () => {
      try { recognitionRef.current?.abort(); } catch {}
    };
  }, []);

  return {
    get listening() { return stateRef.current.listening; },
    get interimText() { return stateRef.current.interimText; },
    get finalText() { return stateRef.current.finalText; },
    start,
    stop,
  };
}
