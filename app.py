import os
import base64
import json
import logging
import hmac
import hashlib
import requests
from flask import Flask, request

# Configuração de Logs
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

app = Flask(__name__)

def get_seatalk_token():
    url = "https://openapi.seatalk.io/auth/app_access_token"
    payload = {"app_id": os.environ.get('SEATALK_APP_ID'), "app_secret": os.environ.get('SEATALK_APP_SECRET')}
    try:
        response = requests.post(url, json=payload, timeout=10)
        return response.json().get('app_access_token')
    except:
        return None

@app.route('/webhook', methods=['POST'])
def webhook():
    # Captura o desafio de qualquer lugar (JSON ou Formulário)
    data = request.get_json(silent=True) or {}
    challenge = data.get('seatalk_challenge') or request.form.get('seatalk_challenge')

    # --- RESPOSTA AO DESAFIO (Handshake) ---
    # Retorna o texto puro para passar na verificação do SeaTalk
    if challenge:
        logger.info(f"Verificação aprovada para o desafio: {challenge}")
        return str(challenge), 200, {'Content-Type': 'text/plain'}

    # --- PROCESSAMENTO DE MENSAGENS REAIS ---
    if data.get('event_type') == 'new_message':
        msg_text = data.get('message', {}).get('text', '').strip().lower()
        group_id = data.get('chat', {}).get('group_id')

        if msg_text == 'backlog':
            # Aqui você pode adicionar a lógica de leitura da planilha futuramente
            token = get_seatalk_token()
            url_send = "https://openapi.seatalk.io/messaging/v2/group_chat"
            headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
            payload_send = {
                "group_id": group_id, 
                "message": {"tag": "text", "text": {"content": "📋 Robô ativo! Aguardando conexão com a planilha."}}
            }
            requests.post(url_send, headers=headers, json=payload_send, timeout=20)

    return "OK", 200

@app.route('/')
def index():
    return "Servidor Online - SP5", 200

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
