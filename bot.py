# bot.py
import os
import json
import requests
from flask import Flask, request, jsonify, abort

# Load .env locally if present (dev only)
try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
# SECRET_PATH is used to keep webhook path unpredictable, e.g. "sk_verysecret"
SECRET_PATH = os.getenv("SECRET_PATH", "default_secret_path_please_change")

if not TELEGRAM_TOKEN or not GEMINI_API_KEY:
    raise RuntimeError("Missing TELEGRAM_TOKEN or GEMINI_API_KEY environment variable.")

BASE_TELEGRAM = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"

app = Flask(__name__)

# Helper: send message to Telegram chat
def send_telegram_message(chat_id, text, reply_to_message_id=None):
    url = f"{BASE_TELEGRAM}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "Markdown"
    }
    if reply_to_message_id:
        payload["reply_to_message_id"] = reply_to_message_id
    r = requests.post(url, json=payload, timeout=20)
    return r.ok, r.text

# Helper: call Gemini generateContent (HTTP POST). Adjust model/endpoint as needed.
def call_gemini(prompt_text):
    # Gemini v1beta generateContent method structure per your curl example
    endpoint = "https://generativelanguage.googleapis.com/v1beta/models/gemini-3-pro-preview:generateContent"
    headers = {
        "x-goog-api-key": GEMINI_API_KEY,
        "Content-Type": "application/json"
    }
    payload = {
        "contents": [
            {
                "parts": [
                    {"text": prompt_text}
                ]
            }
        ]
    }
    try:
        r = requests.post(endpoint, headers=headers, json=payload, timeout=30)
        r.raise_for_status()
        data = r.json()
        # Attempt to extract text from known structure — adapt if Google uses different path
        # This is defensive: search for any "text" fields within the response parts
        text = ""
        if isinstance(data, dict):
            # naive extraction: look for the first string in response
            def find_text(obj):
                if isinstance(obj, str):
                    return obj
                if isinstance(obj, dict):
                    for v in obj.values():
                        res = find_text(v)
                        if res:
                            return res
                if isinstance(obj, list):
                    for it in obj:
                        res = find_text(it)
                        if res:
                            return res
                return None
            maybe = find_text(data)
            text = maybe or json.dumps(data)[:1900]
        else:
            text = str(data)[:1900]
        return text
    except Exception as e:
        return f"[error calling Gemini] {str(e)}"

# Webhook receiver — Telegram will POST updates here
@app.route(f"/telegram/{SECRET_PATH}", methods=["POST"])
def telegram_webhook():
    if request.method != "POST":
        abort(405)
    try:
        update = request.get_json(force=True)
    except Exception:
        return jsonify({"ok": False}), 400

    # Basic message handling
    message = update.get("message") or update.get("edited_message")
    if not message:
        return jsonify({"ok": True})  # not a message we handle

    chat_id = message["chat"]["id"]
    text = message.get("text", "")
    message_id = message.get("message_id")

    if not text:
        send_telegram_message(chat_id, "I only understand text messages for now.", reply_to_message_id=message_id)
        return jsonify({"ok": True})

    # Optional simple command handling
    if text.startswith("/start"):
        send_telegram_message(chat_id, "Hello! I'm CYBREIGN AI. Send any question and I'll ask Gemini and reply.")
        return jsonify({"ok": True})

    # Build prompt — you can expand this logic
    prompt = f"User asked: {text}\nProvide a short helpful explanation."

    # Call Gemini
    response_text = call_gemini(prompt)

    # Respect Telegram message length limit; trim if necessary
    if len(response_text) > 4000:
        response_text = response_text[:3990] + "\n\n...[truncated]"

    ok, resp = send_telegram_message(chat_id, response_text, reply_to_message_id=message_id)
    return jsonify({"ok": ok, "raw": resp})

# One-time endpoint to set webhook from Telegram to your Render URL.
# Use it after deploy or you can call it manually from your browser/postman.
@app.route("/set_webhook", methods=["GET"])
def set_webhook():
    # You must set RENDER_EXTERNAL_URL as environment variable OR use request host
    render_url = os.getenv("RENDER_EXTERNAL_URL")  # we'll set this on Render
    if not render_url:
        # fallback to request host (useful for testing)
        host = request.host_url.rstrip("/")
        render_url = host

    webhook_url = f"{render_url}/telegram/{SECRET_PATH}"
    telegram_set_url = f"{BASE_TELEGRAM}/setWebhook"
    payload = {"url": webhook_url}
    r = requests.post(telegram_set_url, json=payload, timeout=20)
    return jsonify({"webhook_url": webhook_url, "telegram_response": r.json()})

# Keepalive route for cron pings
@app.route("/keepalive", methods=["GET"])
def keepalive():
    return "OK - CYBREIGN alive", 200

# Root
@app.route("/", methods=["GET"])
def index():
    return "CYBREIGN AI Bot Service", 200

if __name__ == "__main__":
    # for local testing only
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 5000)))
