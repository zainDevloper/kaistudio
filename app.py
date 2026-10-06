# KAI AI STUDIO — Flask backend
# pip install flask flask-cors requests
import asyncio
import os
import edge_tts
import os, base64, uuid, random, requests
from datetime import datetime
from pathlib import Path
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS


# ---------- CONFIG ----------
# Set the token as an environment variable (recommended):
#   Windows: set CF_API_TOKEN=xxxx    Mac/Linux: export CF_API_TOKEN=xxxx
CF_API_TOKEN = os.environ.get("CF_API_TOKEN", "")
CF_ACCOUNT_ID = os.environ.get("CF_ACCOUNT_ID", "37ec054fc29dc61b9a1e487da5d86e9c")

CF_MODEL      = "@cf/black-forest-labs/flux-1-schnell"
CF_ENDPOINT   = f"https://api.cloudflare.com/client/v4/accounts/{CF_ACCOUNT_ID}/ai/run/{CF_MODEL}"
GENERATED_DIR = Path("generated")
GENERATED_DIR.mkdir(exist_ok=True)

app = Flask(__name__, static_folder=".", static_url_path="")
CORS(app)

STYLE_SUFFIXES = {
    "realistic": ", ultra realistic, photorealistic, 8k, highly detailed, sharp focus, professional photography",
    "3d":        ", 3d render, octane render, cinematic lighting, subsurface scattering, ray tracing, ultra detailed",
    "anime":     ", anime style, studio ghibli, vibrant colors, cel shaded, detailed background",
    "cyberpunk": ", cyberpunk, neon lights, futuristic city, blade runner style, rain, moody atmosphere",
    "fantasy":   ", fantasy art, epic, magical, intricate details, concept art, dramatic lighting",
    "none":      "",
}
#ASPECT_MAP = {"1:1": (1024, 1024), "16:9": (1024, 576), "9:16": (576, 1024), "4:3": (1024, 768)}

PROMPTS = [
    "a cyberpunk samurai in neon Tokyo rain", "floating islands with waterfalls at sunset",
    "a lion wearing a spacesuit on Mars", "an ancient library inside a giant tree",
    "a steampunk dragon made of brass gears", "a crystal castle under aurora sky",
    "a robot reading a book in a garden", "a phoenix rising from digital code",
    "a whale swimming through clouds", "an astronaut riding a horse on Mars",
    "a futuristic mosque with neon calligraphy", "a tiger made of fire in a bamboo forest",
    "a skyline of floating temples", "a girl with galaxy hair", "a samurai cat with katana",
    "a dragon sleeping on a mountain of gold", "a bioluminescent forest at night",
    "a giant mecha standing over a city", "an ancient ruin in a desert with a portal",
    "a library of infinite books floating in space",
]

# ==================== TEXT-TO-SPEECH ====================
VOICE_MAP = {
    "male":   {"en": "en-US-GuyNeural",      "ur": "ur-PK-AsadNeural"},
    "female": {"en": "en-US-AriaNeural",     "ur": "ur-PK-UzmaNeural"},
}

AUDIO_DIR = Path("generated/audio")
AUDIO_DIR.mkdir(parents=True, exist_ok=True)


@app.route("/api/speak", methods=["POST"])
def speak():
    """Convert text to MP3 using Microsoft Edge Neural TTS."""
    data = request.get_json(silent=True) or {}
    text = (data.get("text") or "").strip()
    gender = data.get("gender", "female").lower()
    lang = data.get("lang", "en").lower()

    if not text:
        return jsonify(success=False, error="Text is empty."), 400
    if len(text) > 2000:
        return jsonify(success=False, error="Text too long (max 2000)."), 400
    if gender not in VOICE_MAP:
        gender = "female"
    if lang not in ("en", "ur"):
        lang = "en"

    voice = VOICE_MAP[gender][lang]
    print(f"🔊 TTS request: [{gender}/{lang}] {voice} | {text[:60]}...")

    filename = f"tts_{datetime.now():%Y%m%d_%H%M%S}_{uuid.uuid4().hex[:6]}.mp3"
    filepath = AUDIO_DIR / filename

    async def _gen():
        comm = edge_tts.Communicate(text, voice)
        await comm.save(str(filepath))

    try:
        asyncio.run(_gen())
        print(f"✅ Audio saved: {filepath}")
        return jsonify(
            success=True,
            audio_url=f"/audio/{filename}",
            filename=filename,
            voice=voice,
            gender=gender,
            lang=lang,
        )
    except Exception as e:
        print(f"❌ TTS error: {e}")
        return jsonify(success=False, error=f"TTS failed: {str(e)}"), 500


