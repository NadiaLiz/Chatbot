import os
import unicodedata
import requests
import firebase_admin
from firebase_admin import credentials, firestore
from transformers import AutoTokenizer, AutoModelForCausalLM
from flask import Flask, request
import torch

VERIFY_TOKEN = os.getenv("VERIFY_TOKEN", "mi_token_unico_12345")
PHONE_ID     = "622356997632753"
WHATSAPP_API = f"https://graph.facebook.com/v13.0/{PHONE_ID}/messages"
ACCESS_TOKEN = os.getenv("ACCESS_TOKEN", "EAAJqQiKe1jgBOZCsZAt2kb66NTV0Ppr3sKQ7iAAi5wAj2WGZC7lT7AnneyKZBFxygSC6SWlZAgIjnLkHZBePFgE5D6DrcSXGHTZCzVyoqgnC8I1EtQtYoqs2ELDeHDqf1foCAx38ctAXZAHRFImNIHaZAfLMNalZCKvMaRRze7UzgTwMd0ZBfUwdaW1")

# Inicializar Firebase
if not firebase_admin._apps:
    cred = credentials.Certificate("./ninatec-ecc00-firebase-adminsdk-fbsvc-5d1171c4a7 (1).json")
    firebase_admin.initialize_app(cred)
db = firestore.client()

# Cargar modelo de Hugging Face
model_name = "NadiaLiz/Llama-3.2"
tokenizer  = AutoTokenizer.from_pretrained(model_name)
device     = torch.device("cuda" if torch.cuda.is_available() else "cpu")
model      = AutoModelForCausalLM.from_pretrained(
    model_name,
    device_map="auto",
    torch_dtype=torch.float16
).to(device)

def normalizar(texto):
    texto = texto.lower()
    texto = unicodedata.normalize('NFKD', texto).encode('ASCII', 'ignore').decode('utf-8')
    return texto

def extraer_producto(mensaje):
    mensaje_norm = normalizar(mensaje)
    productos_ref = db.collection("Productos").stream()

    for doc in productos_ref:
        nombre_producto = doc.to_dict().get("producto", "")
        nombre_norm = normalizar(nombre_producto)
        if nombre_norm in mensaje_norm:
            return doc.id
    return None

def buscar_precio(producto):
    ref = db.collection("Productos").document(producto)
    doc = ref.get()

    if doc.exists:
        data = doc.to_dict()
        producto = data.get("producto")
        precio = data.get("precio")
        return f"Claro, el {producto} cuesta S/{precio}."
    else:
        return None

def send_whatsapp_message(to: str, body: str) -> dict:
    headers = {
        "Authorization": f"Bearer {ACCESS_TOKEN}",
        "Content-Type":  "application/json"
    }
    payload = {
        "messaging_product": "whatsapp",
        "to":                to,
        "text":              {"body": body}
    }
    resp = requests.post(WHATSAPP_API, headers=headers, json=payload)
    try:
        return resp.json()
    except ValueError:
        return {"error": resp.text}

def obtener_contexto():
    return (
        "Eres un asistente virtual de Ninatec, una empresa especializada en "
        "tecnología y automatización. Responde siempre de manera amable, clara y profesional."
    )

# ———————— FLASK APP ————————
app = Flask(__name__)

@app.route("/whatsapp", methods=["GET", "POST"])
def webhook():
    if request.method == "GET":
        mode      = request.args.get("hub.mode")
        token     = request.args.get("hub.verify_token")
        challenge = request.args.get("hub.challenge")
        if mode == "subscribe" and token == VERIFY_TOKEN:
            print("Webhook verificado")
            return challenge, 200
        return "Token no coincide", 403

    data = request.get_json(force=True)
    try:
        msg_obj      = data["entry"][0]["changes"][0]["value"]["messages"][0]
        incoming_msg = msg_obj["text"]["body"]
        from_number  = msg_obj["from"]
    except Exception:
        return "OK", 200  # ignorar otros eventos

    print("Mensaje recibido:", incoming_msg)

    texto = incoming_msg.lower()
    if "precio" in texto or "cuánto cuesta" in texto:
        pid = extraer_producto(incoming_msg)
        if pid:
            respuesta = buscar_precio(pid)
        else:
            respuesta = "¿De qué producto deseas saber el precio? Por favor escribe el nombre exacto."
    else:
        prompt = f"{obtener_contexto()}\nUsuario: {incoming_msg}\nAsistente:"
        inputs = tokenizer(prompt, return_tensors="pt").to(device)
        out    = model.generate(**inputs, max_new_tokens=100, do_sample=True, temperature=0.7)
        gen    = tokenizer.decode(out[0], skip_special_tokens=True)
        respuesta = gen.replace(prompt, "").strip()

    print("Respuesta generada:", respuesta)

    # Limpiar número y enviar respuesta
    to   = from_number.replace("whatsapp:", "").replace("+", "").strip()
    print("Enviando a:", to)
    resp = send_whatsapp_message(to, respuesta)
    print("WhatsApp API response:", resp)

    return "OK", 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
