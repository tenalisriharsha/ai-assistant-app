// components/MicButton.jsx
import React, { useEffect, useState } from 'react';
import useSpeech, { isSpeechRecognitionSupported } from '../hooks/useSpeech';

export default function MicButton({ onTranscript, onFinal, lang = 'en-US' }) {
  const [supported] = useState(isSpeechRecognitionSupported());
  const [lastHeard, setLastHeard] = useState('');
  const phrases = [
    // domain hints; totally optional
    'what is my availability today',
    'find a 60 minute free slot tomorrow',
    'create a meeting at 2 pm today',
    'move standup to 3 pm',
    'cancel my 4 pm appointment',
    'remind me at 6 pm to call mom',
  ];

  const speech = useSpeech({
    lang,
    grammar: phrases,
    interim: true,
    onFinal: (text) => {
      setLastHeard(text);
      // Send a plain string for maximum compatibility with handlers that call .trim()
      if (onTranscript) onTranscript(text);
      if (onFinal) onFinal(text);
    }
  });

  useEffect(() => {
    function onKey(e) {
      // Hold-to-talk with Space bar if not focused on an input
      const target = e.target;
      const typing = ['INPUT','TEXTAREA'].includes(target?.tagName) || target?.isContentEditable;
      if (typing) return;
      if (e.code === 'Space') {
        e.preventDefault();
        if (e.type === 'keydown' && !speech.listening) speech.start();
        if (e.type === 'keyup' && speech.listening) speech.stop();
      }
    }
    window.addEventListener('keydown', onKey);
    window.addEventListener('keyup', onKey);
    return () => {
      window.removeEventListener('keydown', onKey);
      window.removeEventListener('keyup', onKey);
    };
    // eslint-disable-next-line
  }, []);

  if (!supported) {
    return (
      <button
        type="button"
        aria-label="Voice recognition not supported"
        title="Voice not supported in this browser"
        className="mic-btn mic-unsupported"
        onClick={() => alert('This browser does not support Web Speech. Use Chrome/Edge, or we can add a Whisper fallback.')}
      >
        🎙️
      </button>
    );
  }

  return (
    <div className="mic-wrap">
      <button
        type="button"
        aria-label={speech.listening ? "Listening for voice input" : "Press and hold to speak"}
        className={`mic-btn ${speech.listening ? 'listening' : ''}`}
        onMouseDown={() => speech.start()}
        onMouseUp={() => speech.stop()}
        onTouchStart={(e) => { e.preventDefault(); speech.start(); }}
        onTouchEnd={() => speech.stop()}
        title="Hold to talk (or press Space)"
      >
        {speech.listening ? '🟢 Listening…' : '🎙️ Hold to talk'}
      </button>
      <div className="mic-caption">
        {speech.listening ? (speech.interimText || '…') : (lastHeard ? `Heard: “${lastHeard}”` : 'Speak a command')}
      </div>
    </div>
  );
}
