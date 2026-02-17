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
from functools import wraps
from flask import Flask, request, jsonify
import gspread
from google.oauth2.service_account import Credentials
import requests

# Configuração de logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Inicialização do Flask
app = Flask(__name__)

# Constantes
SCOPES = ['https://www.googleapis.com/auth/spreadsheets.readonly']
SEATALK_API_BASE = "https://openapi.seatalk.io"


def get_google_credentials():
    """
    Decodifica as credenciais do Google a partir da variável de ambiente
    GOOGLE_CREDENTIALS_BASE64 e retorna um objeto Credentials.
    """
    try:
        credentials_base64 = os.environ.get('GOOGLE_CREDENTIALS_BASE64')
        if not credentials_base64:
            raise ValueError("GOOGLE_CREDENTIALS_BASE64 não configurado")
        
        # Decodifica o base64
        credentials_json = base64.b64decode(credentials_base64).decode('utf-8')
        credentials_info = json.loads(credentials_json)
        
        # Cria as credenciais
        credentials = Credentials.from_service_account_info(
            credentials_info,
            scopes=SCOPES
        )
        logger.info("Credenciais do Google decodificadas com sucesso")
        return credentials
    except Exception as e:
        logger.error(f"Erro ao decodificar credenciais do Google: {e}")
        raise


def get_backlog_tasks():
    """
    Consulta o Google Sheets e retorna apenas as tarefas com Status = 'Backlog'.
    
    Returns:
        list: Lista de nomes das tarefas em Backlog
    """
    try:
        credentials = get_google_credentials()
        client = gspread.authorize(credentials)
        
        sheet_id = os.environ.get('SHEET_ID')
        sheet_name = os.environ.get('SHEET_NAME', 'Sheet1')
        
        if not sheet_id:
            raise ValueError("SHEET_ID não configurado")
        
        # Abre a planilha
        spreadsheet = client.open_by_key(sheet_id)
        worksheet = spreadsheet.worksheet(sheet_name)
        
        # Obtém todos os dados
        data = worksheet.get_all_records()
        logger.info(f"Dados obtidos da planilha: {len(data)} linhas")
        
        # Filtra apenas as tarefas com Status = 'Backlog' (case insensitive)
        backlog_tasks = []
        for row in data:
            # Verifica se existe a coluna 'Status' (pode variar conforme o header)
            status_value = row.get('Status', row.get('status', ''))
            if status_value and status_value.strip().lower() == 'backlog':
                # Pega o nome da tarefa (coluna 'Nome da tarefa' ou 'Tarefa' ou primeira coluna)
                task_name = row.get('Nome da tarefa', 
                          row.get('Tarefa', 
                          row.get('tarefa', 
                          row.get('nome', None))))
                
                # Se não encontrou pelo nome, tenta a primeira coluna
                if task_name is None and row:
                    task_name = list(row.values())[0] if row else None
                
                if task_name and str(task_name).strip():
                    backlog_tasks.append(str(task_name).strip())
        
        logger.info(f"Tarefas em Backlog encontradas: {len(backlog_tasks)}")
        return backlog_tasks
        
    except gspread.exceptions.WorksheetNotFound:
        logger.error(f"Aba '{sheet_name}' não encontrada na planilha")
        raise
    except gspread.exceptions.SpreadsheetNotFound:
        logger.error(f"Planilha com ID '{sheet_id}' não encontrada")
        raise
    except Exception as e:
        logger.error(f"Erro ao consultar Google Sheets: {e}")
        raise


def send_seatalk_message(group_id, message_text, app_token):
    """
    Envia uma mensagem para um grupo do SeaTalk usando a API oficial.
    
    Args:
        group_id: ID do grupo
        message_text: Texto da mensagem
        app_token: Token de acesso do bot
    
    Returns:
        bool: True se enviado com sucesso
    """
    try:
        url = f"{SEATALK_API_BASE}/messaging/v2/group_chat"
        
        headers = {
            "Authorization": f"Bearer {app_token}",
            "Content-Type": "application/json"
        }
        
        payload = {
            "group_id": group_id,
            "message": {
                "text": message_text
            }
        }
        
        response = requests.post(
            url,
            headers=headers,
            json=payload,
            timeout=30
        )
        
        if response.status_code == 200:
            logger.info(f"Mensagem enviada com sucesso para o grupo {group_id}")
            return True
        else:
            logger.error(f"Erro ao enviar mensagem: {response.status_code} - {response.text}")
            return False
            
    except requests.exceptions.Timeout:
        logger.error("Timeout ao enviar mensagem para o SeaTalk")
        return False
    except Exception as e:
        logger.error(f"Erro ao enviar mensagem para o SeaTalk: {e}")
        return False


def verify_webhook_signature(request_data, signature, signing_secret):
    """
    Verifica a assinatura da webhook do SeaTalk.
    
    Args:
        request_data: Dados brutos da requisição
        signature: Assinatura recebida no header
        signing_secret: Segredo para validação
    
    Returns:
        bool: True se a assinatura for válida
    """
    if not signing_secret:
        logger.warning("SIGNING_SECRET não configurado, ignorando validação de assinatura")
        return True
    
    if not signature:
        logger.warning("Assinatura não recebida na requisição")
        return False
    
    try:
        # Calcula o HMAC SHA256
        expected_signature = hmac.new(
            signing_secret.encode('utf-8'),
            request_data,
            hashlib.sha256
        ).hexdigest()
        
        # Compara as assinaturas (case insensitive)
        is_valid = hmac.compare_digest(
            signature.lower(),
            expected_signature.lower()
        )
        
        if is_valid:
            logger.info("Assinatura da webhook validada com sucesso")
        else:
            logger.warning("Assinatura da webhook inválida")
        
        return is_valid
        
    except Exception as e:
        logger.error(f"Erro ao verificar assinatura: {e}")
        return False


