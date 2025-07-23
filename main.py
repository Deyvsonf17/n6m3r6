import logging
import os
import sqlite3
import asyncio
import aiohttp
from aiohttp import web
import random
import string
import json
import urllib.parse
import threading
import time
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes
from collections import defaultdict
from functools import wraps

# Configurações dos logs melhoradas
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Rate limiting global - configurações mais flexíveis
user_rate_limits = defaultdict(list)
RATE_LIMIT_SECONDS = 0.5  # Máximo 1 comando a cada 0.5 segundos por usuário
MAX_REQUESTS_PER_MINUTE = 30  # Máximo 30 requests por minuto por usuário

# Cache global para preços de crypto
crypto_price_cache = {}
CACHE_EXPIRY_SECONDS = 300  # Cache de 5 minutos

def rate_limit(func):
    """Decorator para rate limiting por usuário"""
    @wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not update.effective_user:
            return
        
        user_id = update.effective_user.id
        now = time.time()
        
        # Limpar requests antigos (mais de 1 minuto)
        user_rate_limits[user_id] = [req_time for req_time in user_rate_limits[user_id] 
                                    if now - req_time < 60]
        
        # Verificar rate limit por minuto (mais flexível)
        if len(user_rate_limits[user_id]) >= MAX_REQUESTS_PER_MINUTE:
            logger.warning(f"Rate limit por minuto atingido para usuário {user_id}")
            try:
                if hasattr(update, 'message') and update.message:
                    await update.message.reply_text(
                        "⚠️ Muitas solicitações! Aguarde um momento antes de tentar novamente."
                    )
                elif hasattr(update, 'callback_query') and update.callback_query:
                    await update.callback_query.answer(
                        "⚠️ Aguarde um momento antes de tentar novamente.", show_alert=False
                    )
            except Exception as e:
                logger.error(f"Erro ao enviar mensagem de rate limit: {e}")
            return
        
        # Verificar intervalo mínimo (mais flexível)
        if user_rate_limits[user_id] and now - user_rate_limits[user_id][-1] < RATE_LIMIT_SECONDS:
            logger.info(f"Rate limit por segundo atingido para usuário {user_id}")
            return  # Silencioso para não irritar o usuário
        
        # Adicionar timestamp atual
        user_rate_limits[user_id].append(now)
        
        return await func(update, context)
    return wrapper

# Tokens das APIs (usando secrets do Replit)
BOT_TOKEN = os.getenv("BOT_TOKEN")
CRYPTOPAY_API_TOKEN = os.getenv("CRYPTOPAY_API_TOKEN")
FIVESIM_API_TOKEN = os.getenv("FIVESIM_API_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
RENDER_URL = os.getenv("RENDER_URL", "https://n6m3r6.onrender.com")

# URLs das APIs
CRYPTOPAY_API_BASE = "https://pay.crypt.bot/api"
FIVESIM_API_BASE = "https://5sim.net/v1"

# Configurações do sistema
VALORES_RECARGA = [1, 10, 25, 50, 100, 200]

# Criptomoedas disponíveis (apenas as suportadas pelo CryptoPay)
MOEDAS_CRYPTO = [
    {"code": "USDT", "symbol": "₮", "name": "Tether"},
    {"code": "TON", "symbol": "💎", "name": "Toncoin"},
    {"code": "SOL", "symbol": "◎", "name": "Solana"},
    {"code": "TRX", "symbol": "⚡", "name": "Tron"},
    {"code": "BTC", "symbol": "₿", "name": "Bitcoin"},
    {"code": "ETH", "symbol": "Ξ", "name": "Ethereum"},
    {"code": "DOGE", "symbol": "Ð", "name": "Dogecoin"},
    {"code": "LTC", "symbol": "Ł", "name": "Litecoin"},
    {"code": "PEPE", "symbol": "🐸", "name": "Pepe"},
    {"code": "BNB", "symbol": "🔸", "name": "BNB"},
    {"code": "USDC", "symbol": "💵", "name": "USD Coin"},
    {"code": "NOT", "symbol": "🚫", "name": "Notcoin"},
    {"code": "WIF", "symbol": "🧢", "name": "Dogwifhat"},
    {"code": "BONK", "symbol": "🔥", "name": "Bonk"},
    {"code": "MAJOR", "symbol": "⭐", "name": "Major"},
    {"code": "DOGS", "symbol": "🐕", "name": "Dogs"},
    {"code": "HMSTR", "symbol": "🐹", "name": "Hamster"},
    {"code": "CATI", "symbol": "🐱", "name": "Catizen"}
]

# Preços dos serviços por país (baseado na tabela fornecida)
PRECOS_SERVICOS = {
    "facebook": {
        "brasil": 1.68, "russia": 1.12, "indonesia": 0.91, "india": 1.26,
        "eua": 1.54, "franca": 2.10, "alemanha": 2.24, "japao": 2.38,
        "mexico": 1.47, "turquia": 1.33
    },
    "google": {
        "brasil": 1.82, "russia": 1.19, "indonesia": 0.98, "india": 1.40,
        "eua": 1.68, "franca": 2.24, "alemanha": 2.38, "japao": 2.52,
        "mexico": 1.61, "turquia": 1.40
    },
    "twitter": {
        "brasil": 1.54, "russia": 1.05, "indonesia": 0.84, "india": 1.19,
        "eua": 1.40, "franca": 1.96, "alemanha": 2.10, "japao": 2.24,
        "mexico": 1.33, "turquia": 1.19
    },
    "instagram": {
        "brasil": 1.75, "russia": 1.26, "indonesia": 1.05, "india": 1.33,
        "eua": 1.61, "franca": 2.17, "alemanha": 2.31, "japao": 2.45,
        "mexico": 1.54, "turquia": 1.40
    },
    "snapchat": {
        "brasil": 1.47, "russia": 0.98, "indonesia": 0.77, "india": 1.12,
        "eua": 1.33, "franca": 1.89, "alemanha": 2.03, "japao": 2.17,
        "mexico": 1.26, "turquia": 1.12
    },
    "linkedin": {
        "brasil": 1.89, "russia": 1.33, "indonesia": 1.12, "india": 1.47,
        "eua": 1.75, "franca": 2.31, "alemanha": 2.45, "japao": 2.59,
        "mexico": 1.68, "turquia": 1.54
    },
    "pinterest": {
        "brasil": 1.40, "russia": 0.91, "indonesia": 0.70, "india": 1.05,
        "eua": 1.26, "franca": 1.82, "alemanha": 1.96, "japao": 2.10,
        "mexico": 1.19, "turquia": 1.05
    },
    "viber": {
        "brasil": 1.61, "russia": 1.12, "indonesia": 0.91, "india": 1.26,
        "eua": 1.47, "franca": 2.03, "alemanha": 2.17, "japao": 2.31,
        "mexico": 1.40, "turquia": 1.26
    },
    "paypal": {
        "brasil": 1.96, "russia": 1.40, "indonesia": 1.19, "india": 1.54,
        "eua": 1.82, "franca": 2.38, "alemanha": 2.52, "japao": 2.66,
        "mexico": 1.75, "turquia": 1.61
    },
    "skype": {
        "brasil": 1.54, "russia": 1.05, "indonesia": 0.84, "india": 1.19,
        "eua": 1.40, "franca": 1.96, "alemanha": 2.10, "japao": 2.24,
        "mexico": 1.33, "turquia": 1.19
    },
    "discord": {
        "brasil": 1.47, "russia": 0.98, "indonesia": 0.77, "india": 1.12,
        "eua": 1.33, "franca": 1.89, "alemanha": 2.03, "japao": 2.17,
        "mexico": 1.26, "turquia": 1.12
    },
    "yahoo": {
        "brasil": 1.82, "russia": 1.19, "indonesia": 0.98, "india": 1.40,
        "eua": 1.68, "franca": 2.24, "alemanha": 2.38, "japao": 2.52,
        "mexico": 1.61, "turquia": 1.40
    },
    "netflix": {
        "brasil": 2.10, "russia": 1.54, "indonesia": 1.33, "india": 1.68,
        "eua": 1.96, "franca": 2.52, "alemanha": 2.66, "japao": 2.80,
        "mexico": 1.89, "turquia": 1.75
    },
    "tinder": {
        "brasil": 1.68, "russia": 1.19, "indonesia": 0.98, "india": 1.33,
        "eua": 1.54, "franca": 2.10, "alemanha": 2.24, "japao": 2.38,
        "mexico": 1.47, "turquia": 1.33
    },
    "badoo": {
        "brasil": 1.54, "russia": 1.05, "indonesia": 0.84, "india": 1.19,
        "eua": 1.40, "franca": 1.96, "alemanha": 2.10, "japao": 2.24,
        "mexico": 1.33, "turquia": 1.19
    },
    "spotify": {
        "brasil": 1.89, "russia": 1.33, "indonesia": 1.12, "india": 1.47,
        "eua": 1.75, "franca": 2.31, "alemanha": 2.45, "japao": 2.59,
        "mexico": 1.68, "turquia": 1.54
    },
    "bumble": {
        "brasil": 1.47, "russia": 0.98, "indonesia": 0.77, "india": 1.12,
        "eua": 1.33, "franca": 1.89, "alemanha": 2.03, "japao": 2.17,
        "mexico": 1.26, "turquia": 1.12
    },
    "dropbox": {
        "brasil": 1.61, "russia": 1.12, "indonesia": 0.91, "india": 1.26,
        "eua": 1.47, "franca": 2.03, "alemanha": 2.17, "japao": 2.31,
        "mexico": 1.40, "turquia": 1.26
    },
    "telegram": {
        "brasil": 5.32, "russia": 1.26, "indonesia": 0.91, "india": 1.68,
        "eua": 2.10, "franca": 8.68, "alemanha": 10.22, "japao": 11.06,
        "mexico": 2.94, "turquia": 2.52
    },
    "whatsapp": {
        "brasil": 6.30, "russia": 2.52, "indonesia": 1.96, "india": 2.66,
        "eua": 3.08, "franca": 9.10, "alemanha": 10.08, "japao": 10.92,
        "mexico": 3.92, "turquia": 3.22
    }
}

# Mapeamento para IDs do CoinGecko (apenas moedas suportadas pelo CryptoPay)
COINGECKO_IDS = {
    "USDT": "tether",
    "TON": "toncoin",
    "SOL": "solana",
    "TRX": "tron",
    "BTC": "bitcoin",
    "ETH": "ethereum",
    "DOGE": "dogecoin",
    "LTC": "litecoin",
    "PEPE": "pepe",
    "BNB": "binancecoin",
    "USDC": "usd-coin",
    "NOT": "notcoin",
    "WIF": "dogwifhat",
    "BONK": "bonk",
    "MAJOR": "major-token",
    "DOGS": "dogs-token",
    "HMSTR": "hamster-kombat",
    "CATI": "catizen"
}

# Países disponíveis
PAISES_DISPONIVEIS = {
    "brasil": {"nome": "🇧🇷 Brasil", "code": "brazil"},
    "russia": {"nome": "🇷🇺 Rússia", "code": "russia"},
    "indonesia": {"nome": "🇮🇩 Indonésia", "code": "indonesia"},
    "india": {"nome": "🇮🇳 Índia", "code": "india"},
    "eua": {"nome": "🇺🇸 Estados Unidos", "code": "usa"},
    "franca": {"nome": "🇫🇷 França", "code": "france"},
    "alemanha": {"nome": "🇩🇪 Alemanha", "code": "germany"},
    "japao": {"nome": "🇯🇵 Japão", "code": "japan"},
    "mexico": {"nome": "🇲🇽 México", "code": "mexico"},
    "turquia": {"nome": "🇹🇷 Turquia", "code": "turkey"}
}

# Mensagens de urgência e exclusividade
MENSAGENS_URGENCIA = [
    "⚡ ÚLTIMAS HORAS da promoção!",
    "🔥 OFERTA LIMITADA - Restam poucas horas!",
    "⏰ URGENTE: Promoção acaba em breve!",
    "🚨 ÚLTIMAS CHANCES - Não perca!",
    "💥 OFERTA RELÂMPAGO - Por tempo limitado!"
]

MENSAGENS_EXCLUSIVIDADE = [
    "👑 ACESSO VIP - Só para você!",
    "🎯 OFERTA EXCLUSIVA - Membros premium!",
    "💎 ACESSO PRIVILEGIADO ativado!",
    "🌟 VOCÊ É ESPECIAL - Desconto exclusivo!",
    "🔑 ACESSO LIBERADO - Usuário selecionado!"
]

MENSAGENS_SUCESSO = [
    "🎉 PARABÉNS! Você garantiu sua vaga!",
    "✨ SUCESSO! Número reservado com desconto!",
    "🏆 EXCELENTE ESCOLHA! Compra confirmada!",
    "🎊 FANTÁSTICO! Você economizou muito!",
    "🌟 PERFEITO! Transação realizada com sucesso!"
]

class DatabaseManager:
    def __init__(self, db_path="premium_bot.db"):
        self.db_path = db_path
        self._lock = threading.Lock()
        self.init_database()

    def get_connection(self):
        """Obtém conexão com configurações otimizadas para alta concorrência"""
        conn = sqlite3.connect(
            self.db_path,
            timeout=30.0,  # Timeout de 30 segundos
            check_same_thread=False
        )
        # Otimizações para performance
        conn.execute("PRAGMA journal_mode=WAL")  # Write-Ahead Logging
        conn.execute("PRAGMA synchronous=NORMAL")  # Balance entre segurança e performance
        conn.execute("PRAGMA cache_size=10000")  # Cache maior
        conn.execute("PRAGMA temp_store=MEMORY")  # Store temporário na memória
        return conn

    def init_database(self):
        """Inicializa o banco de dados com as tabelas necessárias"""
        with self._lock:
            conn = self.get_connection()
            cursor = conn.cursor()

        # Tabela de usuários
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS usuarios (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                saldo REAL DEFAULT 0.0,
                saldo_bonus REAL DEFAULT 0.0,
                numeros_gratis INTEGER DEFAULT 0,
                indicador_id INTEGER,
                codigo_indicacao TEXT UNIQUE,
                data_registro TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                total_depositado REAL DEFAULT 0.0,
                indicacoes_validas INTEGER DEFAULT 0,
                ultimo_bonus TIMESTAMP,
                vip_status INTEGER DEFAULT 0,
                total_starts INTEGER DEFAULT 0
            )
        ''')

        # Migração: Adicionar coluna total_starts se não existir
        try:
            cursor.execute('ALTER TABLE usuarios ADD COLUMN total_starts INTEGER DEFAULT 0')
        except sqlite3.OperationalError:
            # Coluna já existe, ignorar erro
            pass

        # Migração: Adicionar coluna saldo_bonus se não existir
        try:
            cursor.execute('ALTER TABLE usuarios ADD COLUMN saldo_bonus REAL DEFAULT 0.0')
        except sqlite3.OperationalError:
            # Coluna já existe, ignorar erro
            pass

        # Tabela de transações
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS transacoes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                tipo TEXT,
                valor REAL,
                moeda TEXT,
                status TEXT,
                invoice_id TEXT,
                data_transacao TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                data_confirmacao TIMESTAMP,
                valor_crypto_pago REAL,
                moeda_paga TEXT,
                observacoes TEXT,
                FOREIGN KEY (user_id) REFERENCES usuarios (user_id)
            )
        ''')

        # Migração: Adicionar colunas se não existirem
        try:
            cursor.execute('ALTER TABLE transacoes ADD COLUMN data_confirmacao TIMESTAMP')
        except sqlite3.OperationalError:
            pass

        try:
            cursor.execute('ALTER TABLE transacoes ADD COLUMN valor_crypto_pago REAL')
        except sqlite3.OperationalError:
            pass

        try:
            cursor.execute('ALTER TABLE transacoes ADD COLUMN moeda_paga TEXT')
        except sqlite3.OperationalError:
            pass

        try:
            cursor.execute('ALTER TABLE transacoes ADD COLUMN observacoes TEXT')
        except sqlite3.OperationalError:
            pass

        # Tabela de números SMS
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS numeros_sms (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                servico TEXT,
                pais TEXT,
                numero TEXT,
                codigo_recebido TEXT,
                preco REAL,
                desconto_aplicado REAL,
                status TEXT,
                data_compra TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES usuarios (user_id)
            )
        ''')

        conn.commit()
        conn.close()

    def get_user(self, user_id):
        """Busca um usuário no banco"""
        with self._lock:
            conn = self.get_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM usuarios WHERE user_id = ?", (user_id,))
            user = cursor.fetchone()
            conn.close()
            return user

    def create_user(self, user_id, username, first_name, indicador_id=None):
        """Cria um novo usuário com bônus de boas-vindas"""
        with self._lock:
            conn = self.get_connection()
            cursor = conn.cursor()
            cursor.execute('''
                INSERT OR IGNORE INTO usuarios (user_id, username, first_name, indicador_id, saldo, saldo_bonus)
                VALUES (?, ?, ?, ?, 0.0, 0.5)
            ''', (user_id, username, first_name, indicador_id))
            conn.commit()
            conn.close()

    def update_saldo(self, user_id, valor):
        """Atualiza o saldo base do usuário (APENAS para depósitos)"""
        with self._lock:
            conn = self.get_connection()
            cursor = conn.cursor()
            cursor.execute('''
                UPDATE usuarios SET saldo = saldo + ? WHERE user_id = ?
            ''', (valor, user_id))
            conn.commit()
            conn.close()

    def update_saldo_bonus(self, user_id, valor_bonus):
        """Atualiza o saldo de bônus do usuário"""
        with self._lock:
            conn = self.get_connection()
            cursor = conn.cursor()
            cursor.execute('''
                UPDATE usuarios SET saldo_bonus = saldo_bonus + ? WHERE user_id = ?
            ''', (valor_bonus, user_id))
            conn.commit()
            conn.close()

    def processar_deposito(self, user_id, valor_depositado, bonus):
        """Processa um depósito separando saldo base e bônus"""
        with self._lock:
            conn = self.get_connection()
            cursor = conn.cursor()
            # Atualizar saldo base com valor depositado
            cursor.execute('UPDATE usuarios SET saldo = saldo + ? WHERE user_id = ?', (valor_depositado, user_id))
            # Atualizar bônus separadamente
            cursor.execute('UPDATE usuarios SET saldo_bonus = saldo_bonus + ? WHERE user_id = ?', (bonus, user_id))
            # Atualizar total depositado
            cursor.execute('UPDATE usuarios SET total_depositado = total_depositado + ? WHERE user_id = ?', (valor_depositado, user_id))
            conn.commit()
            conn.close()

    def deduzir_saldo(self, user_id, valor):
        """Deduz saldo do usuário, usando primeiro o bônus e depois o saldo base"""
        with self._lock:
            conn = self.get_connection()
            cursor = conn.cursor()
            
            # Obter saldo atual
            cursor.execute('SELECT saldo, saldo_bonus FROM usuarios WHERE user_id = ?', (user_id,))
            result = cursor.fetchone()
            if not result:
                conn.close()
                return False
            
            saldo_base, saldo_bonus = result
            saldo_base = saldo_base or 0.0
            saldo_bonus = saldo_bonus or 0.0
            
            # Verificar se há saldo suficiente
            saldo_total = saldo_base + saldo_bonus
            if saldo_total < valor:
                conn.close()
                return False
            
            # Deduzir primeiro do bônus
            if saldo_bonus >= valor:
                # Todo valor é deduzido do bônus
                cursor.execute('UPDATE usuarios SET saldo_bonus = saldo_bonus - ? WHERE user_id = ?', (valor, user_id))
            else:
                # Deduzir todo o bônus e o restante do saldo base
                valor_restante = valor - saldo_bonus
                cursor.execute('UPDATE usuarios SET saldo_bonus = 0 WHERE user_id = ?', (user_id,))
                cursor.execute('UPDATE usuarios SET saldo = saldo - ? WHERE user_id = ?', (valor_restante, user_id))
            
            conn.commit()
            conn.close()
            return True

    def get_saldo(self, user_id):
        """Obtém o saldo total do usuário (base + bônus)"""
        with self._lock:
            conn = self.get_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT saldo, saldo_bonus FROM usuarios WHERE user_id = ?", (user_id,))
            result = cursor.fetchone()
            conn.close()
            if result:
                saldo_base, saldo_bonus = result
                return (saldo_base or 0.0) + (saldo_bonus or 0.0)
            return 0.0

    def get_numeros_gratis(self, user_id):
        """Obtém a quantidade de números grátis do usuário"""
        with self._lock:
            conn = self.get_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT numeros_gratis FROM usuarios WHERE user_id = ?", (user_id,))
            result = cursor.fetchone()
            conn.close()
            return result[0] if result else 0

    def get_user_details(self, user_id):
        """Obtém detalhes completos do usuário incluindo saldo base e bônus separados"""
        with self._lock:
            conn = self.get_connection()
            cursor = conn.cursor()
            cursor.execute("""
                SELECT saldo, saldo_bonus, numeros_gratis, total_depositado 
                FROM usuarios WHERE user_id = ?
            """, (user_id,))
            result = cursor.fetchone()
            conn.close()
            if result:
                saldo_base, saldo_bonus, numeros_gratis, total_depositado = result
                
                # Garantir que valores não sejam None
                saldo_base = saldo_base or 0.0
                saldo_bonus = saldo_bonus or 0.0
                numeros_gratis = numeros_gratis or 0
                total_depositado = total_depositado or 0.0
                
                # Saldo total = saldo base + bônus
                saldo_total = saldo_base + saldo_bonus
                
                return {
                    'saldo_base': saldo_base,
                    'bonus': saldo_bonus,
                    'saldo_total': saldo_total,
                    'numeros_gratis': numeros_gratis,
                    'total_depositado': total_depositado
                }
            return {
                'saldo_base': 0,
                'bonus': 0,
                'saldo_total': 0,
                'numeros_gratis': 0,
                'total_depositado': 0
            }

    def get_user_stats(self, user_id):
        """Obtém estatísticas do usuário"""
        with self._lock:
            conn = self.get_connection()
            cursor = conn.cursor()
            cursor.execute('''
                SELECT 
                    COUNT(*) as total_compras,
                    SUM(preco) as total_gasto,
                    SUM(desconto_aplicado) as total_economizado
                FROM numeros_sms 
                WHERE user_id = ?
            ''', (user_id,))
            result = cursor.fetchone()
            conn.close()
            return result if result else (0, 0.0, 0.0)

# Instância do gerenciador de banco de dados
db = DatabaseManager()

# Funções auxiliares
def generate_referral_code():
    """Gera um código de indicação aleatório"""
    letters = string.ascii_uppercase
    numbers = string.digits
    return ''.join(random.choice(letters + numbers) for _ in range(8))

def load_referral_codes():
    """Carrega códigos de indicação do arquivo JSON"""
    try:
        with open('referral_codes.json', 'r') as f:
            return json.load(f)
    except FileNotFoundError:
        return {}

def save_referral_codes(codes_data):
    """Salva códigos de indicação no arquivo JSON"""
    with open('referral_codes.json', 'w') as f:
        json.dump(codes_data, f, indent=2)

def get_or_create_referral_code_json(user_id):
    """Obtém ou cria código de indicação para usuário usando JSON"""
    codes_data = load_referral_codes()
    user_id_str = str(user_id)

    # Verificar se usuário já tem código
    if user_id_str in codes_data:
        return codes_data[user_id_str]

    # Gerar novo código único
    while True:
        code = generate_referral_code()
        # Verificar se código já existe
        if code not in codes_data.values():
            codes_data[user_id_str] = code
            save_referral_codes(codes_data)
            return code

def get_user_by_referral_code_json(code):
    """Busca usuário pelo código de indicação usando JSON"""
    codes_data = load_referral_codes()
    for user_id, user_code in codes_data.items():
        if user_code == code:
            return int(user_id)
    return None

def calcular_bonus(valor):
    """Função centralizada para calcular bônus baseado no valor depositado"""
    if valor >= 200:
        return 50
    elif valor >= 100:
        return 20
    elif valor >= 50:
        return 8
    else:
        return 0

def is_admin(user_id):
    """Verifica se o usuário é admin"""
    return user_id == ADMIN_ID

def update_user_starts(user_id):
    """Atualiza contador de starts do usuário"""
    with db._lock:
        conn = db.get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            UPDATE usuarios SET total_starts = total_starts + 1 WHERE user_id = ?
        ''', (user_id,))
        conn.commit()
        conn.close()

