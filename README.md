# Bot de Telegram - Achadinhos

Bot para Telegram que **publica ofertas no canal automaticamente** usando IA (OpenAI) com controle total do admin.

---

## 🗺️ Fases do Projeto

| Fase | Status | Descrição |
|------|--------|-----------|
| **Fase 1** | ✅ Concluída | Publicação manual completa (nome, preço, loja, link, imagem) |
| **Fase 2** | ✅ Concluída | Publicação por link (extração automática + link de afiliado) |
| **Fase 3** | ✅ Concluída | Scheduler automático + aprovação manual pelo admin |
| **Fase 4** | 🔜 Planejada | Autopostagem + WhatsApp + múltiplos destinos |

---

## 🚀 Novidades da Fase 3

- **Monitoramento automático de fontes**: Configure URLs em `data/sources.json` e o bot varrerá periodicamente.
- **Detecção de links de produto**: Heurísticas simples identificam URLs de produto nas páginas monitoradas.
- **Deduplicação**: Links já processados são armazenados em `data/seen_links.json` e nunca são reprocessados.
- **Aprovação manual**: O admin recebe a prévia no Telegram e escolhe **Aprovar** ou **Rejeitar** antes de publicar.
- **Scheduler configurável**: Altere `MONITOR_INTERVAL_MINUTES` no `.env` para ajustar a frequência da varredura.
- **Pronto para autopostagem**: A flag `AUTO_APPROVE=true` no `.env` habilita publicação automática (Fase 4).

---

## 📦 Instalação

```bash
# 1. Clone o repositório
git clone https://github.com/SeuRepo/bot-achadinhos.git
cd bot-achadinhos

# 2. Instale as dependências
pip install -r requirements.txt

# 3. Configure o .env
cp .env.example .env
# Edite .env com suas chaves reais

# 4. Execute
python app.py
```

---

## ⚙️ Configuração do `.env`

```env
TELEGRAM_BOT_TOKEN=seu_token_aqui
TELEGRAM_CHANNEL_ID=-1001234567890
ADMIN_IDS=123456789,987654321

OPENAI_API_KEY=sk-proj-sua-chave
OPENAI_MODEL=gpt-4o-mini
OPENAI_BASE_URL=   # Opcional: base URL customizada

# Fase 3
MONITOR_INTERVAL_MINUTES=60   # Varredura a cada 60 minutos
AUTO_APPROVE=false             # Manter false para aprovação manual
```

---

## 📋 Configuração das Fontes (`data/sources.json`)

Edite o arquivo `data/sources.json` para adicionar as URLs que o bot deve monitorar:

```json
[
  {
    "name": "Shopee Flash Sale",
    "url": "https://shopee.com.br/flash_sale",
    "active": true,
    "notes": "Página de flash sale da Shopee"
  },
  {
    "name": "ML Ofertas",
    "url": "https://www.mercadolivre.com.br/ofertas",
    "active": true,
    "notes": "Página de ofertas do ML"
  },
  {
    "name": "Fonte desativada",
    "url": "https://www.exemplo.com.br/categoria",
    "active": false,
    "notes": "Desativada — não será varrida"
  }
]
```

**Campos:**
- `name`: Nome descritivo da fonte (aparece nas notificações).
- `url`: URL da página a ser varrida.
- `active`: `true` para ativar, `false` para ignorar.
- `notes`: Anotação livre (não afeta o funcionamento).

---

## 🎮 Como Usar

### Menu Manual (`/start`)
- **📢 Publicar Oferta Manual**: Fluxo passo-a-passo guiado pelo bot.
- **🔗 Publicar por Link**: Cole um link e o bot extrai os dados automaticamente.

### Fluxo Automático (Fase 3)
1. O scheduler roda a cada `MONITOR_INTERVAL_MINUTES` minutos.
2. Varre todas as fontes com `"active": true` em `data/sources.json`.
3. Links novos são extraídos, a copy é gerada pela IA.
4. O admin recebe uma prévia no Telegram com dois botões:
   - ✅ **Aprovar e Publicar** → publica no canal.
   - ❌ **Rejeitar** → descarta a oferta (não aparece de novo).

---

## 🗂️ Estrutura do Projeto

```
project/
├── app.py                          # Ponto de entrada
├── requirements.txt
├── .env.example
├── data/
│   ├── sources.json                # FASE 3: Fontes monitoradas
│   └── seen_links.json             # FASE 3: Links já processados
└── bot/
    ├── handlers/
    │   ├── start.py                # Menu principal
    │   ├── cancel.py               # Cancelamento
    │   ├── offer.py                # Publicação manual
    │   ├── offer_by_link.py        # Publicação por link
    │   └── review_queue.py         # FASE 3: Aprovação manual
    ├── services/
    │   ├── ai_writer.py            # Geração de copy (OpenAI)
    │   ├── affiliate_links.py      # Lógica de links
    │   ├── product_extractor.py    # Extração de dados do produto
    │   ├── publisher_telegram.py   # Envio ao canal Telegram
    │   ├── publisher_router.py     # Roteador (preparado p/ WhatsApp)
    │   ├── source_monitor.py       # FASE 3: Varredura de fontes
    │   ├── dedup_store.py          # FASE 3: Controle de duplicatas
    │   └── scheduler_service.py    # FASE 3: Scheduler automático
    ├── permissions.py
    └── utils/
        ├── config.py
        ├── constants.py
        └── formatter.py
```

---

## 🔜 Fase 4 (Próximos Passos)

- `AUTO_APPROVE=true` no `.env` → autopostagem sem intervenção
- `publisher_whatsapp.py` → publicação em grupos WhatsApp
- Filtros de qualidade por fonte (preço mínimo, palavras-chave)
- Múltiplos destinos de destino (canais diferentes por categoria)
