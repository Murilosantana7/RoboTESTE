import os
import base64
import json
import logging
import hmac
import hashlib
import requests
from flask import Flask, request, jsonify
import gspread
from google.oauth2.service_account import Credentials

# Configuração de logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

app = Flask(__name__)

# Constantes
SCOPES = ['https://www.googleapis.com/auth/spreadsheets.readonly']
SEATALK_API_BASE = "https://openapi.seatalk.io"

def get_seatalk_app_token():
    url = f"{SEATALK_API_BASE}/auth/app_access_token"
    payload = {"app_id": os.environ.get('SEATALK_APP_ID'), "app_secret": os.environ.get('SEATALK_APP_SECRET')}
    try:
        response = requests.post(url, json=payload, timeout=10)
        return response.json().get('app_access_token') if response.status_code == 200 else None
    except Exception as e:
        logger.error(f"Erro token SeaTalk: {e}")
        return None

def get_backlog_tasks():
    try:
        creds_b64 = os.environ.get('GOOGLE_CREDENTIALS_BASE64')
        creds_info = json.loads(base64.b64decode(creds_b64).decode('utf-8'))
        credentials = Credentials.from_service_account_info(creds_info, scopes=SCOPES)
        client = gspread.authorize(credentials)
        
        sheet = client.open_by_key(os.environ.get('SHEET_ID')).sheet1
        data = sheet.get_all_records()
        
        # Filtra tarefas com status 'Backlog'
        return [str(row.get('Tarefa', list(row.values())[0])).strip() 
                for row in data if str(row.get('Status', '')).strip().lower() == 'backlog']
    except Exception as e:
        logger.error(f"Erro Sheets: {e}")
        return []

def send_message(group_id, text, token):
    url = f"{SEATALK_API_BASE}/messaging/v2/group_chat"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    payload = {"group_id": group_id, "message": {"tag": "text", "text": {"content": text}}}
    requests.post(url, headers=headers, json=payload, timeout=30)

@app.route('/webhook', methods=['POST'])
def webhook():
    # 'silent=True' evita erro se o SeaTalk não enviar o header de JSON
    data = request.get_json(silent=True) or {}
    
    # 1. RESPOSTA AO DESAFIO (Crítico para a verificação do painel)
    if 'seatalk_challenge' in data:
        logger.info("Desafio SeaTalk respondido com sucesso!")
        return jsonify({"seatalk_challenge": data['seatalk_challenge']})

    # 2. VALIDAÇÃO DE ASSINATURA (Opcional, mas seguro)
    signing_secret = os.environ.get('SIGNING_SECRET')
    if signing_secret:
        signature = request.headers.get('X-Seatalk-Signature', '')
        expected = hmac.new(signing_secret.encode('utf-8'), request.get_data(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(signature.lower(), expected.lower()):
            return jsonify({"status": "invalid_signature"}), 401

    # 3. PROCESSAMENTO DA MENSAGEM
    if data.get('event_type') == 'new_message':
        msg_text = data.get('message', {}).get('text', '').strip().lower()
        group_id = data.get('chat', {}).get('group_id')

        if msg_text == 'backlog':
            token = get_seatalk_app_token()
            if token:
                tasks = get_backlog_tasks()
                resposta = "📋 *Backlog atual:*\n" + ("\n".join([f"• {t}" for t in tasks]) if tasks else "Nenhuma tarefa.")
                send_message(group_id, resposta, token)

    return jsonify({"status": "ok"}), 200

@app.route('/')
def index():
    return "Bot Online!", 200

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