def get_min_price_for_service():
    """Obtém o preço mínimo entre todos os serviços e países"""
    min_price = float('inf')
    for servico, paises in PRECOS_SERVICOS.items():
        for pais, preco in paises.items():
            if preco < min_price:
                min_price = preco
    return min_price

def get_crypto_symbol(crypto_code):
    """Obtém o símbolo da criptomoeda"""
    for moeda in MOEDAS_CRYPTO:
        if moeda["code"] == crypto_code:
            return moeda["symbol"]
    return "💰"  # símbolo padrão se não encontrar

def get_crypto_name(crypto_code):
    """Obtém o nome da criptomoeda"""
    for moeda in MOEDAS_CRYPTO:
        if moeda["code"] == crypto_code:
            return moeda["name"]
    return crypto_code

class CryptoPayManager:
    def __init__(self):
        self.api_token = CRYPTOPAY_API_TOKEN
        self.api_base = CRYPTOPAY_API_BASE
        self.headers = {
            "Content-Type": "application/json",
            "Crypto-Pay-API-Token": self.api_token
        }

    async def get_crypto_price_async(self, valor_brl, cripto):
        """Converte valor em BRL para criptomoeda usando CoinGecko com cache e requests assíncronos"""
        try:
            # Verificar cache primeiro
            cache_key = f"{cripto.upper()}_{int(time.time() // CACHE_EXPIRY_SECONDS)}"
            if cache_key in crypto_price_cache:
                cotacao = crypto_price_cache[cache_key]
                return round(valor_brl / cotacao, 8)

            # Verificar se a moeda é suportada
            moedas_suportadas = [m["code"] for m in MOEDAS_CRYPTO]
            if cripto.upper() not in moedas_suportadas:
                logger.error(f"Moeda {cripto} não suportada pelo CryptoPay")
                return None

            cripto_id = COINGECKO_IDS.get(cripto.upper())
            if not cripto_id:
                logger.error(f"ID CoinGecko não encontrado para {cripto}")
                return None

            url = f"https://api.coingecko.com/api/v3/simple/price?ids={cripto_id}&vs_currencies=brl"
            
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10)) as session:
                async with session.get(url) as response:
                    if response.status != 200:
                        logger.error(f"Erro na API CoinGecko: {response.status}")
                        return None

                    data = await response.json()
                    if cripto_id not in data:
                        logger.error(f"Dados não encontrados para {cripto_id}")
                        return None

                    cotacao = data[cripto_id]["brl"]
                    
                    # Salvar no cache
                    crypto_price_cache[cache_key] = cotacao
                    
                    # Limpar cache antigo
                    current_time_slot = int(time.time() // CACHE_EXPIRY_SECONDS)
                    keys_to_remove = [k for k in crypto_price_cache.keys() 
                                    if int(k.split('_')[-1]) < current_time_slot - 1]
                    for key in keys_to_remove:
                        del crypto_price_cache[key]
                    
                    return round(valor_brl / cotacao, 8)
        except Exception as e:
            logger.error(f"Erro ao converter BRL para {cripto}: {e}")
            return None

    def get_crypto_price(self, valor_brl, cripto):
        """Versão síncrona para compatibilidade"""
        try:
            # Verificar cache primeiro
            cache_key = f"{cripto.upper()}_{int(time.time() // CACHE_EXPIRY_SECONDS)}"
            if cache_key in crypto_price_cache:
                cotacao = crypto_price_cache[cache_key]
                return round(valor_brl / cotacao, 8)

            # Verificar se a moeda é suportada
            moedas_suportadas = [m["code"] for m in MOEDAS_CRYPTO]
            if cripto.upper() not in moedas_suportadas:
                logger.error(f"Moeda {cripto} não suportada pelo CryptoPay")
                return None

            cripto_id = COINGECKO_IDS.get(cripto.upper())
            if not cripto_id:
                logger.error(f"ID CoinGecko não encontrado para {cripto}")
                return None

            url = f"https://api.coingecko.com/api/v3/simple/price?ids={cripto_id}&vs_currencies=brl"
            
            import requests
            response = requests.get(url, timeout=10)

            if response.status_code != 200:
                logger.error(f"Erro na API CoinGecko: {response.status_code}")
                return None

            data = response.json()
            if cripto_id not in data:
                logger.error(f"Dados não encontrados para {cripto_id}")
                return None

            cotacao = data[cripto_id]["brl"]
            
            # Salvar no cache
            crypto_price_cache[cache_key] = cotacao
            
            return round(valor_brl / cotacao, 8)
        except Exception as e:
            logger.error(f"Erro ao converter BRL para {cripto}: {e}")
            return None

    async def create_invoice_async(self, valor_brl, moeda, user_id):
        """Cria uma fatura de pagamento com requests assíncronos"""
        try:
            valor_crypto = await self.get_crypto_price_async(valor_brl, moeda)
            if not valor_crypto:
                return None, "Erro ao converter moeda"

            payload = {
                "amount": str(valor_crypto),
                "asset": moeda,
                "currency_type": "crypto",
                "description": f"🔥 OFERTA ESPECIAL - R$ {valor_brl} - Usuário {user_id}",
                "expires_in": 3600
            }

            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15)) as session:
                async with session.post(
                    f"{self.api_base}/createInvoice",
                    json=payload,
                    headers=self.headers
                ) as response:
                    data = await response.json()
                    if data.get("ok"):
                        invoice = data["result"]
                        return invoice, None
                    else:
                        return None, data.get("error", "Erro desconhecido")
        except Exception as e:
            logger.error(f"Erro ao criar fatura: {e}")
            return None, str(e)

    def create_invoice(self, valor_brl, moeda, user_id):
        """Versão síncrona para compatibilidade"""
        try:
            valor_crypto = self.get_crypto_price(valor_brl, moeda)
            if not valor_crypto:
                return None, "Erro ao converter moeda"

            payload = {
                "amount": str(valor_crypto),
                "asset": moeda,
                "currency_type": "crypto",
                "description": f"🔥 OFERTA ESPECIAL - R$ {valor_brl} - Usuário {user_id}",
                "expires_in": 3600
            }

            import requests
            response = requests.post(
                f"{self.api_base}/createInvoice",
                json=payload,
                headers=self.headers,
                timeout=15
            )

            data = response.json()
            if data.get("ok"):
                invoice = data["result"]
                return invoice, None
            else:
                return None, data.get("error", "Erro desconhecido")
        except Exception as e:
            logger.error(f"Erro ao criar fatura: {e}")
            return None, str(e)

