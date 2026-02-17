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

# 1. Configuração de Logs (Para você acompanhar no Render)
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

app = Flask(__name__)

# 2. Funções de Apoio (SeaTalk e Google Sheets)
def get_seatalk_token():
    url = "https://openapi.seatalk.io/auth/app_access_token"
    payload = {"app_id": os.environ.get('SEATALK_APP_ID'), "app_secret": os.environ.get('SEATALK_APP_SECRET')}
    try:
        response = requests.post(url, json=payload, timeout=10)
        return response.json().get('app_access_token')
    except Exception as e:
        logger.error(f"Erro no token SeaTalk: {e}")
        return None

def get_backlog_data():
    try:
        creds_b64 = os.environ.get('GOOGLE_CREDENTIALS_BASE64')
        creds_info = json.loads(base64.b64decode(creds_b64).decode('utf-8'))
        credentials = Credentials.from_service_account_info(creds_info, scopes=['https://www.googleapis.com/auth/spreadsheets.readonly'])
        client = gspread.authorize(credentials)
        
        sheet = client.open_by_key(os.environ.get('SHEET_ID')).sheet1
        data = sheet.get_all_records()
        
        # Filtra as tarefas onde a coluna 'Status' é 'Backlog'
        return [str(row.get('Tarefa', list(row.values())[0])).strip() 
                for row in data if str(row.get('Status', '')).strip().lower() == 'backlog']
    except Exception as e:
        logger.error(f"Erro no Google Sheets: {e}")
        return None

# 3. Rota Principal do Webhook
@app.route('/webhook', methods=['POST'])
def webhook():
    # 'force=True' garante a leitura mesmo se o SeaTalk não enviar o header de JSON
    data = request.get_json(force=True, silent=True) or {}
    
    # --- A: RESPOSTA AO DESAFIO (Handshake) ---
    # Isso resolve o erro "invalid response"
    challenge = data.get('seatalk_challenge') or request.args.get('seatalk_challenge')
    if challenge:
        logger.info(f"Respondendo ao desafio SeaTalk: {challenge}")
        return jsonify({"seatalk_challenge": challenge})

    # --- B: VALIDAÇÃO DE ASSINATURA ---
    signing_secret = os.environ.get('SIGNING_SECRET')
    signature = request.headers.get('X-Seatalk-Signature', '')
    if signing_secret and signature:
        expected = hmac.new(signing_secret.encode('utf-8'), request.get_data(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(signature.lower(), expected.lower()):
            logger.warning("Assinatura inválida detectada.")

    # --- C: PROCESSAMENTO DA MENSAGEM ---
    if data.get('event_type') == 'new_message':
        msg_text = data.get('message', {}).get('text', '').strip().lower()
        group_id = data.get('chat', {}).get('group_id')

        if msg_text == 'backlog':
            token = get_seatalk_token()
            tasks = get_backlog_data()
            
            if tasks is not None:
                resposta = "📋 *Backlog atual SP5:*\n" + ("\n".join([f"• {t}" for t in tasks]) if tasks else "Nenhuma tarefa pendente.")
            else:
                resposta = "❌ Erro ao acessar a planilha. Verifique o compartilhamento com o e-mail do robô."
            
            # Envio da resposta via API do SeaTalk
            url_send = "https://openapi.seatalk.io/messaging/v2/group_chat"
            headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
            payload_send = {"group_id": group_id, "message": {"tag": "text", "text": {"content": resposta}}}
            requests.post(url_send, headers=headers, json=payload_send, timeout=20)

    return jsonify({"status": "ok"}), 200

@app.route('/')
def home():
    return "Servidor Live - Robô do Murilo!", 200

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
