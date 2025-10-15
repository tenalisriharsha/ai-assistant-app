# voice_assistant.py
import queue
import sounddevice as sd
import json
from vosk import Model, KaldiRecognizer
import requests
import pyttsx3
from flask import Flask, request, jsonify
import io
import wave

# --- Settings ---
WAKE_WORD = "nova"
SERVER_URL = "http://127.0.0.1:5000/query"
MODEL_PATH = "vosk-model-small-en-us-0.15"
DEVICE = None  # default mic

# Load model
model = Model(MODEL_PATH)
recognizer = KaldiRecognizer(model, 16000)
q = queue.Queue()

# Text-to-speech
engine = pyttsx3.init()

def speak(text):
    print(f"Bot: {text}")
    engine.say(text)
    engine.runAndWait()

def callback(indata, frames, time, status):
    if status:
        print(status)
    q.put(bytes(indata))

def listen_for_command():
    print("🎙 Listening for wake word… Say 'Nova'")
    while True:
        data = q.get()
        if recognizer.AcceptWaveform(data):
            result = json.loads(recognizer.Result())
            text = result.get("text", "").lower()
            print("👂 Heard:", text)
            if WAKE_WORD in text:
                speak("Yes? I'm listening.")
                return listen_and_transcribe()

def listen_and_transcribe():
    print("🎤 Speak your command now...")
    transcription = ""
    timeout_counter = 0

    while True:
        try:
            data = q.get(timeout=5)
            if recognizer.AcceptWaveform(data):
                result = json.loads(recognizer.Result())
                partial = result.get("text", "")
                if partial:
                    transcription += " " + partial
            else:
                partial = json.loads(recognizer.PartialResult()).get("partial", "")
                print("…", partial.ljust(60), end="\r")
        except queue.Empty:
            timeout_counter += 1
            if timeout_counter > 2:
                speak("Sorry, I didn’t hear anything.")
                return None
    return transcription.strip()

def send_to_server(query):
    try:
        # Send to Flask backend
        res = requests.post(SERVER_URL, json={"query": query})
        data = res.json()
        reply = "Your command has been sent to the assistant."
        # speak(reply)  # No longer speak the reply

        # Inject command into browser (React UI)
        try:
            import webbrowser
            import urllib.parse
            url = f"http://localhost:3000/?q={urllib.parse.quote(query)}"
            webbrowser.open_new_tab(url)
        except Exception as browser_error:
            print("⚠️ Could not open browser:", browser_error)

    except Exception as e:
        print("❌ Error sending to server:", e)
        speak("Something went wrong.")

def main():
    with sd.RawInputStream(samplerate=16000, blocksize=8000, device=DEVICE,
                           dtype='int16', channels=1, callback=callback):
        while True:
            user_query = listen_for_command()
            if user_query:
                print(f"🧠 You said: {user_query}")
                send_to_server(user_query)

# --- Flask App for API Endpoints ---
app = Flask(__name__)

@app.route("/voice-command", methods=["GET"])
def voice_command():
    try:
        with sd.RawInputStream(samplerate=16000, blocksize=8000, device=DEVICE,
                               dtype='int16', channels=1, callback=callback):
            print("🎤 One-time passive listening...")
            transcription = listen_and_transcribe()
            if transcription:
                send_to_server(transcription)
                return jsonify({"message": "Command received", "query": transcription}), 200
            else:
                return jsonify({"message": "No command detected"}), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/upload-audio", methods=["POST"])
def upload_audio():
    try:
        audio_file = request.files["audio"]
        audio_bytes = audio_file.read()

        with wave.open(io.BytesIO(audio_bytes), "rb") as wf:
            if wf.getnchannels() != 1 or wf.getsampwidth() != 2 or wf.getframerate() != 16000:
                return jsonify({"error": "Invalid audio format. Must be mono, 16-bit, 16kHz."}), 400

            recognizer = KaldiRecognizer(model, wf.getframerate())
            transcription = ""

            while True:
                data = wf.readframes(4000)
                if len(data) == 0:
                    break
                if recognizer.AcceptWaveform(data):
                    result = json.loads(recognizer.Result())
                    transcription += " " + result.get("text", "")
            transcription = transcription.strip()
            if transcription:
                send_to_server(transcription)
                return jsonify({"message": "Audio processed", "query": transcription}), 200
            else:
                return jsonify({"error": "No speech detected"}), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    import threading

    flask_thread = threading.Thread(target=lambda: app.run(port=5001))
    flask_thread.daemon = True
    flask_thread.start()

    main()