# Instância do gerenciador de pagamentos
crypto_pay = CryptoPayManager()

class FiveSimManager:
    def __init__(self):
        self.api_token = FIVESIM_API_TOKEN
        self.api_base = FIVESIM_API_BASE
        self.headers = {
            "Authorization": f"Bearer {self.api_token}",
            "Accept": "application/json"
        }

    async def get_available_countries_async(self, service):
        """Obtém países disponíveis para um serviço com requests assíncronos"""
        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10)) as session:
                async with session.get(
                    f"{self.api_base}/guest/countries",
                    headers=self.headers
                ) as response:
                    if response.status == 200:
                        return await response.json()
                    return None
        except Exception as e:
            logger.error(f"Erro ao obter países: {e}")
            return None

    async def buy_number_async(self, service, country):
        """Compra um número SMS com requests assíncronos"""
        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15)) as session:
                async with session.get(
                    f"{self.api_base}/user/buy/activation/{country}/{service}",
                    headers=self.headers
                ) as response:
                    if response.status == 200:
                        return await response.json()
                    return None
        except Exception as e:
            logger.error(f"Erro ao comprar número: {e}")
            return None

    def get_available_countries(self, service):
        """Obtém países disponíveis para um serviço"""
        try:
            import requests
            response = requests.get(
                f"{self.api_base}/guest/countries",
                headers=self.headers,
                timeout=10
            )
            return response.json() if response.status_code == 200 else None
        except Exception as e:
            logger.error(f"Erro ao obter países: {e}")
            return None

    def get_service_price(self, service, country):
        """Obtém preço do serviço para um país específico"""
        try:
            import requests
            response = requests.get(
                f"{self.api_base}/guest/prices?country={country}&product={service}",
                headers=self.headers,
                timeout=10
            )
            data = response.json()
            if response.status_code == 200 and data:
                return data.get(country, {}).get(service, {})
            return None
        except Exception as e:
            logger.error(f"Erro ao obter preços: {e}")
            return None

    def buy_number(self, service, country):
        """Compra um número SMS"""
        try:
            import requests
            response = requests.get(
                f"{self.api_base}/user/buy/activation/{country}/{service}",
                headers=self.headers,
                timeout=15
            )
            return response.json() if response.status_code == 200 else None
        except Exception as e:
            logger.error(f"Erro ao comprar número: {e}")
            return None

    def get_sms_code(self, activation_id):
        """Obtém código SMS recebido"""
        try:
            import requests
            response = requests.get(
                f"{self.api_base}/user/check/{activation_id}",
                headers=self.headers,
                timeout=10
            )
            return response.json() if response.status_code == 200 else None
        except Exception as e:
            logger.error(f"Erro ao verificar SMS: {e}")
            return None

# Instância do gerenciador 5sim
fivesim = FiveSimManager()

# Dicionário para armazenar dados temporários
temp_data = {}

# Dicionário para armazenar IDs das mensagens por usuário
user_messages = {}

def get_random_urgencia():
    """Retorna uma mensagem de urgência aleatória"""
    return random.choice(MENSAGENS_URGENCIA)

def get_random_exclusividade():
    """Retorna uma mensagem de exclusividade aleatória"""
    return random.choice(MENSAGENS_EXCLUSIVIDADE)

def get_random_sucesso():
    """Retorna uma mensagem de sucesso aleatória"""
    return random.choice(MENSAGENS_SUCESSO)

async def delete_previous_messages(context, chat_id, user_id, user_message_id=None):
    """Apaga mensagens anteriores do usuário no chat (bot + usuário)"""
    # Apagar mensagem do usuário atual se fornecida
    if user_message_id:
        try:
            await context.bot.delete_message(chat_id=chat_id, message_id=user_message_id)
        except Exception as e:
            logger.error(f"Erro ao apagar mensagem do usuário {user_message_id}: {e}")
    
    # Apagar mensagens anteriores do bot
    if user_id in user_messages:
        for message_id in user_messages[user_id]:
            try:
                await context.bot.delete_message(chat_id=chat_id, message_id=message_id)
            except Exception as e:
                logger.error(f"Erro ao apagar mensagem do bot {message_id}: {e}")
        # Limpar lista após apagar
        user_messages[user_id] = []

def store_message_id(user_id, message_id):
    """Armazena ID da mensagem enviada pelo bot"""
    if user_id not in user_messages:
        user_messages[user_id] = []
    user_messages[user_id].append(message_id)
    
    # Manter apenas as últimas 15 mensagens para evitar acúmulo
    if len(user_messages[user_id]) > 15:
        user_messages[user_id] = user_messages[user_id][-15:]

def calculate_time_left():
    """Calcula tempo restante da promoção baseado em horário de Brasília"""
    from datetime import timezone, timedelta

    # Usar timezone do Brasil (UTC-3)
    brasilia_tz = timezone(timedelta(hours=-3))
    now_brasilia = datetime.now(brasilia_tz)

    # Promoção acaba sempre às 23:59 do dia atual em Brasília
    end_time = now_brasilia.replace(hour=23, minute=59, second=59, microsecond=0)

    if now_brasilia > end_time:
        # Se já passou das 23:59, a promoção acaba às 23:59 do próximo dia
        end_time = end_time + timedelta(days=1)

    time_left = end_time - now_brasilia
    hours = time_left.seconds // 3600
    minutes = (time_left.seconds % 3600) // 60

    return f"{hours}h {minutes}min"

def load_daily_stats():
    """Carrega estatísticas do dia do arquivo JSON"""
    try:
        with open('daily_stats.json', 'r') as f:
            return json.load(f)
    except FileNotFoundError:
        return {}

def save_daily_stats(stats_data):
    """Salva estatísticas do dia no arquivo JSON"""
    with open('daily_stats.json', 'w') as f:
        json.dump(stats_data, f, indent=2)

def get_stats_fake():
    """Retorna estatísticas com comportamento melhorado"""
    from datetime import timezone, timedelta

    # Usar timezone do Brasil (UTC-3)
    brasilia_tz = timezone(timedelta(hours=-3))
    now_brasilia = datetime.now(brasilia_tz)

    # Data atual no formato YYYY-MM-DD
    hoje = now_brasilia.strftime('%Y-%m-%d')

    # Carregar dados salvos
    stats_data = load_daily_stats()

    # 1. USUÁRIOS ONLINE: Aleatório entre 1000-2000 sempre
    usuarios_online = random.randint(1000, 2000)

    # 2. NÚMEROS VENDIDOS: Sistema fixo que aumenta de 5 em 5 minutos
    # Calcular minutos desde meia-noite
    midnight = now_brasilia.replace(hour=0, minute=0, second=0, microsecond=0)
    minutes_since_midnight = int((now_brasilia - midnight).total_seconds() / 60)

    # A cada 5 minutos aumenta entre 5-25
    intervals_passed = minutes_since_midnight // 5

    # Usar seed baseado no dia para manter consistência
    date_seed = int(now_brasilia.strftime('%Y%m%d'))

    numeros_vendidos_hoje = 50  # Base
    for i in range(intervals_passed):
        random.seed(date_seed + i)
        numeros_vendidos_hoje += random.randint(5, 25)

    # Resetar seed
    random.seed()

    # 3. PESSOAS RECARREGARAM: Por hora (aleatório mas fixo por hora)
    current_hour = now_brasilia.hour
    hour_seed = int(now_brasilia.strftime('%Y%m%d%H'))
    random.seed(hour_seed)
    pessoas_recarregaram = random.randint(150, 300)
    random.seed()

    # 4. PESSOAS VENDO SERVIÇO: Aleatório entre 100-300
    pessoas_vendo_servico = random.randint(100, 300)

    # 5. INDICAÇÕES DIÁRIAS: Fixo que muda a cada 24h
    if hoje not in stats_data:
        stats_data[hoje] = {}

    if "novas_indicacoes" not in stats_data[hoje]:
        # Gerar valor fixo para o dia
        random.seed(date_seed + 100)
        stats_data[hoje]["novas_indicacoes"] = random.randint(77, 646)
        save_daily_stats(stats_data)
        random.seed()

    novas_indicacoes = stats_data[hoje]["novas_indicacoes"]

    # Limpar dados antigos (manter apenas últimos 7 dias)
    cutoff_date = (now_brasilia - timedelta(days=7)).strftime('%Y-%m-%d')
    stats_data = {k: v for k, v in stats_data.items() if k >= cutoff_date}
    save_daily_stats(stats_data)

    return {
        "usuarios_online": usuarios_online,
        "numeros_vendidos_hoje": numeros_vendidos_hoje,
        "pessoas_recarregaram": pessoas_recarregaram,
        "pessoas_vendo_servico": pessoas_vendo_servico,
        "novas_indicacoes": novas_indicacoes
    }

