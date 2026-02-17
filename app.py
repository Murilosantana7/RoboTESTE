"""
SeaTalk Bot - Integração com Google Sheets
Bot que responde com tarefas do Backlog quando recebe a mensagem "Backlog"
"""

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
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# Constantes
SCOPES = ['https://www.googleapis.com/auth/spreadsheets.readonly']
SEATALK_API_BASE = "https://openapi.seatalk.io"

def get_seatalk_app_token():
    """Obtém o access_token oficial do SeaTalk usando ID e Secret"""
    url = f"{SEATALK_API_BASE}/auth/app_access_token"
    payload = {
        "app_id": os.environ.get('SEATALK_APP_ID'),
        "app_secret": os.environ.get('SEATALK_APP_SECRET')
    }
    try:
        response = requests.post(url, json=payload, timeout=10)
        if response.status_code == 200:
            return response.json().get('app_access_token')
        return None
    except Exception as e:
        logger.error(f"Erro ao obter token SeaTalk: {e}")
        return None

def get_google_credentials():
    try:
        credentials_base64 = os.environ.get('GOOGLE_CREDENTIALS_BASE64')
        if not credentials_base64:
            raise ValueError("GOOGLE_CREDENTIALS_BASE64 não configurado")
        
        credentials_json = base64.b64decode(credentials_base64).decode('utf-8')
        credentials_info = json.loads(credentials_json)
        
        return Credentials.from_service_account_info(
            credentials_info,
            scopes=SCOPES
        )
    except Exception as e:
        logger.error(f"Erro ao decodificar credenciais do Google: {e}")
        raise

def get_backlog_tasks():
    try:
        credentials = get_google_credentials()
        client = gspread.authorize(credentials)
        
        sheet_id = os.environ.get('SHEET_ID')
        sheet_name = os.environ.get('SHEET_NAME', 'Sheet1')
        
        spreadsheet = client.open_by_key(sheet_id)
        worksheet = spreadsheet.worksheet(sheet_name)
        data = worksheet.get_all_records()
        
        backlog_tasks = []
        for row in data:
            status_value = row.get('Status', row.get('status', ''))
            if str(status_value).strip().lower() == 'backlog':
                task_name = row.get('Nome da tarefa', row.get('Tarefa', list(row.values())[0]))
                if task_name:
                    backlog_tasks.append(str(task_name).strip())
        
        return backlog_tasks
    except Exception as e:
        logger.error(f"Erro ao consultar Google Sheets: {e}")
        raise

def send_seatalk_message(group_id, message_text, app_token):
    try:
        url = f"{SEATALK_API_BASE}/messaging/v2/group_chat"
        headers = {
            "Authorization": f"Bearer {app_token}",
            "Content-Type": "application/json"
        }
        payload = {
            "group_id": group_id,
            "message": {
                "tag": "text",
                "text": {"content": message_text}
            }
        }
        response = requests.post(url, headers=headers, json=payload, timeout=30)
        return response.status_code == 200
    except Exception as e:
        logger.error(f"Erro ao enviar mensagem: {e}")
        return False

def verify_webhook_signature(request_data, signature, signing_secret):
    if not signing_secret or not signature:
        return False
    try:
        expected_signature = hmac.new(
            signing_secret.encode('utf-8'),
            request_data,
            hashlib.sha256
        ).hexdigest()
        return hmac.compare_digest(signature.lower(), expected_signature.lower())
    except Exception:
        return False

@app.route('/webhook', methods=['POST'])
def webhook():
    try:
        request_data = request.get_data()
        data = request.get_json()
        
        # --- VERIFICAÇÃO DE CHALLENGE (Handshake do SeaTalk) ---
        if data and 'seatalk_challenge' in data:
            logger.info("Respondendo ao desafio de verificação do SeaTalk")
            return jsonify({"seatalk_challenge": data['seatalk_challenge']})

        # Validação de Assinatura
        signing_secret = os.environ.get('SIGNING_SECRET')
        signature = request.headers.get('X-Seatalk-Signature', '')
        if signing_secret and not verify_webhook_signature(request_data, signature, signing_secret):
            return jsonify({"status": "error", "message": "Invalid signature"}), 401
        
        if not data or data.get('event_type') != 'new_message':
            return jsonify({"status": "ok"}), 200
        
        message_data = data.get('message', {})
        message_text = message_data.get('text', '').strip().lower()
        group_id = data.get('chat', {}).get('group_id', '')

        if message_text == 'backlog':
            app_token = get_seatalk_app_token()
            if not app_token:
                return jsonify({"status": "error", "message": "Auth failed"}), 500
            
            try:
                tasks = get_backlog_tasks()
                response_text = "📋 *Backlog atual:*\n" + ("\n".join([f"• {t}" for t in tasks]) if tasks else "Nenhuma tarefa.")
            except Exception:
                response_text = "❌ Erro ao consultar a planilha."
            
            send_seatalk_message(group_id, response_text, app_token)
        
        return jsonify({"status": "ok"}), 200
    except Exception as e:
        logger.error(f"Erro no webhook: {e}")
        return jsonify({"status": "ok"}), 200

@app.route('/')
def index():
    return "Bot Online e Acordado!", 200

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