@app.route("/audio/<filename>")
def serve_audio(filename):
    """Serve generated audio files."""
    return send_from_directory(AUDIO_DIR, filename)


@app.route("/api/audio/<filename>", methods=["DELETE"])
def delete_audio(filename):
    p = safe_path(filename)
    if not p:
        return jsonify(success=False, error="Bad filename"), 400
    p = AUDIO_DIR / filename
    if not p.exists():
        return jsonify(success=False, error="Not found"), 404
    p.unlink()
    return jsonify(success=True)
def safe_path(filename):
    """Reject anything that isn't a plain file name inside generated/."""
    if filename != Path(filename).name:
        return None
    return GENERATED_DIR / filename


@app.route("/")
def index():
    return send_from_directory(".", "index.html")


@app.route("/api/generate", methods=["POST"])
def generate():
    data = request.get_json(silent=True) or {}
    prompt = (data.get("prompt") or "").strip()
    style = data.get("style", "none")
    aspect = data.get("aspect", "1:1")
    try:
        steps = max(1, min(8, int(data.get("steps", 4))))
    except (TypeError, ValueError):
        steps = 4

    if not prompt:
        return jsonify(success=False, error="Prompt is empty."), 400
    if len(prompt) > 2000:
        return jsonify(success=False, error="Prompt is too long (max 2000 characters)."), 400

    print(f"🎨 New request: {prompt[:60]}...")
    print(f"🎭 Style: {style} | 📐 Aspect: {aspect} | ⚙️ Steps: {steps}")

    enhanced = prompt + STYLE_SUFFIXES.get(style, "")
  

    try:
        r = requests.post(
            CF_ENDPOINT,
            headers={"Authorization": f"Bearer {CF_API_TOKEN}", "Content-Type": "application/json"},
            json={"prompt": enhanced, "steps": steps},
            timeout=60,
        )
        if r.status_code != 200:
            print(f"❌ Error: HTTP {r.status_code} — {r.text[:500]}")
            return jsonify(success=False, error=f"Image service returned HTTP {r.status_code}."), 502

        body = r.json()
        if not body.get("success"):
            msg = "; ".join(e.get("message", "") for e in body.get("errors", [])) or "Generation failed."
            print(f"❌ Error: {msg}")
            return jsonify(success=False, error=msg), 502

        img_bytes = base64.b64decode(body["result"]["image"])
        filename = f"kai_{datetime.now():%Y%m%d_%H%M%S}_{uuid.uuid4().hex[:6]}.png"
        (GENERATED_DIR / filename).write_bytes(img_bytes)
        print(f"✅ Saved: {GENERATED_DIR / filename}")

        return jsonify(success=True, image_url=f"/image/{filename}", filename=filename,
                       prompt_used=enhanced, style=style, aspect=aspect)

    except requests.exceptions.Timeout:
        print("❌ Error: timeout")
        return jsonify(success=False, error="The request timed out. Please try again."), 504
    except Exception as e:  # network, JSON, base64 errors
        print(f"❌ Error: {e}")
        return jsonify(success=False, error="Something went wrong on the server."), 500


@app.route("/image/<filename>")
def serve_image(filename):
    return send_from_directory(GENERATED_DIR, filename)


@app.route("/api/image/<filename>", methods=["DELETE"])
def delete_image(filename):
    p = safe_path(filename)
    if not p or not p.exists():
        return jsonify(success=False, error="Not found."), 404
    p.unlink()
    return jsonify(success=True)


@app.route("/api/gallery")
def gallery():
    files = sorted(GENERATED_DIR.glob("kai_*.png"), key=lambda f: f.stat().st_mtime, reverse=True)[:50]
    return jsonify(success=True, images=[
        {"filename": f.name, "url": f"/image/{f.name}",
         "created": datetime.fromtimestamp(f.stat().st_mtime).isoformat(), "size": f.stat().st_size}
        for f in files])


@app.route("/api/health")
def health():
    return jsonify(status="ok", service="KAI AI Studio")


@app.route("/api/prompts")
def prompts():
    return jsonify(random.sample(PROMPTS, len(PROMPTS)))


if __name__ == "__main__":
    print("=" * 60)
    print("  🎨 KAI AI STUDIO — Backend Starting")
    print("=" * 60)
    print(f"  🖼️  Model: {CF_MODEL}")
    print(f"  📁 Generated folder: {GENERATED_DIR.absolute()}")
    if CF_API_TOKEN.startswith("PASTE"):
        print("  ⚠️  CF_API_TOKEN is not set — generation will fail")
    print("  🌐 Open in browser: http://localhost:5000")
    print("  🛑 Press Ctrl+C to stop")
    print("=" * 60)
    app.run(host="0.0.0.0", port=5000, debug=False)
