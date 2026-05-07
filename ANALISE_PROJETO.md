# Análise do Projeto: Bot de Achadinhos (V5)

Este documento fornece uma visão geral técnica do projeto, suas funcionalidades atuais e os desafios identificados no desenvolvimento.

## 🤖 O que é o projeto?

O **Bot de Achadinhos** é uma ferramenta de automação focada em **Web Scraping de e-commerce**. Ele foi projetado especificamente para "puxar" informações de grandes varejistas (**Amazon, Shopee, Mercado Livre, Magalu, Netshoes**) para alimentar canais de ofertas de forma automática ou semi-automática.

O objetivo é automatizar a jornada do afiliado: encontrar o produto -> extrair detalhes -> gerar copy -> converter link -> postar.

---

## 🛠️ O que ele faz? (O Coração do Bot)

O sistema é centrado na capacidade de extrair dados de produtos de sites protegidos:

1.  **"Puxada" Automática (Scraping Avançado)**:
    *   Monitora páginas de ofertas da **Amazon (Goldbox)**, **Shopee (Flash Sale)** e **Mercado Livre**.
    *   Utiliza uma arquitetura de camadas: tenta primeiro via APIs internas (Magalu/Netshoes), depois via ScraperAPI/Playwright e, por fim, via parsing HTML bruto.
2.  **Extração de Detalhes**:
    *   Consegue identificar títulos, preços (incluindo diferenciação de preço PIX vs parcelado) e imagens.
    *   Possui lógica específica para lidar com as variações de layout de cada loja.
3.  **IA e Marketing**:
    *   Usa **GPT-4o-mini** para transformar os dados brutos "puxados" em mensagens de venda atraentes.
4.  **Monetização**:
    *   Injeta IDs de afiliado automaticamente em cada link extraído, suportando múltiplas plataformas de uma só vez.
5.  **Revisão Humana**:
    *   O administrador recebe os itens "puxados" e decide o que vai ao ar, garantindo a qualidade do feed.
6.  **Funcionalidades Extras**:
    *   Inclui um módulo de geração de documentos PDF (`pdf_logic.py`), embora este pareça ser um serviço paralelo ou legado integrado ao ambiente do bot.

---

## ⚠️ Problemas e Desafios Identificados

Com base na análise do código e dos logs, foram detectados os seguintes pontos críticos:

### 1. Fragilidade do Web Scraping (O desafio de "Puxar")
*   **Amazon**: A Amazon frequentemente altera suas classes CSS e utiliza Captchas pesados. O arquivo `amazon_debug.html` no projeto indica que o sistema já enfrentou (ou enfrenta) bloqueios onde o HTML retornado não contém os dados do produto, mas sim um desafio de bot.
*   **Shopee**: É a fonte mais instável devido ao uso intenso de JavaScript e URLs dinâmicas que mudam o padrão (ex: `i-` links). O bot depende de expandir links curtos (`shp.ee`) via browser real (Playwright), o que é lento e custoso em termos de processamento.
*   **Proteções Anti-Bot**: O uso de "Bypass Radware" indica que o projeto está em uma luta constante contra sistemas de segurança que tentam impedir a "puxada" automatizada de dados.
*   **Dependência de Proxies**: Sem proxies de qualidade, o bot é rapidamente banido pelas lojas, interrompendo a coleta.

### 2. Dívida Técnica e Redundância
*   Existem arquivos duplicados com propósitos similares, como `product_extractor.py` vs `product_extractor_v2.py` e `affiliate_links.py` vs `affiliate_link_service.py`. Isso sugere que o sistema foi atualizado para tentar resolver falhas na extração, mas as versões antigas não foram limpas.

### 3. Coordenadas Rígidas no PDF
*   O preenchimento de PDFs (`pdf_logic.py`) é feito via coordenadas de pixel (eixo X/Y) fixas. Qualquer alteração mínima no template oficial do contrato fará com que os dados saiam fora do lugar ou sobreponham textos.

## 🚀 Fluxo de "Puxada" (Extração por Link)

O coração do projeto para "puxar coisas" da Amazon/Shopee segue este fluxo:
1.  **Entrada**: O admin envia um link (curto ou longo).
2.  **Resolução**: Se for link curto (`amzn.to`, `shope.ee`), o bot usa o **Playwright** (um navegador real) para expandir a URL e ver o destino final.
3.  **Extração Híbrida**: O bot tenta primeiro via seletores HTML rápidos. Se falhar (bloqueio), usa o **ScraperAPI** com bypass de Radware/Cloudflare.
4.  **IA de Refinamento**: Se o nome do produto vier sujo (ex: "Amazon.com.br: Ofertas..."), o sistema usa IA para limpar o título e gerar uma legenda de venda atraente.
5.  **Conversão**: O link é automaticamente convertido para o ID de afiliado do dono do bot.

## ⚠️ Principais Gargalos Atuais

1.  **Velocidade**: A dependência de Playwright para resolver links da Shopee torna o processo lento (pode levar até 60-90 segundos).
2.  **Custo**: O uso de ScraperAPI e proxies para "puxar" os dados sem ser bloqueado gera um custo por requisição.
3.  **Manutenção de Seletores**: Sempre que a Amazon ou Shopee mudam o layout do site, o bot para de "puxar" os preços corretamente até que o código seja atualizado.

### 4. Conflitos de Instância
*   O arquivo `app.py` contém um "sleep" forçado de 10 segundos para evitar erros de conflito (instância duplicada) no Railway/Heroku. Isso indica uma dificuldade no gerenciamento do ciclo de vida da aplicação durante novos deploys.

### 5. Configurações Hardcoded
*   Ainda existem valores fixos no código (ex: "Belo Horizonte" como local padrão de assinatura), o que limita a flexibilidade para usuários de outras regiões sem alterar o código-fonte.

### 6. Instabilidade de Estado
*   O uso de `ConversationHandler` do Telegram é sensível. Notas no código indicam correções recentes para evitar perda de estado do usuário, mas fluxos complexos ainda podem ser interrompidos por reinicializações do servidor.

---

## 📅 Próximos Passos Sugeridos
*   **Consolidação de Módulos**: Unificar os extratores de produtos e serviços de links para reduzir a complexidade.
*   **Melhoria no PDF**: Implementar detecção de campos de formulário PDF (AcroForms) em vez de coordenadas fixas, se possível.
*   **Dashboard de Monitoramento**: Uma interface web simples para visualizar o status das fontes de scraping e a saúde dos proxies.
