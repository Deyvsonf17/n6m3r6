# Bot de Vendas SMS Premium - Otimizado para Alta Demanda

## Overview

Este é um bot de vendas SMS premium para Telegram desenvolvido em Python, especializado na venda de números de telefone para recebimento de códigos SMS de diversas plataformas. O sistema foi **completamente otimizado para suportar 500+ usuários simultâneos** com implementações críticas de rate limiting, cache, requests assíncronos e pool de conexões otimizado.

## User Preferences

Preferred communication style: Simple, everyday language.

## System Architecture

### Backend Architecture
- **Tecnologia Principal**: Python 3.11 com python-telegram-bot
- **Arquitetura**: Bot assíncrono com alta concorrência
- **Banco de Dados**: SQLite3 otimizado com WAL mode
- **APIs Externas**: CryptoPay (pagamentos), 5Sim (números SMS), CoinGecko (cotações)
- **Cache**: Sistema global com expiração automática (5 minutos)

### Otimizações Críticas Implementadas (2025-07-19)
- **Rate Limiting**: 30 requests/minuto por usuário, 0.5s entre comandos (otimizado)
- **Requests Assíncronos**: aiohttp para chamadas não-bloqueantes
- **Pool de Conexões**: SQLite otimizado para alta concorrência
- **Cache de Preços**: Cotações crypto com cache inteligente
- **Tratamento de Erros**: Fallbacks robustos e logs detalhados
- **Sistema de Bônus**: Função centralizada calcular_bonus() para consistência
- **Responsividade Melhorada**: Rate limiting mais flexível, respostas mais rápidas

### CORREÇÃO CRÍTICA: Sistema de Bônus Separado (2025-07-19)
- **Nova Coluna**: `saldo_bonus` adicionada ao banco para separar bônus do saldo base
- **Processamento Correto**: Depósitos agora separam valor pago (saldo base) do bônus ganho
- **Dedução Inteligente**: Sistema prioriza uso do bônus antes do saldo base nas compras
- **Exibição Clara**: Usuários veem saldo base e bônus separadamente no painel
- **Migração Automática**: Usuários existentes migrados automaticamente para nova estrutura

### COMANDOS ADMIN CORRIGIDOS (2025-07-19)
- **`/dar_saldo`**: Corrigido para aplicar bônus automático baseado no valor (R$100 = +R$20 bônus)
- **`/dar_bonus`**: Novo comando para adicionar apenas bônus (sem saldo base)
- **`/confirmar`**: Mantido funcionamento correto com bônus e indicações
- **Números Grátis**: Todos comandos agora concedem números grátis corretos por faixa de valor

### Estrutura de Arquivos
- **main.py**: Bot principal otimizado para 500+ usuários simultâneos
- **premium_bot.db**: Banco SQLite com configurações de alta performance
- **daily_stats.json**: Estatísticas em tempo real
- **referral_codes.json**: Sistema de indicações

## Key Components

### 1. Sistema de Design
- **Variáveis CSS**: Definidas em `:root` para cores, sombras, bordas e transições
- **Paleta de Cores**: 
  - Cores primárias: #667eea (azul) e #764ba2 (roxo)
  - Cores de texto: #333 (escuro) e #666 (claro)
  - Background: #f8fafc (cinza claro)
- **Tipografia**: Sistema de fontes nativo (system fonts) para melhor performance

### 2. Layout e Estrutura
- **Container Principal**: `.welcome-container` com design card centralizado
- **Sistema de Layout**: Flexbox para centralização vertical e horizontal
- **Responsividade**: Design adaptável com padding responsivo

### 3. Estilização Visual
- **Gradiente de Fundo**: Linear gradient diagonal usando as cores primárias
- **Sombras**: Box-shadow suave para profundidade visual
- **Border Radius**: 12px para cantos arredondados modernos
- **Transições**: Animações suaves de 0.3s para interações

## Data Flow

Como se trata de uma página estática, não há fluxo de dados dinâmico. O conteúdo é renderizado diretamente no HTML sem necessidade de processamento server-side ou client-side.

## External Dependencies

### Dependências Mínimas
- **Nenhuma biblioteca JavaScript**: O projeto não utiliza frameworks ou bibliotecas externas
- **Fontes do Sistema**: Utiliza fontes nativas do sistema operacional
- **CSS Puro**: Sem frameworks CSS externos como Bootstrap ou Tailwind

### Vantagens da Abordagem
- **Performance**: Carregamento rápido sem dependências externas
- **Manutenibilidade**: Código simples e direto
- **Compatibilidade**: Funciona em qualquer navegador moderno

## Deployment Strategy

### Estratégia de Deploy
- **Hospedagem Estática**: Pode ser hospedado em qualquer servidor web ou CDN
- **Configuração Mínima**: Apenas servir o arquivo HTML estático
- **Opções de Deploy**:
  - GitHub Pages
  - Netlify
  - Vercel
  - Qualquer servidor web (Apache, Nginx)

### Requisitos de Infraestrutura
- **Servidor Web**: Qualquer servidor capaz de servir arquivos estáticos
- **HTTPS**: Recomendado para melhor SEO e segurança
- **Compressão**: Gzip pode ser configurado para otimização

## Architectural Decisions

### 1. CSS Incorporado vs. Arquivo Separado
- **Decisão**: CSS incorporado no HTML
- **Rationale**: Para um projeto pequeno, reduz requisições HTTP
- **Trade-off**: Sacrifica reutilização em favor da simplicidade

### 2. Sem Framework CSS
- **Decisão**: CSS customizado puro
- **Rationale**: Controle total sobre o design e performance otimizada
- **Benefício**: Sem bloat de código desnecessário

### 3. Design System com Variáveis CSS
- **Decisão**: Uso de CSS Custom Properties
- **Rationale**: Facilita manutenção e consistência visual
- **Vantagem**: Fácil modificação de temas e cores

### 4. Tipografia de Sistema
- **Decisão**: Fontes nativas do sistema
- **Rationale**: Performance e consistência com o OS do usuário
- **Benefício**: Carregamento instantâneo sem web fonts