@rate_limit
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Comando /start - Menu principal premium"""
    if not update.effective_user:
        return

    user = update.effective_user

    # Apagar mensagens anteriores (bot + usuário)
    if update.message:
        await delete_previous_messages(context, update.message.chat_id, user.id, update.message.message_id)

    # Atualizar contador de starts
    update_user_starts(user.id)

    # Verificar se é um link de indicação com código
    indicador_id = None
    if context.args:
        referral_code = context.args[0]
        indicador_id = get_user_by_referral_code_json(referral_code)

    # Verificar se usuário existe
    user_exists = db.get_user(user.id)

    # Criar usuário se não existir
    if not user_exists:
        db.create_user(user.id, user.username, user.first_name, indicador_id)

        # Se foi indicado, notificar o indicador
        if indicador_id:
            try:
                await context.bot.send_message(
                    indicador_id,
                    f"🎉 NOVA INDICAÇÃO CONFIRMADA!\n"
                    f"👤 Usuário: {user.first_name}\n"
                    f"💰 Quando ele depositar R$ 20+:\n"
                    f"• Você ganha 2 números GRÁTIS\n"
                    f"• Ele também ganha 2 números GRÁTIS\n"
                    f"🔥 Indicação válida registrada!"
                )
            except Exception as e:
                logger.error(f"Erro ao notificar indicador: {e}")

    # Obter estatísticas e detalhes do usuário
    stats = get_stats_fake()
    user_details = db.get_user_details(user.id)
    user_stats = db.get_user_stats(user.id)
    
    # Extrair informações do usuário
    saldo_base = user_details['saldo_base']
    bonus = user_details['bonus']
    saldo_total = user_details['saldo_total']
    numeros_gratis = user_details['numeros_gratis']

    # Criar mensagem de boas-vindas premium
    exclusividade_msg = get_random_exclusividade()
    urgencia_msg = get_random_urgencia()
    tempo_restante = calculate_time_left()

    # Menu principal com design premium
    keyboard = [
        [
            InlineKeyboardButton("🔥 NÚMEROS SMS", callback_data="menu_servicos"),
            InlineKeyboardButton("💎 RECARGA VIP", callback_data="menu_recarga")
        ],
        [
            InlineKeyboardButton("👑 INDICAÇÕES", callback_data="menu_indicacao"),
            InlineKeyboardButton("❓ SUPORTE", callback_data="menu_ajuda")
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    # Verificar se é novo usuário (não existia antes)
    is_new_user = not user_exists

    # Preço mínimo atual
    preco_minimo = get_min_price_for_service()

    if is_new_user:
        welcome_text = (
            f"🎊 BEM-VINDO(A), {user.first_name}!\n\n"
            f"🎁 BÔNUS DE BOAS-VINDAS: R$ 0,50 GRÁTIS!\n\n"
            f"{exclusividade_msg}\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"💰 Seu saldo: R$ {saldo_base:.2f}\n"
            f"🎁 Seu bônus: R$ {bonus:.2f}\n"
            f"📳 Celular grátis: {numeros_gratis}\n"
            f"📱 Preços a partir de: R$ {preco_minimo:.2f}\n"
            f"🔥 Usuários online: {stats['usuarios_online']}\n"
            f"📱 Vendidos hoje: {stats['numeros_vendidos_hoje']}\n"
            f"⏰ Promoção acaba em: {tempo_restante}\n"
            f"━━━━━━━━━━━━━━━━━━━━\n\n"
            f"⚡ MELHORES PREÇOS DO MERCADO!\n"
            f"{urgencia_msg}\n\n"
            f"Escolha uma opção:"
        )
    else:
        welcome_text = (
            f"👑 OLÁ NOVAMENTE, {user.first_name.upper()}!\n\n"
            f"🏆 CLIENTE VIP DETECTADO!\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"💰 Seu saldo: R$ {saldo_base:.2f}\n"
            f"🎁 Seu bônus: R$ {bonus:.2f}\n"
            f"📳 Celular grátis: {numeros_gratis}\n"
            f"📱 Suas compras: {user_stats[0]}\n"
            f"🔥 Usuários online: {stats['usuarios_online']}\n"
            f"⏰ Promoção VIP: {tempo_restante}\n"
            f"━━━━━━━━━━━━━━━━━━━━\n\n"
            f"🎯 OFERTAS EXCLUSIVAS DISPONÍVEIS!\n"
            f"{urgencia_msg}\n\n"
            f"Escolha uma opção:"
        )

    if update.message:
        sent_message = await update.message.reply_text(welcome_text, reply_markup=reply_markup)
        store_message_id(user.id, sent_message.message_id)
    elif update.callback_query:
        await update.callback_query.edit_message_text(welcome_text, reply_markup=reply_markup)

@rate_limit
async def menu_servicos(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Menu de serviços premium"""
    query = update.callback_query
    if not query or not query.from_user:
        return

    await query.answer()
    
    # Armazenar ID da mensagem atual
    store_message_id(query.from_user.id, query.message.message_id)

    user_id = query.from_user.id
    saldo = db.get_saldo(user_id)

    # Verificar se tem saldo suficiente
    preco_minimo = get_min_price_for_service()
    if saldo < preco_minimo:
        keyboard = [
            [InlineKeyboardButton("💳 RECARREGAR AGORA", callback_data="menu_recarga")],
            [InlineKeyboardButton("🔗 INDICAR", callback_data="menu_indicacao")],
            [InlineKeyboardButton("🔙 Voltar", callback_data="menu_principal")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await query.edit_message_text(
            f"⚠️ SALDO INSUFICIENTE!\n\n"
            f"💰 Seu saldo: R$ {saldo:.2f}\n"
            f"💳 Necessário: R$ {preco_minimo:.2f}\n\n"
            f"🎯 RECARREGUE AGORA E GANHE BÔNUS!\n"
            f"🔥 Depósito de R$ 50+ = 5 números GRÁTIS!\n\n"
            f"Ou indique amigos e ganhe saldo grátis:",
            reply_markup=reply_markup
        )
        return

    # Obter estatísticas
    stats = get_stats_fake()
    tempo_restante = calculate_time_left()
    urgencia_msg = get_random_urgencia()

    # Mostrar serviços com preços
    keyboard = []
    for servico in PRECOS_SERVICOS.keys():
        emoji_map = {
            "whatsapp": "📱",
            "telegram": "📨",
            "instagram": "📸",
            "facebook": "👥",
            "twitter": "🐦",
            "google": "🔍",
            "linkedin": "💼",
            "pinterest": "📌",
            "viber": "📞",
            "paypal": "💳",
            "skype": "🎥",
            "discord": "🎮",
            "yahoo": "📧",
            "netflix": "📺",
            "tinder": "💕",
            "badoo": "💝",
            "spotify": "🎵",
            "bumble": "🐝",
            "dropbox": "📦",
            "snapchat": "👻"
        }

        emoji = emoji_map.get(servico, "📱")
        # Pegar o preço mais barato do serviço
        preco_min = min(PRECOS_SERVICOS[servico].values())

        keyboard.append([
            InlineKeyboardButton(
                f"{emoji} {servico.upper()} - A partir de R$ {preco_min:.2f}",
                callback_data=f"servico_{servico}"
            )
        ])

    keyboard.append([InlineKeyboardButton("🔙 Voltar", callback_data="menu_principal")])
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.edit_message_text(
        f"🚨 MEGA PROMOÇÃO SMS! 🚨\n\n"
        f"💎 VIP ACCESS ATIVADO\n"
        f"💰 Seu saldo: R$ {saldo:.2f}\n"
        f"🔥 {stats['usuarios_online']} pessoas online AGORA!\n"
        f"⏰ ÚLTIMAS {tempo_restante} DA PROMOÇÃO!\n"
        f"━━━━━━━━━━━━━━━━━━━━\n\n"
        f"💥 MELHORES PREÇOS DO MERCADO!\n"
        f"{urgencia_msg}\n\n"
        f"🏆 ESCOLHA SEU SERVIÇO:\n"
        f"━━━━━━━━━━━━━━━━━━━━",
        reply_markup=reply_markup
    )

async def selecionar_servico(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Selecionar país após escolher serviço"""
    query = update.callback_query
    if not query or not query.data or not query.from_user:
        return

    await query.answer()

    servico = query.data.split("_")[1]
    user_id = query.from_user.id

    # Armazenar serviço selecionado
    temp_data[user_id] = {"servico": servico}

    # Obter preços do serviço por país
    precos_servico = PRECOS_SERVICOS[servico]
    stats = get_stats_fake()
    tempo_restante = calculate_time_left()

    # Países disponíveis para o serviço
    keyboard = []
    for pais, info_pais in PAISES_DISPONIVEIS.items():
        if pais in precos_servico:
            preco = precos_servico[pais]
            keyboard.append([
                InlineKeyboardButton(
                    f"{info_pais['nome']} - R$ {preco:.2f}",
                    callback_data=f"pais_{pais}"
                )
            ])

    keyboard.append([InlineKeyboardButton("🔙 Voltar", callback_data="menu_servicos")])
    reply_markup = InlineKeyboardMarkup(keyboard)

    preco_min = min(precos_servico.values())
    preco_max = max(precos_servico.values())

    await query.edit_message_text(
        f"🎯 {servico.upper()} SELECIONADO!\n\n"
        f"💰 Preços: R$ {preco_min:.2f} - R$ {preco_max:.2f}\n"
        f"⏰ Resta: {tempo_restante}\n"
        f"━━━━━━━━━━━━━━━━━━━━\n\n"
        f"🚨 ALTA DEMANDA HOJE!\n"
        f"👥 {stats['pessoas_vendo_servico']} pessoas visualizando agora\n\n"
        f"🌍 Escolha o país:",
        reply_markup=reply_markup
    )

async def selecionar_pais(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Processar compra do número após selecionar país"""
    query = update.callback_query
    if not query or not query.data or not query.from_user:
        return

    await query.answer()

    pais = query.data.split("_")[1]
    user_id = query.from_user.id

    if user_id not in temp_data:
        await query.edit_message_text("❌ Erro: Dados não encontrados. Tente novamente.")
        return

    servico = temp_data[user_id]["servico"]
    preco = PRECOS_SERVICOS[servico][pais]
    saldo = db.get_saldo(user_id)

    # Verificar saldo
    if saldo < preco:
        keyboard = [
            [InlineKeyboardButton("💳 RECARREGAR URGENTE", callback_data="menu_recarga")],
            [InlineKeyboardButton("🔗 CONVIDAR", callback_data="menu_indicacao")],
            [InlineKeyboardButton("🔙 Voltar", callback_data="menu_servicos")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await query.edit_message_text(
            f"⚠️ SALDO INSUFICIENTE!\n\n"
            f"💰 Seu saldo: R$ {saldo:.2f}\n"
            f"💳 Necessário: R$ {preco:.2f}\n\n"
            f"🔥 NÃO PERCA ESTA OPORTUNIDADE!\n"
            f"⏰ Promoção acaba em: {calculate_time_left()}\n\n"
            f"🚨 RECARREGUE AGORA ou PERCA esta chance!",
            reply_markup=reply_markup
        )
        return

    # Tentar comprar número
    await query.edit_message_text("🔄 PROCESSANDO SUA COMPRA VIP...\n\n⚡ Procurando o melhor número disponível...")

    # Mapear países para códigos da 5sim
    country_code = PAISES_DISPONIVEIS[pais]["code"]

    # Mapear serviços para códigos da 5sim
    service_codes = {
        "whatsapp": "whatsapp",
        "telegram": "telegram", 
        "instagram": "instagram",
        "facebook": "facebook",
        "twitter": "twitter",
        "google": "google",
        "linkedin": "linkedin",
        "pinterest": "pinterest",
        "viber": "viber",
        "paypal": "paypal",
        "skype": "skype",
        "discord": "discord",
        "yahoo": "yahoo",
        "netflix": "netflix",
        "tinder": "tinder",
        "badoo": "badoo",
        "spotify": "spotify",
        "bumble": "bumble",
        "dropbox": "dropbox",
        "snapchat": "snapchat"
    }

    service_code = service_codes.get(servico, servico)

    # Tentar comprar número real via 5sim usando método assíncrono
    try:
        numero_data = await fivesim.buy_number_async(service_code, country_code)
    except Exception as e:
        logger.error(f"Erro ao usar método assíncrono, tentando síncrono: {e}")
        numero_data = fivesim.buy_number(service_code, country_code)
    
    numero_disponivel = numero_data is not None

    # Obter estatísticas fixas
    stats = get_stats_fake()

    if not numero_disponivel:
        keyboard = [
            [InlineKeyboardButton("🔔 AVISAR QUANDO DISPONÍVEL", callback_data="notificar_disponivel")],
            [InlineKeyboardButton("🔄 TENTAR OUTRO PAÍS", callback_data=f"servico_{servico}")],
            [InlineKeyboardButton("🔙 Voltar", callback_data="menu_servicos")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await query.edit_message_text(
            f"😔 ESGOTADO TEMPORARIAMENTE!\n\n"
            f"🔥 {servico.upper()} para {PAISES_DISPONIVEIS[pais]['nome']} está em alta demanda!\n"
            f"📱 {stats['numeros_vendidos_hoje']} números já vendidos hoje\n\n"
            f"💡 DICA: Números ficam disponíveis a cada 3 horas!\n"
            f"🔔 Ative as notificações para ser o primeiro a saber!\n\n"
            f"⏰ Oferta ainda válida por: {calculate_time_left()}",
            reply_markup=reply_markup
        )
        return

    # Processar compra com sucesso
    await asyncio.sleep(1)  # Simular processamento

    db.deduzir_saldo(user_id, preco)

    # Usar número real da API
    numero_telefone = numero_data.get("phone", "Número não disponível")
    activation_id = numero_data.get("id", 0)

    # Salvar no banco de dados com melhor tratamento de erro
    try:
        with db._lock:
            conn = db.get_connection()
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO numeros_sms (user_id, servico, pais, numero, preco, desconto_aplicado, status)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (user_id, servico, pais, numero_telefone, preco, 0, "aguardando_sms"))
            conn.commit()
            conn.close()
    except Exception as e:
        logger.error(f"Erro ao salvar número no banco: {e}")

    sucesso_msg = get_random_sucesso()

    keyboard = [
        [InlineKeyboardButton("🔥 COMPRAR OUTRO", callback_data="menu_servicos")],
        [InlineKeyboardButton("💎 RECARREGAR VIP", callback_data="menu_recarga")],
        [InlineKeyboardButton("🏠 Menu Principal", callback_data="menu_principal")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.edit_message_text(
        f"{sucesso_msg}\n\n"
        f"📱 Serviço: {servico.upper()}\n"
        f"🌍 País: {PAISES_DISPONIVEIS[pais]['nome']}\n"
        f"📞 Número: {numero_telefone}\n"
        f"💰 Pago: R$ {preco:.2f}\n"
        f"━━━━━━━━━━━━━━━━━━━━\n\n"
        f"📨 AGUARDE O CÓDIGO SMS...\n"
        f"🔔 Você será notificado quando chegar!\n\n"
        f"⚡ Aproveite e compre mais números!",
        reply_markup=reply_markup
    )

@rate_limit
async def menu_recarga(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Menu de recarga premium"""
    query = update.callback_query
    if not query:
        return

    await query.answer()
    
    # Armazenar ID da mensagem atual
    if query.from_user:
        store_message_id(query.from_user.id, query.message.message_id)

    stats = get_stats_fake()
    tempo_restante = calculate_time_left()
    urgencia_msg = get_random_urgencia()

    keyboard = []
    for valor in VALORES_RECARGA:
        # Calcular bônus fixo
        # Calcular bônus usando função centralizada
        bonus = calcular_bonus(valor)
        if bonus > 0:
            valor_total = valor + bonus
            bonus_text = f" (PAGUE R$ {valor_total}) + R$ {bonus} BÔNUS"
        else:
            bonus_text = ""

        if valor >= 50:
            keyboard.append([
                InlineKeyboardButton(
                    f"🔥 R$ {valor}{bonus_text} - POPULAR!",
                    callback_data=f"recarga_{valor}"
                )
            ])
        else:
            keyboard.append([
                InlineKeyboardButton(
                    f"💰 R$ {valor} - INICIANTE",
                    callback_data=f"recarga_{valor}"
                )
            ])

    keyboard.append([InlineKeyboardButton("🔙 Voltar", callback_data="menu_principal")])
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.edit_message_text(
        f"💎 SUPER RECARGA VIP! 💎\n\n"
        f"🚨 PROMOÇÃO RELÂMPAGO ATIVA!\n"
        f"💥 ATÉ 25% DE BÔNUS EXTRA!\n"
        f"⏰ RESTAM APENAS {tempo_restante}!\n"
        f"━━━━━━━━━━━━━━━━━━━━\n\n"
        f"🏆 BENEFÍCIOS EXCLUSIVOS:\n"
        f"💰 R$ 50 → PAGUE R$ 58 + 5 números GRÁTIS\n"
        f"🎯 R$ 100 → PAGUE R$ 120 + 10 números GRÁTIS\n"
        f"🔥 R$ 200 → PAGUE R$ 250 + 20 números GRÁTIS\n\n"
        f"🚀 APROVADO POR {stats['usuarios_online']} CLIENTES VIP!\n"
        f"📈 {stats['pessoas_recarregaram']} pessoas recarregaram na última hora!\n"
        f"{urgencia_msg}\n\n"
        f"💳 ESCOLHA SEU PACOTE PREMIADO:\n"
        f"━━━━━━━━━━━━━━━━━━━━",
        reply_markup=reply_markup
    )

async def selecionar_valor_recarga(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Selecionar moeda após escolher valor"""
    query = update.callback_query
    if not query or not query.data or not query.from_user:
        return

    await query.answer()

    valor = int(query.data.split("_")[1])
    user_id = query.from_user.id

    # Calcular bônus fixo
    if valor >= 200:
        bonus = 50
        numeros_gratis = 20
    elif valor >= 100:
        bonus = 20
        numeros_gratis = 10
    elif valor >= 50:
        bonus = 8
        numeros_gratis = 5
    else:
        bonus = 0
        numeros_gratis = 0

    # Valor a pagar é apenas o valor base (sem bônus)
    valor_total_pagar = valor

    # Armazenar dados
    temp_data[user_id] = {
        "valor_recarga": valor,
        "bonus": bonus,
        "valor_total_pagar": valor_total_pagar
    }

    total_receber = valor + bonus

    # Criar teclado com criptomoedas em grupos de 2
    keyboard = []
    for i in range(0, len(MOEDAS_CRYPTO), 2):
        row = []
        for j in range(2):
            if i + j < len(MOEDAS_CRYPTO):
                moeda = MOEDAS_CRYPTO[i + j]
                row.append(InlineKeyboardButton(
                    f"{moeda['symbol']} {moeda['code']}", 
                    callback_data=f"moeda_{moeda['code']}"
                ))
        keyboard.append(row)

    keyboard.append([InlineKeyboardButton("🔙 Voltar", callback_data="menu_recarga")])
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.edit_message_text(
        f"💎 RECARGA VIP SELECIONADA!\n\n"
        f"💳 VALOR A PAGAR: R$ {valor}\n"
        f"🎁 Bônus incluído: R$ {bonus}\n"
        f"📊 Você receberá: R$ {total_receber}\n"
        f"🎯 Números grátis: {numeros_gratis}\n"
        f"━━━━━━━━━━━━━━━━━━━━\n\n"
        f"🚨 OFERTA LIMITADA!\n"
        f"⏰ Válida por: {calculate_time_left()}\n\n"
        f"🪙 Escolha a criptomoeda:\n"
        f"━━━━━━━━━━━━━━━━━━━━",
        reply_markup=reply_markup
    )

async def processar_pagamento(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Processar pagamento após selecionar moeda"""
    query = update.callback_query
    if not query or not query.data or not query.from_user:
        return

    await query.answer()

    moeda = query.data.split("_")[1]
    user_id = query.from_user.id

    if user_id not in temp_data:
        await query.edit_message_text("❌ Erro: Dados não encontrados. Tente novamente.")
        return

    valor = temp_data[user_id]["valor_recarga"]
    bonus = temp_data[user_id]["bonus"]
    valor_total_pagar = temp_data[user_id]["valor_total_pagar"]

    await query.edit_message_text("🔄 GERANDO PAGAMENTO VIP...\n\n💎 Preparando sua transação exclusiva...")

    # Criar fatura usando método assíncrono para melhor performance
    try:
        invoice, erro = await crypto_pay.create_invoice_async(valor_total_pagar, moeda, user_id)
    except Exception as e:
        logger.error(f"Erro ao usar método assíncrono, tentando síncrono: {e}")
        invoice, erro = crypto_pay.create_invoice(valor_total_pagar, moeda, user_id)

    if erro:
        await query.edit_message_text(f"❌ Erro ao gerar pagamento: {erro}")
        return

    # Calcular números grátis baseado no valor base
    if valor >= 200:
        numeros_gratis = 20
    elif valor >= 100:
        numeros_gratis = 10
    elif valor >= 50:
        numeros_gratis = 5
    else:
        numeros_gratis = 0

    total_receber = valor + bonus

    # Obter símbolo e nome da moeda
    crypto_symbol = get_crypto_symbol(moeda)
    crypto_name = get_crypto_name(moeda)
    
    # Usar método assíncrono para obter preço se possível
    try:
        valor_crypto = await crypto_pay.get_crypto_price_async(valor_total_pagar, moeda)
    except Exception as e:
        logger.error(f"Erro ao usar método assíncrono, tentando síncrono: {e}")
        valor_crypto = crypto_pay.get_crypto_price(valor_total_pagar, moeda)

    # Salvar transação pendente no banco
    try:
        with db._lock:
            conn = db.get_connection()
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO transacoes (user_id, tipo, valor, moeda, status, invoice_id)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (user_id, 'deposito', valor_total_pagar, moeda, 'pendente', invoice["invoice_id"]))
            conn.commit()
            conn.close()
    except Exception as e:
        logger.error(f"Erro ao salvar transação pendente: {e}")

    keyboard = [
        [InlineKeyboardButton("💳 PAGAR AGORA", url=invoice["bot_invoice_url"])],
        [InlineKeyboardButton("🔙 Voltar", callback_data="menu_recarga")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.edit_message_text(
        f"💎 PAGAMENTO VIP GERADO!\n\n"
        f"💳 TOTAL A PAGAR: R$ {valor}\n"
        f"🎁 Bônus incluído: R$ {bonus}\n"
        f"📊 Você receberá: R$ {total_receber}\n"
        f"🎯 Números grátis: {numeros_gratis}\n"
        f"{crypto_symbol} Moeda: {crypto_name} ({moeda})\n"
        f"💵 Valor a pagar: {valor_crypto} {moeda}\n"
        f"━━━━━━━━━━━━━━━━━━━━\n\n"
        f"🚨 IMPORTANTE:\n"
        f"• Pague o valor EXATO: {valor_crypto} {moeda}\n"
        f"• Processamento automático APENAS com valor correto\n"
        f"• Bônus será creditado após confirmação\n"
        f"• Valores incorretos NÃO serão processados\n\n"
        f"⏰ Link válido por 1 hora",
        reply_markup=reply_markup
    )

async def menu_indicacao(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Menu de indicações premium"""
    query = update.callback_query
    if not query or not query.from_user:
        return

    await query.answer()

    user_id = query.from_user.id
    user_data = db.get_user(user_id)

    if not user_data:
        await query.edit_message_text("❌ Erro: Usuário não encontrado.")
        return

    indicacoes = user_data[8] if len(user_data) > 8 else 0
    stats = get_stats_fake()

    keyboard = [
        [InlineKeyboardButton("📤 COMPARTILHAR LINK", callback_data=f"compartilhar_{user_id}")],
        [InlineKeyboardButton("🎯 ESTRATÉGIAS DE INDICAÇÃO", callback_data="estrategias_indicacao")],
        [InlineKeyboardButton("🔙 Voltar", callback_data="menu_principal")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.edit_message_text(
        f"👑 PROGRAMA VIP DE INDICAÇÕES\n\n"
        f"📊 Suas indicações: {indicacoes}\n"
        f"💰 Ganhos estimados: R$ {indicacoes * 12:.0f}\n"
        f"━━━━━━━━━━━━━━━━━━━━\n\n"
        f"🎁 RECOMPENSAS EXCLUSIVAS:\n"
        f"• A cada pessoa que indicar que depositar R$ 20+ = 2 números GRÁTIS para você\n"
        f"• A pessoa indicada também ganha 2 números GRÁTIS após confirmação do pagamento\n"
        f"• Sem limite de indicações - ganhe infinitamente!\n\n"
        f"🔥 HOJE: +{stats['novas_indicacoes']} novas indicações\n"
        f"💎 Seja um INFLUENCIADOR VIP!",
        reply_markup=reply_markup
    )

async def compartilhar_indicacao(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Compartilhar link de indicação premium"""
    query = update.callback_query
    if not query or not query.data or not context.bot.username:
        return

    await query.answer()

    user_id = int(query.data.split("_")[1])

    # Gerar código de indicação único usando JSON
    referral_code = get_or_create_referral_code_json(user_id)

    texto_compartilhamento = (
        f"🤖 Olá! Descobri este bot incrível para receber códigos SMS!\n\n"
        f"📱 Números para WhatsApp, Telegram, Instagram e muito mais!\n"
        f"💰 Melhores preços do mercado!\n"
        f"🎁 Faça seu primeiro depósito de R$ 20+ e ganhe 2 números grátis!\n\n"
        f"🤖 Link do bot: https://t.me/{context.bot.username}?start={referral_code}"
    )

    link_indicacao = f"https://t.me/{context.bot.username}?start={referral_code}"

    # URL para compartilhamento direto no Telegram - só enviar o texto, sem URL duplicada
    texto_encoded = urllib.parse.quote(texto_compartilhamento)
    share_url = f"https://t.me/share/url?text={texto_encoded}"

    keyboard = [
        [InlineKeyboardButton("📤 COMPARTILHAR LINK VIP", url=share_url)],
        [InlineKeyboardButton("📋 COPIAR LINK", callback_data=f"copiar_link_{user_id}")],
        [InlineKeyboardButton("📝 COPIAR TEXTO COMPLETO", callback_data=f"copiar_texto_{user_id}")],
        [InlineKeyboardButton("🔙 Voltar", callback_data="menu_indicacao")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.edit_message_text(
        f"📤 LINK VIP GERADO!\n\n"
        f"🎯 Seu código exclusivo: {referral_code}\n"
        f"🔗 Link personalizado: {link_indicacao}\n\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🚀 CLIQUE EM 'COMPARTILHAR LINK VIP' para abrir diretamente a janela de encaminhamento do Telegram!\n\n"
        f"💬 Mensagem que será enviada:\n"
        f"━━━━━━━━━━━━━━━━━━━━\n\n"
        f"{texto_compartilhamento}\n\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"💡 O Telegram abrirá automaticamente para você escolher os contatos!",
        reply_markup=reply_markup
    )

async def menu_ajuda(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Menu de ajuda premium"""
    query = update.callback_query
    if not query:
        return

    await query.answer()

    keyboard = [
        [InlineKeyboardButton("🔙 Voltar", callback_data="menu_principal")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    # Pegar alguns exemplos de preços
    preco_min = get_min_price_for_service()

    await query.edit_message_text(
        f"💎 SUPORTE VIP 24/7\n\n"
        f"📱 Como usar:\n"
        f"1. Recarregue saldo (bônus incluído)\n"
        f"2. Escolha o serviço desejado\n"
        f"3. Selecione o país\n"
        f"4. Aguarde o código SMS\n\n"
        f"💰 Preços atualizados:\n"
        f"• A partir de: R$ {preco_min:.2f}\n"
        f"• WhatsApp: R$ 1,96 - R$ 10,92\n"
        f"• Telegram: R$ 0,91 - R$ 11,06\n"
        f"• Instagram: R$ 1,05 - R$ 2,45\n\n"
        f"🎁 Sistema de Indicações:\n"
        f"• A cada indicação que depositar R$ 20+ você ganha 2 números grátis\n"
        f"• A pessoa indicada também ganha 2 números grátis\n"
        f"• Sem limite de indicações - ganhe infinitamente!\n\n"
        f"💎 Bônus de Recarga:\n"
        f"• Recarga R$ 50+ = 15% extra + 5 números grátis\n"
        f"• Recarga R$ 100+ = 20% extra + 10 números grátis\n"
        f"• Recarga R$ 200+ = 25% extra + 20 números grátis\n\n"
        f"🔥 MELHORES PREÇOS DO MERCADO!\n"
        f"📞 Suporte: Entre em contato com o administrador",
        reply_markup=reply_markup
    )

async def estrategias_indicacao(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Estratégias de indicação"""
    query = update.callback_query
    if not query:
        return

    await query.answer()

    keyboard = [
        [InlineKeyboardButton("🔙 Voltar", callback_data="menu_indicacao")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.edit_message_text(
        f"🎯 ESTRATÉGIAS DE INDICAÇÃO\n\n"
        f"💡 DICAS PARA GANHAR MAIS:\n\n"
        f"📱 1. REDES SOCIAIS\n"
        f"• Compartilhe nos grupos do WhatsApp\n"
        f"• Poste no seu Instagram Stories\n"
        f"• Publique no Facebook\n\n"
        f"👥 2. AMIGOS E FAMÍLIA\n"
        f"• Indique para quem precisa de números SMS\n"
        f"• Explique os benefícios e preços baixos\n"
        f"• Mostre como é fácil e seguro\n\n"
        f"🎁 3. INCENTIVOS\n"
        f"• Explique que eles ganham 2 números grátis\n"
        f"• Mostre os melhores preços do mercado\n"
        f"• Fale sobre o bônus de boas-vindas\n\n"
        f"💰 GANHOS POTENCIAIS:\n"
        f"• 5 indicações = R$ 60+ em números grátis\n"
        f"• 10 indicações = R$ 120+ em números grátis\n"
        f"• Sem limite de ganhos!",
        reply_markup=reply_markup
    )

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Gerenciador principal de callbacks"""
    query = update.callback_query
    if not query or not query.data:
        return

    data = query.data

    if data == "menu_servicos":
        await menu_servicos(update, context)
    elif data == "menu_recarga":
        await menu_recarga(update, context)
    elif data == "menu_indicacao":
        await menu_indicacao(update, context)
    elif data == "estrategias_indicacao":
        await estrategias_indicacao(update, context)
    elif data == "menu_ajuda":
        await menu_ajuda(update, context)
    elif data == "menu_principal":
        await start(update, context)
    elif data.startswith("servico_"):
        await selecionar_servico(update, context)
    elif data.startswith("pais_"):
        await selecionar_pais(update, context)
    elif data.startswith("recarga_"):
        await selecionar_valor_recarga(update, context)
    elif data.startswith("moeda_"):
        await processar_pagamento(update, context)
    elif data.startswith("compartilhar_"):
        await compartilhar_indicacao(update, context)
    elif data.startswith("copiar_texto_"):
        await copiar_texto_indicacao(update, context)
    elif data.startswith("copiar_link_"):
        await copiar_link_indicacao(update, context)
    elif data.startswith("admin_"):
        await handle_admin_callback(update, context)

async def copiar_texto_indicacao(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Mostra o texto para copiar"""
    query = update.callback_query
    if not query:
        return

    await query.answer("Texto pronto para copiar!")

    user_id = int(query.data.split("_")[2])
    referral_code = get_or_create_referral_code_json(user_id)

    if not context.bot.username:
        return

    link_indicacao = f"https://t.me/{context.bot.username}?start={referral_code}"

    texto_compartilhamento = (
        f"🤖 Olá! Descobri este bot incrível para receber códigos SMS!\n\n"
        f"📱 Números para WhatsApp, Telegram, Instagram e muito mais!\n"
        f"💰 Melhores preços do mercado!\n"
        f"🎁 Faça seu primeiro depósito de R$ 20+ e ganhe 2 números grátis!\n\n"
        f"🤖 Link do bot: {link_indicacao}"
    )

    await query.edit_message_text(
        f"📋 COPIE O TEXTO ABAIXO:\n\n"
        f"━━━━━━━━━━━━━━━━━━━━\n\n"
        f"{texto_compartilhamento}\n\n"
        f"━━━━━━━━━━━━━━━━━━━━\n\n"
        f"💡 Cole esse texto em qualquer lugar e envie!",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔙 Voltar", callback_data="menu_indicacao")]
        ])
    )

async def copiar_link_indicacao(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Mostra apenas o link para copiar"""
    query = update.callback_query
    if not query:
        return

    await query.answer("Link pronto para copiar!")

    user_id = int(query.data.split("_")[2])
    referral_code = get_or_create_referral_code_json(user_id)

    if not context.bot.username:
        return

    link_indicacao = f"https://t.me/{context.bot.username}?start={referral_code}"

    await query.edit_message_text(
        f"🔗 COPIE O LINK ABAIXO:\n\n"
        f"━━━━━━━━━━━━━━━━━━━━\n\n"
        f"{link_indicacao}\n\n"
        f"━━━━━━━━━━━━━━━━━━━━\n\n"
        f"💡 Cole esse link em qualquer lugar!\n"
        f"🎯 Cada pessoa que usar seu link e depositar R$ 20+ você ganha 2 números grátis!",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔙 Voltar", callback_data="menu_indicacao")]
        ])
    )

# Comandos de Administração
async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Comando /admin - Painel administrativo"""
    if not update.effective_user or not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ ACESSO NEGADO! Você não tem permissão para este comando.")
        return

    # Apagar mensagens anteriores (bot + usuário)
    await delete_previous_messages(context, update.message.chat_id, update.effective_user.id, update.message.message_id)

    keyboard = [
        [
            InlineKeyboardButton("📊 ESTATÍSTICAS", callback_data="admin_stats"),
            InlineKeyboardButton("💰 PAGAMENTOS", callback_data="admin_payments")
        ],
        [
            InlineKeyboardButton("🎁 PROMOÇÕES", callback_data="admin_promos"),
            InlineKeyboardButton("👥 USUÁRIOS", callback_data="admin_users")
        ],
        [
            InlineKeyboardButton("🔧 CONFIGURAÇÕES", callback_data="admin_config"),
            InlineKeyboardButton("📤 BROADCAST", callback_data="admin_broadcast")
        ]
    ]

    reply_markup = InlineKeyboardMarkup(keyboard)

    # Usar timezone do Brasil (UTC-3)
    from datetime import timezone, timedelta
    brasilia_tz = timezone(timedelta(hours=-3))
    now_brasilia = datetime.now(brasilia_tz)

    sent_message = await update.message.reply_text(
        f"🛠️ PAINEL ADMINISTRATIVO\n\n"
        f"👑 Bem-vindo, Administrador!\n"
        f"📅 Data: {now_brasilia.strftime('%d/%m/%Y %H:%M')} (UTC-3)\n\n"
        f"Escolha uma opção:",
        reply_markup=reply_markup
    )
    
    # Armazenar ID da mensagem enviada
    store_message_id(update.effective_user.id, sent_message.message_id)

async def dar_saldo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Comando /dar_saldo - Dar saldo para usuário COM BÔNUS AUTOMÁTICO"""
    if not update.effective_user or not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ ACESSO NEGADO! Você não tem permissão para este comando.")
        return

    # Apagar mensagem do comando
    try:
        await delete_previous_messages(context, update.message.chat_id, update.effective_user.id, update.message.message_id)
    except Exception as e:
        logger.error(f"Erro ao apagar mensagem: {e}")

    if not context.args or len(context.args) < 2:
        sent_message = await context.bot.send_message(
            update.message.chat_id,
            "❌ USO: /dar_saldo [user_id] [valor]"
        )
        store_message_id(update.effective_user.id, sent_message.message_id)
        return

    try:
        user_id = int(context.args[0])
        valor = float(context.args[1])

        # Calcular bônus usando função centralizada
        bonus = calcular_bonus(valor)
        
        # Processar como depósito completo (saldo + bônus)
        db.processar_deposito(user_id, valor, bonus)

        # Adicionar números grátis baseado no valor
        if valor >= 200:
            numeros_gratis = 20
        elif valor >= 100:
            numeros_gratis = 10
        elif valor >= 50:
            numeros_gratis = 5
        else:
            numeros_gratis = 0

        if numeros_gratis > 0:
            with db._lock:
                conn = db.get_connection()
                cursor = conn.cursor()
                cursor.execute('UPDATE usuarios SET numeros_gratis = numeros_gratis + ? WHERE user_id = ?', (numeros_gratis, user_id))
                conn.commit()
                conn.close()

        try:
            if bonus > 0:
                await context.bot.send_message(
                    user_id,
                    f"🎁 SALDO ADMINISTRATIVO COM BÔNUS!\n\n"
                    f"💰 Saldo base: R$ {valor:.2f}\n"
                    f"🎁 Bônus ganho: R$ {bonus:.2f}\n"
                    f"📊 Total creditado: R$ {valor + bonus:.2f}\n"
                    f"🎯 Números grátis: {numeros_gratis}\n\n"
                    f"🎉 Aproveite para comprar números SMS!"
                )
            else:
                await context.bot.send_message(
                    user_id,
                    f"🎁 SALDO ADMINISTRATIVO!\n\n"
                    f"💰 Valor creditado: R$ {valor:.2f}\n"
                    f"🎉 Aproveite para comprar números SMS!"
                )
        except Exception as e:
            logger.error(f"Erro ao notificar usuário: {e}")

        sent_message = await context.bot.send_message(
            update.message.chat_id,
            f"✅ SALDO CONCEDIDO COM BÔNUS!\n\n"
            f"👤 Usuário: {user_id}\n"
            f"💰 Saldo base: R$ {valor:.2f}\n"
            f"🎁 Bônus: R$ {bonus:.2f}\n"
            f"📊 Total: R$ {valor + bonus:.2f}\n"
            f"🎯 Números grátis: {numeros_gratis}\n"
            f"🔄 Saldo atualizado com sucesso!"
        )
        store_message_id(update.effective_user.id, sent_message.message_id)

    except (ValueError, IndexError):
        sent_message = await context.bot.send_message(
            update.message.chat_id,
            "❌ ERRO: Use números válidos! Exemplo: /dar_saldo 123456789 25.50"
        )
        store_message_id(update.effective_user.id, sent_message.message_id)

async def dar_bonus(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Comando /dar_bonus - Dar apenas bônus para usuário (sem saldo base)"""
    if not update.effective_user or not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ ACESSO NEGADO! Você não tem permissão para este comando.")
        return

    # Apagar mensagem do comando
    try:
        await delete_previous_messages(context, update.message.chat_id, update.effective_user.id, update.message.message_id)
    except Exception as e:
        logger.error(f"Erro ao apagar mensagem: {e}")

    if not context.args or len(context.args) < 2:
        sent_message = await context.bot.send_message(
            update.message.chat_id,
            "❌ USO: /dar_bonus [user_id] [valor_bonus]"
        )
        store_message_id(update.effective_user.id, sent_message.message_id)
        return

    try:
        user_id = int(context.args[0])
        valor_bonus = float(context.args[1])

        # Adicionar apenas ao saldo de bônus
        db.update_saldo_bonus(user_id, valor_bonus)

        try:
            await context.bot.send_message(
                user_id,
                f"🎁 BÔNUS ESPECIAL!\n\n"
                f"🎁 Você recebeu R$ {valor_bonus:.2f} de bônus!\n"
                f"🎉 Use primeiro nas suas compras!"
            )
        except Exception as e:
            logger.error(f"Erro ao notificar usuário: {e}")

        sent_message = await context.bot.send_message(
            update.message.chat_id,
            f"✅ BÔNUS CONCEDIDO!\n\n"
            f"👤 Usuário: {user_id}\n"
            f"🎁 Bônus: R$ {valor_bonus:.2f}\n"
            f"🔄 Bônus atualizado com sucesso!"
        )
        store_message_id(update.effective_user.id, sent_message.message_id)

    except (ValueError, IndexError):
        sent_message = await context.bot.send_message(
            update.message.chat_id,
            "❌ ERRO: Use números válidos! Exemplo: /dar_bonus 123456789 10.50"
        )
        store_message_id(update.effective_user.id, sent_message.message_id)

async def dar_numeros(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Comando /dar_numeros - Dar números grátis para usuário"""
    if not update.effective_user or not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ ACESSO NEGADO! Você não tem permissão para este comando.")
        return

    # Apagar mensagem do comando
    try:
        await delete_previous_messages(context, update.message.chat_id, update.effective_user.id, update.message.message_id)
    except Exception as e:
        logger.error(f"Erro ao apagar mensagem: {e}")

    if not context.args or len(context.args) < 2:
        sent_message = await context.bot.send_message(
            update.message.chat_id,
            "❌ USO: /dar_numeros [user_id] [quantidade]"
        )
        store_message_id(update.effective_user.id, sent_message.message_id)
        return

    try:
        user_id = int(context.args[0])
        quantidade = int(context.args[1])

        conn = sqlite3.connect(db.db_path)
        cursor = conn.cursor()
        cursor.execute('UPDATE usuarios SET numeros_gratis = numeros_gratis + ? WHERE user_id = ?', (quantidade, user_id))
        conn.commit()
        conn.close()

        try:
            await context.bot.send_message(
                user_id,
                f"🎁 NÚMEROS GRÁTIS!\n\n"
                f"📱 Você recebeu {quantidade} números grátis!\n"
                f"🎉 Use /start para ver seus números disponíveis!"
            )
        except Exception as e:
            logger.error(f"Erro ao notificar usuário: {e}")

        sent_message = await context.bot.send_message(
            update.message.chat_id,
            f"✅ NÚMEROS CONCEDIDOS!\n\n"
            f"👤 Usuário: {user_id}\n"
            f"📱 Quantidade: {quantidade}\n"
            f"🔄 Números grátis atualizados!"
        )
        store_message_id(update.effective_user.id, sent_message.message_id)

    except (ValueError, IndexError):
        sent_message = await context.bot.send_message(
            update.message.chat_id,
            "❌ ERRO: Use números válidos! Exemplo: /dar_numeros 123456789 5"
        )
        store_message_id(update.effective_user.id, sent_message.message_id)

async def info_usuario(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Comando /info - Ver informações de usuário"""
    if not update.effective_user or not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ ACESSO NEGADO! Você não tem permissão para este comando.")
        return

    # Apagar mensagem do comando
    try:
        await delete_previous_messages(context, update.message.chat_id, update.effective_user.id, update.message.message_id)
    except Exception as e:
        logger.error(f"Erro ao apagar mensagem: {e}")

    if not context.args:
        sent_message = await context.bot.send_message(
            update.message.chat_id,
            "❌ USO: /info [user_id]"
        )
        store_message_id(update.effective_user.id, sent_message.message_id)
        return

    try:
        user_id = int(context.args[0])
        user_data = db.get_user(user_id)

        if not user_data:
            await update.message.reply_text("❌ Usuário não encontrado!")
            return

        saldo = db.get_saldo(user_id)
        user_stats = db.get_user_stats(user_id)

        # Buscar dados adicionais
        conn = sqlite3.connect(db.db_path)
        cursor = conn.cursor()

        # Buscar números grátis
        cursor.execute("SELECT numeros_gratis FROM usuarios WHERE user_id = ?", (user_id,))
        numeros_gratis = cursor.fetchone()
        numeros_gratis = numeros_gratis[0] if numeros_gratis else 0

        # Buscar indicações válidas
        cursor.execute("SELECT indicacoes_validas FROM usuarios WHERE user_id = ?", (user_id,))
        indicacoes_validas = cursor.fetchone()
        indicacoes_validas = indicacoes_validas[0] if indicacoes_validas else 0

        # Buscar total depositado
        cursor.execute("SELECT total_depositado FROM usuarios WHERE user_id = ?", (user_id,))
        total_depositado = cursor.fetchone()
        total_depositado = total_depositado[0] if total_depositado else 0

        # Buscar código de indicação
        cursor.execute("SELECT codigo_indicacao FROM usuarios WHERE user_id = ?", (user_id,))
        codigo_indicacao = cursor.fetchone()
        codigo_indicacao = codigo_indicacao[0] if codigo_indicacao else 'Não criado'

        conn.close()

        sent_message = await context.bot.send_message(
            update.message.chat_id,
            f"👤 INFORMAÇÕES DO USUÁRIO\n\n"
            f"🆔 ID: {user_data[0]}\n"
            f"👤 Nome: {user_data[2] or 'N/A'}\n"
            f"📱 Username: @{user_data[1] or 'N/A'}\n"
            f"💰 Saldo: R$ {saldo:.2f}\n"
            f"🎁 Números grátis: {numeros_gratis}\n"
            f"👥 Indicador: {user_data[5] or 'Nenhum'}\n"
            f"🔗 Código indicação: {codigo_indicacao}\n"
            f"📅 Registro: {user_data[7][:10] if len(user_data) > 7 else 'N/A'}\n"
            f"💵 Total depositado: R$ {total_depositado:.2f}\n"
            f"📊 Indicações válidas: {indicacoes_validas}\n"
            f"📱 Total compras: {user_stats[0]}\n"
            f"💸 Total gasto: R$ {user_stats[1]:.2f}\n"
            f"💎 Total economizado: R$ {user_stats[2]:.2f}"
        )
        store_message_id(update.effective_user.id, sent_message.message_id)

    except (ValueError, IndexError):
        sent_message = await context.bot.send_message(
            update.message.chat_id,
            "❌ ERRO: Use um ID válido! Exemplo: /info 123456789"
        )
        store_message_id(update.effective_user.id, sent_message.message_id)
    except Exception as e:
        logger.error(f"Erro em info_usuario: {e}")
        sent_message = await context.bot.send_message(
            update.message.chat_id,
            "❌ ERRO: Falha ao buscar informações do usuário."
        )
        store_message_id(update.effective_user.id, sent_message.message_id)

async def broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Comando /broadcast - Enviar mensagem para todos os usuários"""
    if not update.effective_user or not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ ACESSO NEGADO! Você não tem permissão para este comando.")
        return

    # Apagar mensagem do comando
    try:
        await delete_previous_messages(context, update.message.chat_id, update.effective_user.id, update.message.message_id)
    except Exception as e:
        logger.error(f"Erro ao apagar mensagem: {e}")

    if not context.args:
        sent_message = await context.bot.send_message(
            update.message.chat_id,
            "❌ USO: /broadcast [mensagem]"
        )
        store_message_id(update.effective_user.id, sent_message.message_id)
        return

    mensagem = " ".join(context.args)

    conn = sqlite3.connect(db.db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT user_id FROM usuarios")
    usuarios = cursor.fetchall()
    conn.close()

    enviados = 0
    erros = 0

    status_message = await context.bot.send_message(
        update.message.chat_id,
        f"📤 Iniciando broadcast para {len(usuarios)} usuários..."
    )
    store_message_id(update.effective_user.id, status_message.message_id)

    for (user_id,) in usuarios:
        try:
            await context.bot.send_message(user_id, mensagem)
            enviados += 1
            await asyncio.sleep(0.1)  # Evitar rate limit
        except Exception as e:
            erros += 1
            logger.error(f"Erro ao enviar para {user_id}: {e}")

    sent_message = await context.bot.send_message(
        update.message.chat_id,
        f"📊 BROADCAST CONCLUÍDO!\n\n"
        f"✅ Enviados: {enviados}\n"
        f"❌ Erros: {erros}\n"
        f"📱 Total: {len(usuarios)}"
    )
    store_message_id(update.effective_user.id, sent_message.message_id)

async def confirmar_pagamento(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Comando /confirmar - Confirmar pagamento manualmente"""
    if not update.effective_user or not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ ACESSO NEGADO! Você não tem permissão para este comando.")
        return

    # Apagar mensagem do comando
    try:
        await delete_previous_messages(context, update.message.chat_id, update.effective_user.id, update.message.message_id)
    except Exception as e:
        logger.error(f"Erro ao apagar mensagem: {e}")

    if not context.args:
        sent_message = await context.bot.send_message(
            update.message.chat_id,
            "❌ USO: /confirmar [user_id] [valor]"
        )
        store_message_id(update.effective_user.id, sent_message.message_id)
        return

    try:
        user_id = int(context.args[0])
        valor = float(context.args[1])

        # Calcular bônus usando função centralizada
        bonus = calcular_bonus(valor)
        
        # Processar depósito separando saldo base e bônus corretamente
        db.processar_deposito(user_id, valor, bonus)

        # Verificar se é elegível para recompensa de indicação (R$ 20+)
        user_data = db.get_user(user_id)
        if user_data and valor >= 20.0:
            indicador_id = user_data[5]  # campo indicador_id

            if indicador_id:
                # Dar números grátis para o usuário indicado
                conn = sqlite3.connect(db.db_path)
                cursor = conn.cursor()
                cursor.execute('UPDATE usuarios SET numeros_gratis = numeros_gratis + 2 WHERE user_id = ?', (user_id,))
                # Dar números grátis para o indicador
                cursor.execute('UPDATE usuarios SET numeros_gratis = numeros_gratis + 2 WHERE user_id = ?', (indicador_id,))
                # Atualizar contador de indicações válidas
                cursor.execute('UPDATE usuarios SET indicacoes_validas = indicacoes_validas + 1 WHERE user_id = ?', (indicador_id,))
                conn.commit()
                conn.close()

                # Notificar indicador
                try:
                    await context.bot.send_message(
                        indicador_id,
                        f"🎉 RECOMPENSA DE INDICAÇÃO!\n\n"
                        f"💰 Sua indicação depositou R$ {valor:.2f}!\n"
                        f"🎁 Você ganhou 2 números GRÁTIS!\n"
                        f"👤 Use /start para ver seus números grátis!"
                    )
                except Exception as e:
                    logger.error(f"Erro ao notificar indicador: {e}")

                # Notificar usuário indicado
                try:
                    await context.bot.send_message(
                        user_id,
                        f"✅ PAGAMENTO CONFIRMADO!\n\n"
                        f"💰 Valor pago: R$ {valor:.2f}\n"
                        f"🎁 Bônus de recarga: R$ {bonus:.2f}\n"
                        f"📊 Total creditado: R$ {valor + bonus:.2f}\n"
                        f"🎁 EXTRA: Você ganhou 2 números GRÁTIS por ter sido indicado!\n"
                        f"🎉 Seu saldo foi atualizado!\n"
                        f"📱 Agora você pode comprar números SMS!"
                    )
                except Exception as e:
                    logger.error(f"Erro ao notificar usuário: {e}")
            else:
                # Notificar usuário normal
                try:
                    await context.bot.send_message(
                        user_id,
                        f"✅ PAGAMENTO CONFIRMADO!\n\n"
                        f"💰 Valor pago: R$ {valor:.2f}\n"
                        f"🎁 Bônus de recarga: R$ {bonus:.2f}\n"
                        f"📊 Total creditado: R$ {valor + bonus:.2f}\n"
                        f"🎉 Seu saldo foi atualizado!\n"
                        f"📱 Agora você pode comprar números SMS!"
                    )
                except Exception as e:
                    logger.error(f"Erro ao notificar usuário: {e}")
        else:
            # Notificar usuário normal (valor menor que R$ 20)
            try:
                await context.bot.send_message(
                    user_id,
                    f"✅ PAGAMENTO CONFIRMADO!\n\n"
                    f"💰 Valor pago: R$ {valor:.2f}\n"
                    f"🎁 Bônus de recarga: R$ {bonus:.2f}\n"
                    f"📊 Total creditado: R$ {valor + bonus:.2f}\n"
                    f"🎉 Seu saldo foi atualizado!\n"
                    f"📱 Agora você pode comprar números SMS!"
                )
            except Exception as e:
                logger.error(f"Erro ao notificar usuário: {e}")

        sent_message = await context.bot.send_message(
            update.message.chat_id,
            f"✅ PAGAMENTO CONFIRMADO!\n\n"
            f"👤 Usuário: {user_id}\n"
            f"💰 Valor: R$ {valor:.2f}\n"
            f"🔄 Saldo atualizado com sucesso!"
        )
        store_message_id(update.effective_user.id, sent_message.message_id)

    except (ValueError, IndexError):
        sent_message = await context.bot.send_message(
            update.message.chat_id,
            "❌ ERRO: Use números válidos! Exemplo: /confirmar 123456789 25.50"
        )
        store_message_id(update.effective_user.id, sent_message.message_id)

async def handle_admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Gerenciador de callbacks do admin"""
    query = update.callback_query
    if not query or not query.from_user or not is_admin(query.from_user.id):
        await query.answer("❌ Acesso negado!")
        return

    data = query.data

    if data == "admin_stats":
        await admin_stats(update, context)
    elif data == "admin_payments":
        await admin_payments(update, context)
    elif data == "admin_promos":
        await admin_promos(update, context)
    elif data == "admin_users":
        await admin_users(update, context)
    elif data == "admin_config":
        await admin_config(update, context)
    elif data == "admin_broadcast":
        await admin_broadcast_menu(update, context)
    elif data == "admin_give_balance":
        await admin_give_balance(update, context)
    elif data == "admin_give_numbers":
        await admin_give_numbers(update, context)
    elif data == "admin_pending":
        await admin_pending_payments(update, context)
    elif data == "admin_confirmed":
        await admin_confirmed_payments(update, context)
    elif data == "admin_menu":
        await admin_main_menu(update, context)

async def admin_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Estatísticas do sistema"""
    query = update.callback_query
    await query.answer()

    conn = sqlite3.connect(db.db_path)
    cursor = conn.cursor()

    # Estatísticas básicas
    cursor.execute("SELECT COUNT(*) FROM usuarios")
    total_usuarios = cursor.fetchone()[0]

    cursor.execute("SELECT SUM(total_starts) FROM usuarios")
    total_starts = cursor.fetchone()[0] or 0

    cursor.execute("SELECT COUNT(*) FROM transacoes WHERE status = 'confirmado'")
    total_vendas = cursor.fetchone()[0]

    cursor.execute("SELECT SUM(valor) FROM transacoes WHERE status = 'confirmado'")
    total_faturamento = cursor.fetchone()[0] or 0

    cursor.execute("SELECT COUNT(*) FROM numeros_sms")
    total_numeros = cursor.fetchone()[0]

    # Estatísticas do dia
    cursor.execute("""
        SELECT COUNT(*) FROM usuarios 
        WHERE DATE(data_registro) = DATE('now')
    """)
    novos_hoje = cursor.fetchone()[0]

    cursor.execute("""
        SELECT COUNT(*) FROM transacoes 
        WHERE DATE(data_transacao) = DATE('now') AND status = 'confirmado'
    """)
    vendas_hoje = cursor.fetchone()[0]

    conn.close()

    keyboard = [
        [InlineKeyboardButton("🔄 ATUALIZAR", callback_data="admin_stats")],
        [InlineKeyboardButton("🔙 VOLTAR", callback_data="admin_menu")]
    ]

    await query.edit_message_text(
        f"📊 ESTATÍSTICAS DO SISTEMA\n\n"
        f"👥 Total de usuários: {total_usuarios}\n"
        f"🔢 Total de /start: {total_starts}\n"
        f"💰 Total de vendas: {total_vendas}\n"
        f"💵 Faturamento: R$ {total_faturamento:.2f}\n"
        f"📱 Números vendidos: {total_numeros}\n\n"
        f"📅 HOJE ({datetime.now().strftime('%d/%m/%Y')}):\n"
        f"👤 Novos usuários: {novos_hoje}\n"
        f"💳 Vendas do dia: {vendas_hoje}\n\n"
        f"📈 Taxa de conversão: {(total_vendas/total_usuarios*100):.1f}%",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def admin_payments(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Gerenciar pagamentos"""
    query = update.callback_query
    await query.answer()

    conn = sqlite3.connect(db.db_path)
    cursor = conn.cursor()

    # Pagamentos pendentes
    cursor.execute("""
        SELECT COUNT(*) FROM transacoes 
        WHERE status = 'pendente'
    """)
    pendentes = cursor.fetchone()[0]

    # Últimos pagamentos
    cursor.execute("""
        SELECT u.first_name, t.valor, t.data_transacao 
        FROM transacoes t 
        JOIN usuarios u ON t.user_id = u.user_id 
        WHERE t.status = 'confirmado'
        ORDER BY t.data_transacao DESC 
        LIMIT 5
    """)
    ultimos = cursor.fetchall()

    conn.close()

    ultimos_text = ""
    for nome, valor, data in ultimos:
        ultimos_text += f"• {nome}: R$ {valor:.2f}\n"

    keyboard = [
        [InlineKeyboardButton("⏳ PENDENTES", callback_data="admin_pending")],
        [InlineKeyboardButton("✅ CONFIRMADOS", callback_data="admin_confirmed")],
        [InlineKeyboardButton("🔙 VOLTAR", callback_data="admin_menu")]
    ]

    await query.edit_message_text(
        f"💰 GERENCIAR PAGAMENTOS\n\n"
        f"⏳ Pendentes: {pendentes}\n\n"
        f"✅ Últimos confirmados:\n"
        f"{ultimos_text}\n"
        f"💡 Use /confirmar [user_id] [valor] para confirmar manualmente",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def admin_promos(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Criar promoções"""
    query = update.callback_query
    await query.answer()

    keyboard = [
        [InlineKeyboardButton("🎁 DAR SALDO", callback_data="admin_give_balance")],
        [InlineKeyboardButton("📱 DAR NÚMEROS", callback_data="admin_give_numbers")],
        [InlineKeyboardButton("🔙 VOLTAR", callback_data="admin_menu")]
    ]

    await query.edit_message_text(
        f"🎁 CRIAR PROMOÇÕES\n\n"
        f"Comandos disponíveis:\n"
        f"• /dar_saldo [user_id] [valor]\n"
        f"• /dar_numeros [user_id] [quantidade]\n"
        f"• /broadcast [mensagem]\n\n"
        f"💡 Use os comandos no chat para aplicar promoções",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def admin_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Menu principal do admin"""
    query = update.callback_query
    await query.answer()

    keyboard = [
        [
            InlineKeyboardButton("📊 ESTATÍSTICAS", callback_data="admin_stats"),
            InlineKeyboardButton("💰 PAGAMENTOS", callback_data="admin_payments")
        ],
        [
            InlineKeyboardButton("🎁 PROMOÇÕES", callback_data="admin_promos"),
            InlineKeyboardButton("👥 USUÁRIOS", callback_data="admin_users")
        ],
        [
            InlineKeyboardButton("🔧 CONFIGURAÇÕES", callback_data="admin_config"),
            InlineKeyboardButton("📤 BROADCAST", callback_data="admin_broadcast")
        ]
    ]

    reply_markup = InlineKeyboardMarkup(keyboard)

    from datetime import timezone, timedelta
    brasilia_tz = timezone(timedelta(hours=-3))
    now_brasilia = datetime.now(brasilia_tz)

    await query.edit_message_text(
        f"🛠️ PAINEL ADMINISTRATIVO\n\n"
        f"👑 Bem-vindo, Administrador!\n"
        f"📅 Data: {now_brasilia.strftime('%d/%m/%Y %H:%M')} (UTC-3)\n\n"
        f"Escolha uma opção:",
        reply_markup=reply_markup
    )

async def admin_config(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Configurações do sistema"""
    query = update.callback_query
    await query.answer()

    keyboard = [
        [InlineKeyboardButton("🔙 VOLTAR", callback_data="admin_menu")]
    ]

    await query.edit_message_text(
        f"🔧 CONFIGURAÇÕES DO SISTEMA\n\n"
        f"📋 Comandos disponíveis:\n"
        f"• /dar_saldo [user_id] [valor]\n"
        f"• /dar_numeros [user_id] [quantidade]\n"
        f"• /info [user_id]\n"
        f"• /confirmar [user_id] [valor]\n"
        f"• /broadcast [mensagem]\n\n"
        f"💡 Use os comandos no chat para gerenciar o sistema",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def admin_broadcast_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Menu de broadcast"""
    query = update.callback_query
    await query.answer()

    keyboard = [
        [InlineKeyboardButton("🔙 VOLTAR", callback_data="admin_menu")]
    ]

    await query.edit_message_text(
        f"📤 BROADCAST DE MENSAGENS\n\n"
        f"💡 Use o comando /broadcast [mensagem] para enviar uma mensagem para todos os usuários\n\n"
        f"📝 Exemplo:\n"
        f"/broadcast 🔥 PROMOÇÃO ESPECIAL! Melhores preços do mercado!\n\n"
        f"⚠️ Cuidado: A mensagem será enviada para TODOS os usuários!",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def admin_give_balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Dar saldo para usuário"""
    query = update.callback_query
    await query.answer()

    keyboard = [
        [InlineKeyboardButton("🔙 VOLTAR", callback_data="admin_promos")]
    ]

    await query.edit_message_text(
        f"🎁 DAR SALDO PARA USUÁRIO\n\n"
        f"💡 Use o comando:\n"
        f"/dar_saldo [user_id] [valor]\n\n"
        f"📝 Exemplo:\n"
        f"/dar_saldo 123456789 25.50\n\n"
        f"✅ O usuário será notificado automaticamente",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def admin_give_numbers(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Dar números grátis para usuário"""
    query = update.callback_query
    await query.answer()

    keyboard = [
        [InlineKeyboardButton("🔙 VOLTAR", callback_data="admin_promos")]
    ]

    await query.edit_message_text(
        f"📱 DAR NÚMEROS GRÁTIS\n\n"
        f"💡 Use o comando:\n"
        f"/dar_numeros [user_id] [quantidade]\n\n"
        f"📝 Exemplo:\n"
        f"/dar_numeros 123456789 5\n\n"
        f"✅ O usuário será notificado automaticamente",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def admin_pending_payments(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Pagamentos pendentes"""
    query = update.callback_query
    await query.answer()

    conn = sqlite3.connect(db.db_path)
    cursor = conn.cursor()

    cursor.execute("""
        SELECT t.user_id, u.first_name, t.valor, t.moeda, t.data_transacao, t.invoice_id
        FROM transacoes t 
        JOIN usuarios u ON t.user_id = u.user_id 
        WHERE t.status = 'pendente' OR t.status IS NULL
        ORDER BY t.data_transacao DESC 
        LIMIT 10
    """)
    pendentes = cursor.fetchall()
    conn.close()

    if not pendentes:
        pendentes_text = "✅ Nenhum pagamento pendente!"
    else:
        pendentes_text = ""
        for user_id, nome, valor, moeda, data, invoice_id in pendentes:
            data_formatada = data[:16] if data else "N/A"
            pendentes_text += f"• {nome or 'N/A'} (ID: {user_id})\n"
            pendentes_text += f"  💰 Valor: R$ {valor:.2f} ({moeda or 'N/A'})\n"
            pendentes_text += f"  📅 Data: {data_formatada}\n"
            pendentes_text += f"  🆔 Invoice: {invoice_id or 'N/A'}\n\n"

    keyboard = [
        [InlineKeyboardButton("🔄 ATUALIZAR", callback_data="admin_pending")],
        [InlineKeyboardButton("🔙 VOLTAR", callback_data="admin_payments")]
    ]

    await query.edit_message_text(
        f"⏳ PAGAMENTOS PENDENTES\n\n"
        f"{pendentes_text}"
        f"💡 Use /confirmar [user_id] [valor] para confirmar",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def admin_confirmed_payments(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Pagamentos confirmados"""
    query = update.callback_query
    await query.answer()

    conn = sqlite3.connect(db.db_path)
    cursor = conn.cursor()

    cursor.execute("""
        SELECT t.user_id, u.first_name, t.valor, t.moeda, t.data_transacao, t.invoice_id
        FROM transacoes t 
        JOIN usuarios u ON t.user_id = u.user_id 
        WHERE t.status = 'confirmado'
        ORDER BY t.data_transacao DESC 
        LIMIT 15
    """)
    confirmados = cursor.fetchall()
    conn.close()

    if not confirmados:
        confirmados_text = "❌ Nenhum pagamento confirmado ainda!"
    else:
        confirmados_text = ""
        total_confirmados = 0
        for user_id, nome, valor, moeda, data, invoice_id in confirmados:
            data_formatada = data[:16] if data else "N/A"
            confirmados_text += f"✅ {nome or 'N/A'} (ID: {user_id})\n"
            confirmados_text += f"   💰 R$ {valor:.2f} ({moeda or 'N/A'})\n"
            confirmados_text += f"   📅 {data_formatada}\n\n"
            total_confirmados += valor

        confirmados_text += f"━━━━━━━━━━━━━━━━━━━━\n"
        confirmados_text += f"💰 Total confirmado: R$ {total_confirmados:.2f}"

    keyboard = [
        [InlineKeyboardButton("🔄 ATUALIZAR", callback_data="admin_confirmed")],
        [InlineKeyboardButton("🔙 VOLTAR", callback_data="admin_payments")]
    ]

    await query.edit_message_text(
        f"✅ PAGAMENTOS CONFIRMADOS\n\n"
        f"{confirmados_text}",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def admin_users(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Gerenciar usuários"""
    query = update.callback_query
    await query.answer()

    conn = sqlite3.connect(db.db_path)
    cursor = conn.cursor()

    # Top usuários por saldo
    cursor.execute("""
        SELECT first_name, saldo, total_depositado 
        FROM usuarios 
        ORDER BY saldo DESC 
        LIMIT 10
    """)
    top_users = cursor.fetchall()

    conn.close()

    users_text = ""
    for i, (nome, saldo, depositado) in enumerate(top_users, 1):
        users_text += f"{i}. {nome}: R$ {saldo:.2f} (dep: R$ {depositado:.2f})\n"

    keyboard = [
        [InlineKeyboardButton("🔄 ATUALIZAR", callback_data="admin_users")],
        [InlineKeyboardButton("🔙 VOLTAR", callback_data="admin_menu")]
    ]

    await query.edit_message_text(
        f"👥 TOP USUÁRIOS POR SALDO\n\n"
        f"{users_text}\n"
        f"💡 Use /info [user_id] para ver detalhes",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Tratamento global de erros"""
    logger.error(f"Erro capturado: {context.error}")

    # Se há um update, tentar responder ao usuário
    if isinstance(update, Update):
        try:
            if update.message:
                await update.message.reply_text(
                    "⚠️ Ocorreu um erro temporário. Tente novamente em alguns segundos.\n"
                    "Se o problema persistir, entre em contato com o suporte."
                )
            elif update.callback_query:
                await update.callback_query.answer(
                    "❌ Erro temporário. Tente novamente!",
                    show_alert=True
                )
        except Exception as e:
            logger.error(f"Erro ao responder erro para usuário: {e}")

# ========================= SERVIDOR WEB =========================

async def webhook_handler(request):
    """Handler para webhooks do CryptoPay"""
    try:
        data = await request.json()
        logger.info(f"🎯 Webhook recebido: {data}")
        
        # Verificar se é uma atualização de pagamento
        if data.get('update_type') == 'invoice_paid':
            invoice_data = data.get('payload', {})
            invoice_id = invoice_data.get('invoice_id')
            amount = float(invoice_data.get('amount', 0))
            currency = invoice_data.get('asset')
            
            if invoice_id and amount > 0:
                # Processar pagamento automaticamente
                await processar_pagamento_webhook(invoice_id, amount, currency)
                logger.info(f"✅ Pagamento processado via webhook: {invoice_id}")
        
        return web.Response(text="OK", status=200)
    
    except Exception as e:
        logger.error(f"❌ Erro no webhook: {e}")
        return web.Response(text="ERROR", status=500)

async def uptime_handler(request):
    """Handler para UptimeRobot manter o bot ativo"""
    try:
        # Informações básicas do sistema
        uptime_info = {
            "status": "online",
            "service": "Bot SMS Premium",
            "timestamp": datetime.now().isoformat(),
            "render_url": RENDER_URL
        }
        
        logger.info("🟢 UptimeRobot ping recebido - sistema ativo")
        return web.json_response(uptime_info)
    
    except Exception as e:
        logger.error(f"❌ Erro no uptime: {e}")
        return web.Response(text="ERROR", status=500)

async def status_handler(request):
    """Handler para verificar status do sistema"""
    try:
        # Verificar database
        conn = sqlite3.connect(db.db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM usuarios")
        total_users = cursor.fetchone()[0]
        conn.close()
        
        status_info = {
            "status": "healthy",
            "service": "Bot SMS Premium",
            "users": total_users,
            "timestamp": datetime.now().isoformat(),
            "version": "2.0",
            "features": ["SMS Sales", "Crypto Payments", "Auto Bonus", "Rate Limiting"]
        }
        
        return web.json_response(status_info)
    
    except Exception as e:
        logger.error(f"❌ Erro no status: {e}")
        return web.json_response({"status": "error", "message": str(e)}, status=500)

async def processar_pagamento_webhook(invoice_id, amount, currency):
    """Processa pagamento recebido via webhook COM VALIDAÇÃO DE VALOR EXATO"""
    try:
        conn = sqlite3.connect(db.db_path)
        cursor = conn.cursor()
        
        # Buscar transação pendente com dados da invoice
        cursor.execute("""
            SELECT user_id, valor, moeda FROM transacoes 
            WHERE invoice_id = ? AND status = 'pendente'
        """, (invoice_id,))
        
        transacao = cursor.fetchone()
        if not transacao:
            logger.warning(f"⚠️ Transação não encontrada para invoice {invoice_id}")
            conn.close()
            return
        
        user_id, valor_esperado_brl, moeda_esperada = transacao
        
        # VALIDAÇÃO CRÍTICA: Verificar se o valor pago é EXATAMENTE o esperado
        # Converter valor esperado em BRL para crypto
        try:
            valor_crypto_esperado = await crypto_pay.get_crypto_price_async(valor_esperado_brl, currency)
            if not valor_crypto_esperado:
                # Tentar método síncrono como fallback
                valor_crypto_esperado = crypto_pay.get_crypto_price(valor_esperado_brl, currency)
        except Exception as e:
            logger.error(f"Erro ao converter valor esperado: {e}")
            valor_crypto_esperado = crypto_pay.get_crypto_price(valor_esperado_brl, currency)
        
        if not valor_crypto_esperado:
            logger.error(f"❌ Não foi possível validar valor para invoice {invoice_id}")
            conn.close()
            return
        
        # Verificar se valores coincidem (com margem de erro de 1% para flutuações de preço)
        margem_erro = 0.01  # 1% de tolerância
        valor_minimo = valor_crypto_esperado * (1 - margem_erro)
        valor_maximo = valor_crypto_esperado * (1 + margem_erro)
        
        if not (valor_minimo <= amount <= valor_maximo):
            logger.warning(f"🚫 VALOR INCORRETO! Esperado: {valor_crypto_esperado:.8f} {currency}, Recebido: {amount:.8f} {currency}")
            
            # Marcar como valor incorreto
            cursor.execute("""
                UPDATE transacoes 
                SET status = 'valor_incorreto', 
                    observacoes = ? 
                WHERE invoice_id = ?
            """, (f"Esperado: {valor_crypto_esperado:.8f}, Recebido: {amount:.8f}", invoice_id))
            conn.commit()
            conn.close()
            
            # Notificar admin sobre pagamento com valor incorreto
            if ADMIN_ID:
                try:
                    from telegram import Bot
                    bot = Bot(token=BOT_TOKEN)
                    await bot.send_message(
                        chat_id=ADMIN_ID,
                        text=f"🚫 PAGAMENTO COM VALOR INCORRETO!\n\n"
                             f"👤 Usuário: {user_id}\n"
                             f"🆔 Invoice: {invoice_id}\n"
                             f"💰 Esperado: {valor_crypto_esperado:.8f} {currency}\n"
                             f"💳 Recebido: {amount:.8f} {currency}\n"
                             f"📊 Diferença: {((amount - valor_crypto_esperado) / valor_crypto_esperado * 100):.2f}%\n\n"
                             f"⚠️ Pagamento NÃO foi processado automaticamente!"
                    )
                except Exception as e:
                    logger.error(f"Erro ao notificar admin: {e}")
            return
        
        # VALOR CORRETO - Processar pagamento
        logger.info(f"✅ Valor validado: {amount:.8f} {currency} (esperado: {valor_crypto_esperado:.8f})")
        
        # Calcular bônus
        bonus = calcular_bonus(valor_esperado_brl)
        
        # Processar depósito separando saldo base e bônus
        db.processar_deposito(user_id, valor_esperado_brl, bonus)
        
        # Adicionar números grátis baseado no valor
        if valor_esperado_brl >= 200:
            numeros_gratis = 20
        elif valor_esperado_brl >= 100:
            numeros_gratis = 10
        elif valor_esperado_brl >= 50:
            numeros_gratis = 5
        else:
            numeros_gratis = 0

        if numeros_gratis > 0:
            cursor.execute('UPDATE usuarios SET numeros_gratis = numeros_gratis + ? WHERE user_id = ?', (numeros_gratis, user_id))
        
        # Verificar se é elegível para recompensa de indicação (R$ 20+)
        if valor_esperado_brl >= 20.0:
            cursor.execute("SELECT indicador_id FROM usuarios WHERE user_id = ?", (user_id,))
            indicador_result = cursor.fetchone()
            
            if indicador_result and indicador_result[0]:
                indicador_id = indicador_result[0]
                
                # Dar números grátis para ambos
                cursor.execute('UPDATE usuarios SET numeros_gratis = numeros_gratis + 2 WHERE user_id = ?', (user_id,))
                cursor.execute('UPDATE usuarios SET numeros_gratis = numeros_gratis + 2 WHERE user_id = ?', (indicador_id,))
                cursor.execute('UPDATE usuarios SET indicacoes_validas = indicacoes_validas + 1 WHERE user_id = ?', (indicador_id,))
                
                # Notificar indicador
                try:
                    from telegram import Bot
                    bot = Bot(token=BOT_TOKEN)
                    await bot.send_message(
                        indicador_id,
                        f"🎉 RECOMPENSA DE INDICAÇÃO!\n\n"
                        f"💰 Sua indicação depositou R$ {valor_esperado_brl:.2f}!\n"
                        f"🎁 Você ganhou 2 números GRÁTIS!\n"
                        f"👤 Acesse /start para ver seus números!"
                    )
                except Exception as e:
                    logger.error(f"Erro ao notificar indicador: {e}")
        
        # Marcar transação como confirmada
        cursor.execute("""
            UPDATE transacoes 
            SET status = 'confirmado', 
                data_confirmacao = ?,
                valor_crypto_pago = ?,
                moeda_paga = ?
            WHERE invoice_id = ?
        """, (datetime.now().isoformat(), amount, currency, invoice_id))
        
        conn.commit()
        conn.close()
        
        logger.info(f"✅ Pagamento processado automaticamente: User {user_id}, R${valor_esperado_brl}, Bônus: R${bonus}")
        
        # Enviar notificação para o usuário
        try:
            from telegram import Bot
            bot = Bot(token=BOT_TOKEN)
            
            mensagem_usuario = (
                f"✅ PAGAMENTO CONFIRMADO AUTOMATICAMENTE!\n\n"
                f"💰 Valor depositado: R$ {valor_esperado_brl:.2f}\n"
                f"🎁 Bônus ganho: R$ {bonus:.2f}\n"
                f"📊 Total creditado: R$ {valor_esperado_brl + bonus:.2f}\n"
            )
            
            if numeros_gratis > 0:
                mensagem_usuario += f"🎯 Números grátis: {numeros_gratis}\n"
            
            mensagem_usuario += f"\n🚀 Seu saldo foi atualizado automaticamente!\n📱 Use /start para comprar números SMS!"
            
            await bot.send_message(
                chat_id=user_id,
                text=mensagem_usuario
            )
        except Exception as e:
            logger.error(f"Erro ao enviar notificação: {e}")
    
    except Exception as e:
        logger.error(f"❌ Erro ao processar pagamento webhook: {e}")

async def start_web_server():
    """Inicia servidor web para webhooks e uptime"""
    try:
        app = web.Application()
        
        # Configurar rotas
        app.router.add_post('/webhook', webhook_handler)
        app.router.add_get('/uptime', uptime_handler)
        app.router.add_get('/status', status_handler)
        app.router.add_get('/', status_handler)  # Root também mostra status
        
        # Iniciar servidor na porta 5000
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, '0.0.0.0', 5000)
        await site.start()
        
        logger.info(f"🌐 Servidor web iniciado em {RENDER_URL}")
        logger.info("📡 Endpoints disponíveis:")
        logger.info(f"   • {RENDER_URL}/webhook - Webhooks CryptoPay")
        logger.info(f"   • {RENDER_URL}/uptime - UptimeRobot")
        logger.info(f"   • {RENDER_URL}/status - Status do sistema")
        
        return runner
        
    except Exception as e:
        logger.error(f"❌ Erro ao iniciar servidor web: {e}")
        raise

async def main():
    """Função principal com servidor híbrido"""
    if not BOT_TOKEN:
        logger.error("BOT_TOKEN não configurado nos secrets!")
        return

    try:
        # Criar aplicação
        application = Application.builder().token(BOT_TOKEN).build()

        # Adicionar handlers
        application.add_handler(CommandHandler("start", start))
        application.add_handler(CommandHandler("admin", admin_command))
        application.add_handler(CommandHandler("confirmar", confirmar_pagamento))
        application.add_handler(CommandHandler("dar_saldo", dar_saldo))
        application.add_handler(CommandHandler("dar_bonus", dar_bonus))
        application.add_handler(CommandHandler("dar_numeros", dar_numeros))
        application.add_handler(CommandHandler("info", info_usuario))
        application.add_handler(CommandHandler("broadcast", broadcast))
        application.add_handler(CallbackQueryHandler(handle_callback))

        # Adicionar handler de erros
        application.add_error_handler(error_handler)

        # Iniciar aplicação
        await application.initialize()
        await application.start()

        # Iniciar servidor web em paralelo
        web_runner = await start_web_server()
        
        logger.info("🚀 Bot Premium iniciado! Sistema VIP ativo.")
        logger.info(f"🌐 Servidor web rodando em {RENDER_URL}")
        
        # Configurar webhook do CryptoPay se disponível
        if CRYPTOPAY_API_TOKEN:
            await configurar_webhook_cryptopay()
        
        # Usar polling para o bot
        await application.updater.start_polling(
            allowed_updates=["message", "callback_query"],
            drop_pending_updates=True
        )
        
        # Manter ambos serviços rodando
        try:
            while True:
                await asyncio.sleep(1)
        except KeyboardInterrupt:
            logger.info("🛑 Parando serviços...")
            await application.stop()
            await web_runner.cleanup()

    except Exception as e:
        logger.error(f"Erro crítico ao iniciar bot: {e}")
        # Aguardar e tentar reiniciar
        await asyncio.sleep(5)
        logger.info("Tentando reiniciar bot...")
        await main()

async def configurar_webhook_cryptopay():
    """Configura webhook do CryptoPay para pagamentos automáticos"""
    try:
        webhook_url = f"{RENDER_URL}/webhook"
        
        async with aiohttp.ClientSession() as session:
            url = f"{CRYPTOPAY_API_BASE}/setWebhook"
            headers = {
                "Crypto-Pay-API-Token": CRYPTOPAY_API_TOKEN
            }
            data = {
                "webhook_url": webhook_url
            }
            
            async with session.post(url, headers=headers, json=data) as response:
                if response.status == 200:
                    logger.info(f"✅ Webhook CryptoPay configurado: {webhook_url}")
                else:
                    logger.warning(f"⚠️ Falha ao configurar webhook CryptoPay: {response.status}")
                    
    except Exception as e:
        logger.error(f"❌ Erro ao configurar webhook CryptoPay: {e}")

if __name__ == "__main__":
    asyncio.run(main())