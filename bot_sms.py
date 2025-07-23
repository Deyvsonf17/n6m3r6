#!/usr/bin/env python3
"""
Bot de Vendas SMS Premium - Versão Corrigida
Bot Telegram para venda de números SMS premium
"""

import logging
import os
import sqlite3
import asyncio
import aiohttp
import random
import string
import json
import urllib.parse
import threading
import time
import hashlib
import hmac
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes
from collections import defaultdict
from functools import wraps

# Configuração de logs
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Verificar tokens essenciais
BOT_TOKEN = os.getenv("BOT_TOKEN")
CRYPTOPAY_API_TOKEN = os.getenv("CRYPTOPAY_API_TOKEN")
FIVESIM_API_TOKEN = os.getenv("FIVESIM_API_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))

if not BOT_TOKEN:
    logger.error("❌ BOT_TOKEN não encontrado! Configure o token do bot no Secrets.")
    raise ValueError("BOT_TOKEN é obrigatório!")

logger.info("🤖 Bot de Vendas SMS Premium - Iniciando...")
logger.info(f"👑 Admin ID: {ADMIN_ID}")

# Rate limiting
user_rate_limits = defaultdict(list)
RATE_LIMIT_SECONDS = 1.0
MAX_REQUESTS_PER_MINUTE = 20

def rate_limit(func):
    """Decorator para rate limiting por usuário"""
    @wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not update.effective_user:
            return
        
        user_id = update.effective_user.id
        now = time.time()
        
        # Limpar requests antigos
        user_rate_limits[user_id] = [req_time for req_time in user_rate_limits[user_id] 
                                    if now - req_time < 60]
        
        # Verificar rate limit
        if len(user_rate_limits[user_id]) >= MAX_REQUESTS_PER_MINUTE:
            try:
                if hasattr(update, 'message') and update.message:
                    await update.message.reply_text("⚠️ Muitas solicitações! Aguarde um momento.")
                elif hasattr(update, 'callback_query') and update.callback_query:
                    await update.callback_query.answer("⚠️ Aguarde um momento.", show_alert=False)
            except Exception as e:
                logger.error(f"Erro ao enviar mensagem de rate limit: {e}")
            return
        
        # Verificar intervalo mínimo
        if user_rate_limits[user_id] and now - user_rate_limits[user_id][-1] < RATE_LIMIT_SECONDS:
            return
        
        user_rate_limits[user_id].append(now)
        return await func(update, context)
    return wrapper

# Database simples
class SimpleDB:
    def __init__(self):
        self.db_path = "bot_sms.db"
        self.init_db()
    
    def init_db(self):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS usuarios (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                saldo REAL DEFAULT 0.0,
                saldo_bonus REAL DEFAULT 0.0,
                numeros_gratis INTEGER DEFAULT 0,
                data_registro TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                total_depositado REAL DEFAULT 0.0,
                total_gasto REAL DEFAULT 0.0,
                numeros_comprados INTEGER DEFAULT 0
            )
        ''')
        conn.commit()
        conn.close()
        logger.info("✅ Database inicializado")
    
    def get_or_create_user(self, user_id, username=None, first_name=None):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute("SELECT * FROM usuarios WHERE user_id = ?", (user_id,))
        user = cursor.fetchone()
        
        if not user:
            cursor.execute('''
                INSERT INTO usuarios (user_id, username, first_name) 
                VALUES (?, ?, ?)
            ''', (user_id, username, first_name))
            conn.commit()
            logger.info(f"👤 Novo usuário criado: {user_id}")
        
        conn.close()
        return True
    
    def get_saldo(self, user_id):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT saldo FROM usuarios WHERE user_id = ?", (user_id,))
        result = cursor.fetchone()
        conn.close()
        return result[0] if result else 0.0
    
    def get_saldo_bonus(self, user_id):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT saldo_bonus FROM usuarios WHERE user_id = ?", (user_id,))
        result = cursor.fetchone()
        conn.close()
        return result[0] if result else 0.0

# Instância global do database
db = SimpleDB()

@rate_limit
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Comando /start - Menu principal"""
    user = update.effective_user
    if not user:
        return
    
    # Criar usuário se não existir
    db.get_or_create_user(user.id, user.username, user.first_name)
    
    saldo = db.get_saldo(user.id)
    saldo_bonus = db.get_saldo_bonus(user.id)
    
    keyboard = [
        [
            InlineKeyboardButton("📱 COMPRAR NÚMEROS", callback_data="menu_servicos"),
            InlineKeyboardButton("💳 RECARREGAR", callback_data="menu_recarga")
        ],
        [
            InlineKeyboardButton("🔗 INDICAR AMIGOS", callback_data="menu_indicacao"),
            InlineKeyboardButton("❓ AJUDA", callback_data="menu_ajuda")
        ]
    ]
    
    if user.id == ADMIN_ID:
        keyboard.append([
            InlineKeyboardButton("🛠️ ADMIN", callback_data="admin_panel")
        ])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    welcome_text = (
        f"🤖 **BOT SMS PREMIUM**\n\n"
        f"👋 Olá, {user.first_name}!\n"
        f"💰 Saldo: R$ {saldo:.2f}\n"
        f"🎁 Bônus: R$ {saldo_bonus:.2f}\n\n"
        f"📱 **NÚMEROS DISPONÍVEIS:**\n"
        f"• WhatsApp, Telegram, Instagram\n"
        f"• Facebook, Google, Twitter\n"
        f"• E muito mais!\n\n"
        f"🔥 **PREÇOS A PARTIR DE R$ 2,50**\n"
        f"⚡ Recebimento instantâneo\n"
        f"🎯 Suporte 24h"
    )
    
    if update.message:
        await update.message.reply_text(welcome_text, reply_markup=reply_markup, parse_mode='Markdown')
    elif update.callback_query:
        await update.callback_query.edit_message_text(welcome_text, reply_markup=reply_markup, parse_mode='Markdown')

async def menu_servicos(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Menu de serviços disponíveis"""
    query = update.callback_query
    if not query:
        return
    
    await query.answer()
    
    keyboard = [
        [
            InlineKeyboardButton("📱 WhatsApp - R$ 2,50", callback_data="servico_whatsapp"),
            InlineKeyboardButton("📨 Telegram - R$ 3,00", callback_data="servico_telegram")
        ],
        [
            InlineKeyboardButton("📸 Instagram - R$ 4,00", callback_data="servico_instagram"),
            InlineKeyboardButton("👥 Facebook - R$ 3,50", callback_data="servico_facebook")
        ],
        [
            InlineKeyboardButton("🔍 Google - R$ 2,80", callback_data="servico_google"),
            InlineKeyboardButton("🐦 Twitter - R$ 4,50", callback_data="servico_twitter")
        ],
        [
            InlineKeyboardButton("🔙 Voltar", callback_data="menu_principal")
        ]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        "📱 **NÚMEROS SMS DISPONÍVEIS**\n\n"
        "🔥 **MAIS POPULARES:**\n"
        "• WhatsApp - Recebimento garantido\n"
        "• Telegram - Alta taxa de sucesso\n"
        "• Instagram - Verificação rápida\n\n"
        "💡 Escolha o serviço:",
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )

async def menu_recarga(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Menu de recarga"""
    query = update.callback_query
    if not query:
        return
    
    await query.answer()
    
    keyboard = [
        [
            InlineKeyboardButton("💰 R$ 10,00", callback_data="recarga_10"),
            InlineKeyboardButton("💰 R$ 25,00", callback_data="recarga_25")
        ],
        [
            InlineKeyboardButton("💰 R$ 50,00", callback_data="recarga_50"),
            InlineKeyboardButton("💰 R$ 100,00", callback_data="recarga_100")
        ],
        [
            InlineKeyboardButton("🔙 Voltar", callback_data="menu_principal")
        ]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        "💳 **RECARREGAR SALDO**\n\n"
        "🎁 **BÔNUS DE RECARGA:**\n"
        "• R$ 50+ = +15% bônus\n"
        "• R$ 100+ = +20% bônus\n\n"
        "💡 Escolha o valor:",
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )

async def menu_ajuda(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Menu de ajuda"""
    query = update.callback_query
    if not query:
        return
    
    await query.answer()
    
    keyboard = [
        [InlineKeyboardButton("🔙 Voltar", callback_data="menu_principal")]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        "❓ **CENTRAL DE AJUDA**\n\n"
        "🤖 **COMO FUNCIONA:**\n"
        "1. Recarregue seu saldo\n"
        "2. Escolha o serviço desejado\n"
        "3. Receba o número SMS\n"
        "4. Use para verificação\n\n"
        "⏱️ **TEMPO DE RECEBIMENTO:**\n"
        "• WhatsApp: 1-5 minutos\n"
        "• Telegram: 1-3 minutos\n"
        "• Instagram: 2-10 minutos\n\n"
        "💬 **SUPORTE:**\n"
        "Para ajuda, fale com um administrador.",
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Gerenciador principal de callbacks"""
    query = update.callback_query
    if not query or not query.data:
        return
    
    data = query.data
    
    if data == "menu_principal":
        await start(update, context)
    elif data == "menu_servicos":
        await menu_servicos(update, context)
    elif data == "menu_recarga":
        await menu_recarga(update, context)
    elif data == "menu_ajuda":
        await menu_ajuda(update, context)
    elif data.startswith("servico_"):
        await handle_servico(update, context)
    elif data.startswith("recarga_"):
        await handle_recarga(update, context)

async def handle_servico(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Processar seleção de serviço"""
    query = update.callback_query
    if not query:
        return
    
    await query.answer("🔄 Processando compra...")
    
    servico = query.data.split("_")[1]
    precos = {
        "whatsapp": 2.50,
        "telegram": 3.00,
        "instagram": 4.00,
        "facebook": 3.50,
        "google": 2.80,
        "twitter": 4.50
    }
    
    preco = precos.get(servico, 2.50)
    saldo = db.get_saldo(query.from_user.id)
    
    if saldo < preco:
        keyboard = [
            [InlineKeyboardButton("💳 RECARREGAR", callback_data="menu_recarga")],
            [InlineKeyboardButton("🔙 Voltar", callback_data="menu_servicos")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            f"❌ **SALDO INSUFICIENTE**\n\n"
            f"💰 Seu saldo: R$ {saldo:.2f}\n"
            f"💸 Valor necessário: R$ {preco:.2f}\n"
            f"📊 Faltam: R$ {preco - saldo:.2f}\n\n"
            f"🔄 Recarregue para continuar!",
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
    else:
        # Simular compra bem-sucedida
        numero_fake = f"+55119{random.randint(10000000, 99999999)}"
        
        keyboard = [
            [InlineKeyboardButton("🔙 Menu Principal", callback_data="menu_principal")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            f"✅ **NÚMERO SMS ADQUIRIDO**\n\n"
            f"📱 Serviço: {servico.upper()}\n"
            f"📞 Número: `{numero_fake}`\n"
            f"💰 Valor: R$ {preco:.2f}\n\n"
            f"⏱️ **AGUARDANDO SMS...**\n"
            f"O código chegará em até 10 minutos.\n\n"
            f"💡 Use este número para verificação!",
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )

async def handle_recarga(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Processar recarga"""
    query = update.callback_query
    if not query:
        return
    
    await query.answer("💳 Processando pagamento...")
    
    valor = float(query.data.split("_")[1])
    
    keyboard = [
        [InlineKeyboardButton("🔙 Voltar", callback_data="menu_recarga")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        f"💳 **PAGAMENTO EM PROCESSAMENTO**\n\n"
        f"💰 Valor: R$ {valor:.2f}\n"
        f"🔄 Status: Aguardando pagamento\n\n"
        f"💡 **INSTRUÇÕES:**\n"
        f"1. Faça o PIX para a chave\n"
        f"2. Envie o comprovante\n"
        f"3. Aguarde confirmação\n\n"
        f"⚡ Processamento em até 5 minutos!",
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Tratamento global de erros"""
    logger.error(f"Erro capturado: {context.error}")

async def main():
    """Função principal"""
    try:
        # Criar aplicação
        application = Application.builder().token(BOT_TOKEN).build()
        
        # Adicionar handlers
        application.add_handler(CommandHandler("start", start))
        application.add_handler(CallbackQueryHandler(handle_callback))
        application.add_error_handler(error_handler)
        
        # Inicializar e executar
        logger.info("🚀 Iniciando Bot SMS Premium...")
        await application.initialize()
        await application.start()
        
        # Usar polling
        await application.updater.start_polling(
            allowed_updates=["message", "callback_query"],
            drop_pending_updates=True
        )
        
        logger.info("✅ Bot SMS Premium rodando com sucesso!")
        
        # Manter rodando
        while True:
            await asyncio.sleep(1)
            
    except Exception as e:
        logger.error(f"❌ Erro crítico: {e}")
        raise

if __name__ == "__main__":
    asyncio.run(main())