def format_backlog_message(tasks):
    """
    Formata a mensagem de resposta com as tarefas do Backlog.
    
    Args:
        tasks: Lista de nomes das tarefas
    
    Returns:
        str: Mensagem formatada
    """
    if not tasks:
        return "📋 *Backlog atual:*\n\nNenhuma tarefa no backlog no momento."
    
    message_lines = ["📋 *Backlog atual:*\n"]
    
    for task in tasks:
        message_lines.append(f"• {task}")
    
    return "\n".join(message_lines)


@app.route('/webhook', methods=['POST'])
def webhook():
    """
    Endpoint principal que recebe as webhooks do SeaTalk.
    Processa mensagens e responde quando recebe "Backlog".
    """
    try:
        # Obtém os dados brutos para validação de assinatura
        request_data = request.get_data()
        
        # Verifica assinatura se configurada
        signing_secret = os.environ.get('SIGNING_SECRET')
        signature = request.headers.get('X-Seatalk-Signature', '')
        
        if signing_secret and not verify_webhook_signature(request_data, signature, signing_secret):
            logger.warning("Requisição com assinatura inválida rejeitada")
            return jsonify({"status": "error", "message": "Invalid signature"}), 401
        
        # Parse do JSON
        data = request.get_json()
        
        if not data:
            logger.warning("Requisição sem corpo JSON recebida")
            return jsonify({"status": "error", "message": "Invalid JSON"}), 400
        
        logger.info(f"Webhook recebido: {json.dumps(data, indent=2)}")
        
        # Extrai informações da mensagem
        event_type = data.get('event_type', '')
        
        # Processa apenas eventos de mensagem
        if event_type != 'new_message':
            logger.info(f"Evento ignorado: {event_type}")
            return jsonify({"status": "ok"}), 200
        
        # Extrai dados da mensagem
        message_data = data.get('message', {})
        message_text = message_data.get('text', '').strip()
        chat_data = data.get('chat', {})
        group_id = chat_data.get('group_id', '')
        
        logger.info(f"Mensagem recebida: '{message_text}' do grupo: {group_id}")
        
        # Verifica se a mensagem é "Backlog" (case insensitive)
        if message_text.lower() != 'backlog':
            logger.info(f"Mensagem ignorada: '{message_text}' não é 'Backlog'")
            return jsonify({"status": "ok"}), 200
        
        # Responde rapidamente com 200 para o SeaTalk
        # O processamento continua em background
        
        # Obtém o token do bot
        app_token = os.environ.get('SEATALK_APP_TOKEN')
        if not app_token:
            logger.error("SEATALK_APP_TOKEN não configurado")
            return jsonify({"status": "error", "message": "Bot token not configured"}), 500
        
        # Busca as tarefas do Backlog
        try:
            backlog_tasks = get_backlog_tasks()
            response_message = format_backlog_message(backlog_tasks)
        except Exception as e:
            logger.error(f"Erro ao buscar tarefas: {e}")
            response_message = "❌ Desculpe, ocorreu um erro ao consultar o backlog. Tente novamente mais tarde."
        
        # Envia a resposta
        success = send_seatalk_message(group_id, response_message, app_token)
        
        if success:
            logger.info("Resposta enviada com sucesso")
        else:
            logger.error("Falha ao enviar resposta")
        
        return jsonify({"status": "ok"}), 200
        
    except Exception as e:
        logger.error(f"Erro no processamento do webhook: {e}")
        # Sempre retorna 200 para o SeaTalk não reenviar
        return jsonify({"status": "ok"}), 200


@app.route('/health', methods=['GET'])
def health_check():
    """
    Endpoint de health check para monitoramento.
    """
    return jsonify({
        "status": "healthy",
        "service": "seatalk-bot-google-sheets"
    }), 200


@app.route('/', methods=['GET'])
def index():
    """
    Página inicial com informações do bot.
    """
    return jsonify({
        "name": "SeaTalk Backlog Bot",
        "version": "1.0.0",
        "description": "Bot que consulta tarefas do Backlog no Google Sheets",
        "endpoints": {
            "/webhook": "POST - Recebe webhooks do SeaTalk",
            "/health": "GET - Health check"
        }
    }), 200


if __name__ == '__main__':
    # Verifica variáveis obrigatórias
    required_vars = ['GOOGLE_CREDENTIALS_BASE64', 'SHEET_ID', 'SEATALK_APP_TOKEN']
    missing_vars = [var for var in required_vars if not os.environ.get(var)]
    
    if missing_vars:
        logger.error(f"Variáveis de ambiente obrigatórias não configuradas: {', '.join(missing_vars)}")
        exit(1)
    
    # Inicia o servidor
    port = int(os.environ.get('PORT', 5000))
    debug = os.environ.get('FLASK_DEBUG', 'false').lower() == 'true'
    
    logger.info(f"Iniciando servidor na porta {port}")
    app.run(host='0.0.0.0', port=port, debug=debug)
