// hooks/useSpeech.js
// Minimal, battle-tested SpeechRecognition wrapper with graceful fallbacks.

export function isSpeechRecognitionSupported() {
  // Chrome/Edge: SpeechRecognition; Safari: webkitSpeechRecognition (spotty)
  return !!(window.SpeechRecognition || window.webkitSpeechRecognition);
}

export default function useSpeech({ lang = 'en-US', grammar = [] , interim = true, onFinal } = {}) {
  let recognition = null;
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  const SGL = window.SpeechGrammarList || window.webkitSpeechGrammarList;

  const state = {
    listening: false,
    interimText: '',
    finalText: '',
    _onend: null,
  };

  function buildGrammar() {
    if (!SGL || !grammar?.length) return null;
    const gl = new SGL();
    // Simple JSGF from phrases (optional but helps recognition stability for our domain)
    const jsgf = `#JSGF V1.0; grammar sched; public <cmd> = ${grammar.map(p => p.replace(/\s+/g,' ')).join(' | ')} ;`;
    try {
      gl.addFromString(jsgf, 1);
      return gl;
    } catch { return null; }
  }

  function start() {
    if (!SR) throw new Error('SpeechRecognition not supported in this browser.');
    if (state.listening) return;

    recognition = new SR();
    recognition.lang = lang;
    recognition.continuous = false;            // push-to-talk UX
    recognition.interimResults = !!interim;    // show partial text
    recognition.maxAlternatives = 1;

    const gl = buildGrammar();
    if (gl) recognition.grammars = gl;

    state.listening = true;
    state.interimText = '';
    state.finalText = '';

    recognition.onresult = (e) => {
      let text = '';
      for (let i = e.resultIndex; i < e.results.length; i++) {
        const res = e.results[i];
        if (res.isFinal) {
          text += res[0].transcript;
          state.finalText = (state.finalText + ' ' + text).trim();
        } else {
          state.interimText = res[0].transcript;
        }
      }
    };

    recognition.onerror = (_e) => {
      // swallow common benign errors (no-speech, aborted)
    };

    recognition.onend = () => {
      state.listening = false;
      const text = (state.finalText || state.interimText || '').trim();
      if (text && typeof onFinal === 'function') onFinal(text);
    };

    recognition.start();
  }

  function stop() {
    try { recognition?.stop(); } catch {}
  }

  return {
    get listening() { return state.listening; },
    get interimText() { return state.interimText; },
    get finalText() { return state.finalText; },
    start, stop,
  };
}
