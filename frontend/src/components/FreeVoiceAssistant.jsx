import React, { useEffect, useRef, useState } from "react";

/** CONFIG (you can also pass as props) */
const DEFAULT_WAKE_NAME = "Nova";                    // say: "hey nova"
const DEFAULT_ENDPOINT  = "/query";                  // your Flask route
const WAKE_REGEX_BASE   = "(hey|ok|okay)\\s+(nova|nora|noah)"; // tweak if you rename
const ONE_SHOT_MAX_MS   = 12000;

export default function FreeVoiceAssistant({
  wakeName = DEFAULT_WAKE_NAME,
  endpoint = DEFAULT_ENDPOINT
}) {
  const [uiState, setUiState] = useState("needs-arming"); // needs-arming | idle | awake | listening | thinking | speaking | error
  const [lastHeard, setLastHeard] = useState("");
  const [armed, setArmed] = useState(false);

  const recognizerRef = useRef(null);
  const stopWakeLoopRef = useRef(() => {});
  const abortOneShotRef = useRef(() => {});
  const SR = window.webkitSpeechRecognition || window.SpeechRecognition;
  const WAKE_REGEX = new RegExp("\\b" + WAKE_REGEX_BASE + "\\b", "i");

  // ---- speech synthesis
  function speak(text) {
    try {
      const u = new SpeechSynthesisUtterance(text || "Done.");
      u.lang = "en-US";
      u.rate = 1;
      window.speechSynthesis.cancel();
      window.speechSynthesis.speak(u);
    } catch (e) {}
  }

  // ---- summarize Flask JSON into a voice-friendly sentence
  function summarize(json) {
    if (!json) return "I didn't catch that.";
    if (json.error && json.hint) return `${json.error}. ${json.hint}`;
    if (json.error) return json.error;

    if (json.count !== undefined) return `You have ${json.count} appointments.`;

    if (json.appointment !== undefined) {
      const a = json.appointment;
      if (!a) return "No upcoming appointments.";
      const t = (a.start_time || "").slice(0,5);
      return `Your next appointment is ${a.description || "untitled"} on ${a.date} at ${t}.`;
    }

    if (Array.isArray(json.appointments)) {
      const n = json.appointments.length;
      if (n === 0) return "No appointments found for that time.";
      const a = json.appointments[0];
      return `You have ${n} appointment${n>1?"s":""}. First is ${a.description || "untitled"} at ${(a.start_time||"").slice(0,5)} on ${a.date}.`;
    }

    if (json.proposals?.length) {
      const p = json.proposals[0];
      return `That time is busy. I can do ${(p.start_time||"").slice(0,5)} to ${(p.end_time||"").slice(0,5)} on ${p.date}.`;
    }

    if (json.reminder) {
      const r = json.reminder;
      return `Okay, reminder set: ${r.title} at ${(r.time||"").slice(0,5)} on ${r.date||"the date"}.`;
    }

    if (json.created) return "Appointment created.";
    if (json.updated) return "Appointment updated.";
    if (json.deleted) return "Appointment deleted.";

    return "Done.";
  }

  // ---- backend call
  async function callBackend(text) {
    if (!text) return `Hi, I’m ${wakeName}. What should I do?`;
    try {
      const res = await fetch(endpoint, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ query: text })
      });
      const json = await res.json();
      return summarize(json);
    } catch {
      return "Sorry, I couldn't reach the server.";
    }
  }

  // ---- one-shot listener (grabs the command after wake)
  function oneShotListen() {
    return new Promise((resolve) => {
      if (!SR) { resolve(""); return; }
      const r = new SR();
      r.lang = "en-US";
      r.interimResults = false;
      r.maxAlternatives = 1;

      let done = false;
      abortOneShotRef.current = () => { try { r.abort(); } catch {}; if (!done) { done = true; resolve(""); } };

      r.onresult = (e) => {
        if (!done) {
          done = true;
          resolve(e.results[0][0].transcript || "");
        }
      };
      r.onerror = () => { if (!done) { done = true; resolve(""); } };
      r.onend   = () => { if (!done) { done = true; resolve(""); } };

      try { r.start(); } catch { resolve(""); }
      setUiState("listening");
      setTimeout(() => abortOneShotRef.current?.(), ONE_SHOT_MAX_MS);
    });
  }

  // ---- handle one voice turn
  async function handleTurn(immediateCmd) {
    let command = (immediateCmd || "").trim();
    if (!command) command = await oneShotListen();
    setLastHeard(command || "");
    setUiState("thinking");
    const reply = await callBackend(command || "");
    setUiState("speaking");
    speak(reply);
    await new Promise(r => setTimeout(r, Math.min(4000, Math.max(1200, reply.length * 25))));
    setUiState("idle");
  }

  // ---- wake loop (continuous interim recognition)
  async function startWakeLoop() {
    if (!SR) { setUiState("error"); return; }
    const r = new SR();
    recognizerRef.current = r;
    r.lang = "en-US";
    r.continuous = true;
    r.interimResults = true;

    let buffer = "";
    let cooling = false;

    r.onresult = async (e) => {
      let text = "";
      for (let i = e.resultIndex; i < e.results.length; i++) text += e.results[i][0].transcript + " ";
      buffer = (buffer + " " + text).trim();

      const m = buffer.match(WAKE_REGEX);
      if (m && !cooling) {
        cooling = true;
        setUiState("awake");
        // grab the tail after the wake phrase as immediate command (if spoken in one breath)
        const after = buffer.slice(buffer.search(WAKE_REGEX) + m[0].length).trim();
        buffer = "";
        try { r.abort(); } catch {}
        await handleTurn(after);
        // re-arm
        startWakeLoop();
        setTimeout(() => (cooling = false), 500);
      }
    };

    r.onerror = () => { try { r.abort(); } catch {}; setTimeout(() => startWakeLoop(), 800); };
    r.onend   = () => { if (recognizerRef.current === r) { try { r.start(); } catch {} } };

    try {
      await r.start();
      stopWakeLoopRef.current = () => { try { r.abort(); } catch {} };
      setUiState("idle");
      setArmed(true);
    } catch {
      setUiState("error");
    }
  }

  // we require a click to arm mic on most browsers — no auto start
  useEffect(() => {
    return () => {
      stopWakeLoopRef.current?.();
      abortOneShotRef.current?.();
      recognizerRef.current = null;
    };
  }, []);

  return (
    <div className="va-wrap">
      <button
        className={`mic ${uiState} ${armed ? "armed" : "disarmed"}`}
        aria-label="Voice Assistant"
        onClick={async () => {
          if (!armed) {
            await startWakeLoop();         // ask for mic permission & arm continuous wake
            return;
          }
          // tap-to-talk: handle a single turn immediately
          stopWakeLoopRef.current?.();
          await handleTurn();
          startWakeLoop();
        }}
        title={!armed ? `Enable mic to say “Hey ${wakeName}”` : `Say “Hey ${wakeName}” or tap to talk`}
      >
        <div className="ring"></div>
        <div className="dot"></div>
        <div className="bars"><span/><span/><span/><span/></div>
        <div className="spinner"></div>
        <div className="ripples"></div>
      </button>

      <div className="status">
        <strong>{armed ? `Say “Hey ${wakeName}”` : "Click the mic to enable voice"}</strong>
        <div className="sub">
          {uiState === "idle" && "Listening for the wake phrase."}
          {uiState === "awake" && "I’m here."}
          {uiState === "listening" && "Listening…"}
          {uiState === "thinking" && "Thinking…"}
          {uiState === "speaking" && "Speaking…"}
          {uiState === "needs-arming" && "Click once to grant mic access."}
          {uiState === "error" && "SpeechRecognition isn’t available here; tap-to-talk may still work."}
        </div>
        {lastHeard && <div className="heard">You: “{lastHeard}”</div>}
      </div>
    </div>
  );
}
