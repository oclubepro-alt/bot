# -*- coding: utf-8 -*-
"""
pdf_service.py — Serviço DEFINITIVO de geração de PDF para contratos Rede Total
═══════════════════════════════════════════════════════════════════════════════
Usa PyMuPDF (fitz) — NÃO usa pypdf/reportlab.

ESTRATÉGIA "cobrir → escrever":
  1. Para cada campo dinâmico: desenha retângulo BRANCO sobre a área do template.
  2. Só então escreve o valor — se e somente se não for vazio.
  Isso elimina definitivamente:
    • Parênteses "( )" de telefone vazio
    • Linhas "___/_____/___" de data/assinatura do template
    • Qualquer placeholder do PDF original

SISTEMA DE COORDENADAS:
  PyMuPDF usa origem no canto SUPERIOR ESQUERDO.
  x aumenta →, y aumenta ↓.
  (Diferente de ReportLab que usa origem no canto INFERIOR ESQUERDO.)

INSTALAÇÃO:
  pip install pymupdf

USO DIRETO:
  from pdf_service import gerar_pdf
  gerar_pdf(dados_dict, "Padrao em Branco.pdf", "saida.pdf")
"""

import os
import fitz  # PyMuPDF — pip install pymupdf
from datetime import date as _date


# ═══════════════════════════════════════════════════════════════════════
# CONSTANTES GLOBAIS
# ═══════════════════════════════════════════════════════════════════════

WHITE = (1, 1, 1)
BLACK = (0, 0, 0)
HELV = "helv"   # Helvetica normal (embutida no PyMuPDF)
HEBO = "hebo"   # Helvetica Bold

# ──────────────────────────────────────────────────────────────────────
# SEÇÃO MÉDICA – coordenadas calibradas com base em pdf_output_utf8.txt
# ──────────────────────────────────────────────────────────────────────

# Colunas X para escrever S/N (Titular + Dep 1..5)
# Extraídas do texto "TIT." x=339, "DEP. 1" x=375 etc. na página 21
SN_X = [344, 380, 415, 451, 486, 521]

# Y (baseline) de cada linha de pergunta na Página 21 (Q1-Q13, índices 0-12)
# Calibragem fina para sit on (sentar sobre a linha)
SN_Y_P21 = [
    186,  # Q1  Diabetes
    217,  # Q2  Endocrinológicas
    250,  # Q3  Cardíacas
    318,  # Q4  Obesidade
    339,  # Q5  Quimio/Radio
    365,  # Q6  Olhos
    424,  # Q7  Sangue
    479,  # Q8  Pele
    522,  # Q9  Circulatório
    587,  # Q10 Ouvidos/Garganta
    653,  # Q11 Respiratório
    692,  # Q12 Digestivo
    734,  # Q13 Sistema Nervoso
]

# Y (baseline) de cada linha de pergunta na Página 22 (Q14-Q33, índices 13-32)
# Calibragem Erro 3: Array Y com coordenadas reais search_for
SN_Y_P22 = [
    64,   # Q14 Hérnia
    94,   # Q15 Congênitas
    138,  # Q16 Ortopédica
    183,  # Q17 Auto-imune
    228,  # Q18 Coluna
    257,  # Q19 Sequela
    301,  # Q20 Ginecológicas
    345,  # Q21 Urológicas/Renais
    391,  # Q22 (Transplante/Doença Grave)
    435,  # Q23 (Miopatias/Esclerose)
    479,  # Q24 (Outras)
    506,  # Q25 (Uso medicamento)
    534,  # Q26 (Tratamento)
    562,  # Q27 (Internado)
    590,  # Q28 (Cirurgia)
    619,  # Q29 (Exames)
    647,  # Q30 (Déficit motor)
    675,  # Q31 (Quadro agudo)
    703,  # Q32 (Peso alterado)
    731,  # Q33 (Doença não citada)
]

# Colunas X para nome/idade/peso/altura no cabeçalho da pág. 21
# "TITULAR" x=121, "DEPENDENTE 1" x=195, ...
IDENT_X = [121, 195, 263, 334, 405, 476]

# Faixa etária → valor mensal do plano (tabela padrão)
_FAIXAS = [
    (0,  18,  344.18),
    (19, 23,  367.66),
    (24, 28,  400.22),
    (29, 33,  470.11),
    (34, 38,  565.77),
    (39, 43,  639.61),
    (44, 48,  780.52),
    (49, 53,  957.92),
    (54, 58, 1287.64),
    (59, 999, 1709.59),
]


# ═══════════════════════════════════════════════════════════════════════
# HELPERS DE FORMATAÇÃO
# ═══════════════════════════════════════════════════════════════════════

def formatar_telefone(v) -> str:
    """
    Formata telefone com DDD.
    GARANTIA: retorna '' quando vazio/inválido — NUNCA '( )' ou parênteses soltos.
    """
    if not v:
        return ""
    digitos = "".join(c for c in str(v) if c.isdigit())
    if len(digitos) == 11:
        return f"({digitos[:2]}) {digitos[2:7]}-{digitos[7:]}"
    if len(digitos) == 10:
        return f"({digitos[:2]}) {digitos[2:6]}-{digitos[6:]}"
    return ""   # dígitos insuficientes → nada visível


def normalizar(v, default: str = "") -> str:
    """Retorna string stripped, ou default se None/vazio."""
    if v is None:
        return default
    s = str(v).strip()
    return s if s else default


def formatar_cpf(v) -> str:
    """Formata CPF: 12345678900 -> 123.456.789-00."""
    if not v:
        return ""
    digitos = "".join(c for c in str(v) if c.isdigit())
    if len(digitos) == 11:
        return f"{digitos[:3]}.{digitos[3:6]}.{digitos[6:9]}-{digitos[9:]}"
    return normalizar(v)


def fmt_brl(v) -> str:
    """Formata número como moeda BR: 1234.56 → '1.234,56'."""
    try:
        n = float(str(v).replace(".", "").replace(",", "."))
        return f"{n:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except Exception:
        return normalizar(v)


def resposta_sn(v) -> str:
    """Converte qualquer representação de sim/não para 'S' ou 'N'."""
    return "S" if v in (True, "S", "s", "sim", "Sim", "SIM", 1, "1", "true", "True") else "N"


def data_hoje() -> str:
    return _date.today().strftime("%d/%m/%Y")


def _valor_faixa(idade_str) -> float:
    try:
        idade = int(str(idade_str).strip())
    except Exception:
        return 0.0
    for mn, mx, v in _FAIXAS:
        if mn <= idade <= mx:
            return v
    return 0.0


# ═══════════════════════════════════════════════════════════════════════
# OPERAÇÕES PRIMITIVAS DE PÁGINA
# ═══════════════════════════════════════════════════════════════════════

def cobrir(page: fitz.Page, x0: float, y0: float, x1: float, y1: float):
    """
    Remove FISICAMENTE qualquer conteúdo do template na área indicada.
    Usa anotações de redação para garantir que o texto original suma do arquivo.
    """
    rect = fitz.Rect(x0, y0, x1, y1)
    page.add_redact_annot(rect, fill=WHITE)
    page.apply_redactions()


def tx(page: fitz.Page, x: float, y: float, texto: str,
       size: float = 9, bold: bool = False):
    """
    Insere texto em (x, y) — coordenada y é a BASELINE do texto.
    Ignora chamada se texto for vazio: NUNCA escreve string vazia.
    """
    if not texto:
        return
    page.insert_text(
        (x, y),
        texto,
        fontname=HEBO if bold else HELV,
        fontsize=size,
        color=BLACK,
    )


def campo(page: fitz.Page,
          x0: float, y0: float, x1: float, y1: float,
          valor: str,
          size: float = 9,
          bold: bool = False,
          offset_x: float = 2,
          offset_y: float = 2):
    """
    Operação combinada: cobre a área (x0,y0)→(x1,y1) com branco
    e escreve valor com margem interna.
    offset_x = recuo horizontal dentro da caixa
    offset_y = recuo acima do fundo da caixa (baseline)
    """
    cobrir(page, x0, y0, x1, y1)
    if valor:
        tx(page, x0 + offset_x, y1 - offset_y, valor, size, bold)


# ═══════════════════════════════════════════════════════════════════════
# FUNÇÕES POR PÁGINA
# ═══════════════════════════════════════════════════════════════════════

def _pagina1(page: fitz.Page, d: dict):
    """
    Página 1 — Dados do Titular.
    Campos: nome, telefone residencial, celular, email, nome_mae,
            data_nascimento, sexo, estado_civil, rg, cpf, endereço.
    """
    # ── Checkbox "Plano Novo" e Limpeza de Cabeçalho ──────────────
    # Limpa possíveis restos de versão/data no topo e áreas de ( )
    # x0=45, y0=180, x1=540, y1=205 cobre as opções de Plano Novo/Dependentes
    cobrir(page, 45, 180, 540, 205)
    
    # Marca o checkbox "Plano Novo" conforme dados
    # Calibrado para cair dentro do ( ) original que estava em x=48..65
    tx(page, 59, 187, "X", size=11, bold=True)

    # ── Nome completo ─────────────────────────────────────────────
    # ERRO 1: Nome flutuando -> Ajuste para cair na linha do template
    campo(page, 50, 374, 530, 396, normalizar(d.get("titular_nome")), offset_y=3)

    # ── Telefones ─────────────────────────────────────────────────
    # ERRO 2: Telefone no campo errado e sem formatação
    tel_res = formatar_telefone(
        d.get("titular_telefone_residencial") or d.get("titular_telefone") or d.get("titular_telefone_contato")
    )
    tel_cel = formatar_telefone(
        d.get("titular_celular") or
        d.get("titular_telefone_adicional") or
        d.get("titular_telefone_celular")
    )

    # Cobre os blocos do template usando redação física
    campo(page, 45, 405, 220, 428, tel_res)
    campo(page, 220, 405, 425, 428, tel_cel)

    # ── E-mail ────────────────────────────────────────────────────
    campo(page, 50, 441, 530, 459, normalizar(d.get("titular_email")))

    # ── Nome da mãe ───────────────────────────────────────────────
    campo(page, 50, 466, 530, 484, normalizar(d.get("titular_nome_mae")))

    # ── Nasc / Sexo / Estado civil ────────────────────────────────
    campo(page, 50, 496, 196, 514, normalizar(d.get("titular_data_nascimento")))
    campo(page, 196, 496, 275, 514, normalizar(d.get("titular_sexo")))
    campo(page, 275, 496, 540, 514, normalizar(d.get("titular_estado_civil")))

    # ── RG / CPF ──────────────────────────────────────────────────
    campo(page, 50, 522, 275, 540, normalizar(d.get("titular_rg")))
    # ERRO 3: CPF truncado -> formatar explicitamente para não faltar dígitos
    campo(page, 275, 522, 540, 540, formatar_cpf(d.get("titular_cpf")))

    # ── Endereço ──────────────────────────────────────────────────
    # ERRO 4: "r" solto antes do endereço -> cobrir desde x=40
    rua = normalizar(d.get("endereco_rua"))
    num = normalizar(d.get("endereco_numero"))
    rua_completa = f"{rua}, {num}" if rua and num else rua or num
    campo(page, 40, 548, 530, 566, rua_completa)

    # Complemento / Bairro / Cidade / UF
    campo(page, 50, 583, 278, 601, normalizar(d.get("endereco_complemento")))
    campo(page, 278, 583, 430, 601, normalizar(d.get("endereco_bairro")))
    campo(page, 430, 583, 510, 601, normalizar(d.get("endereco_cidade")))
    campo(page, 510, 583, 540, 601, normalizar(d.get("endereco_uf")))


def preencher_pagina_dependentes(page, dependentes: list):
    """
    page: objeto fitz.Page da página 2
    dependentes: lista de dicts com keys:
        nome, data_nascimento, sexo, estado_civil,
        parentesco, cpf, nome_mae
    Máximo 5 dependentes.
    """
    
    # Coordenadas X extraídas do diagnóstico (x0 dos labels)
    COLUNAS_X = {
        "data_nascimento": 47.76,
        "sexo":            189.17,
        "estado_civil":    246.77,
        "parentesco":      331.63,
        "cpf":             459.94,
    }

    LABELS_NOME = [
        "1 - Nome Completo",
        "2 - Nome Completo",
        "3 - Nome Completo",
        "4 - Nome Completo",
        "5 - Nome Completo"
    ]

    for i, label_text in enumerate(LABELS_NOME):
        # Regra 5: Se o dependente não existir nos dados, não escreve nada
        if i >= len(dependentes):
            break
            
        dep = dependentes[i]
        if not dep or not dep.get("nome"):
            continue

        # 1. Localizar o label do nome para este bloco
        res_nomes = page.search_for(label_text)
        if not res_nomes:
            continue
        r_nome = res_nomes[0]
        
        # POSICIONAMENTO DO NOME: 10pt abaixo do label para cair na célula
        y_nome = r_nome.y1 + 10
        tx(page, r_nome.x0 + 5, y_nome, normalizar(dep.get("nome")), size=8)

        # 2. Localizar o label de "Data de nascimento" deste bloco (i-ésimo na página)
        res_data_labels = page.search_for("Data de nascimento")
        if len(res_data_labels) > i:
            r_data = res_data_labels[i]
            y_dados = r_data.y1 + 10
            
            tx(page, COLUNAS_X["data_nascimento"], y_dados, normalizar(dep.get("data_nascimento")), size=8)
            tx(page, COLUNAS_X["sexo"],            y_dados, normalizar(dep.get("sexo")),            size=8)
            tx(page, COLUNAS_X["estado_civil"],    y_dados, normalizar(dep.get("estado_civil")),    size=8)
            tx(page, COLUNAS_X["parentesco"],      y_dados, normalizar(dep.get("parentesco")),      size=8)
            tx(page, COLUNAS_X["cpf"],             y_dados, formatar_cpf(dep.get("cpf")),           size=8)

        # 3. Localizar o label de "Nome da mãe" deste bloco (i-ésimo na página)
        labels_mae = page.search_for("Nome da m" + chr(227) + "e completo")
        if not labels_mae:
            labels_mae = page.search_for("Nome da mae completo")
            
        if len(labels_mae) > i:
            r_mae = labels_mae[i]
            y_mae = r_mae.y1 + 12
            tx(page, r_mae.x0 + 5, y_mae, normalizar(dep.get("nome_mae")), size=8)


def _pagina2(page: fitz.Page, d: dict):
    """Página 2 — Dependentes (até 5)."""
    preencher_pagina_dependentes(page, d.get("dependentes", []))


def _pagina3(page: fitz.Page, d: dict):
    """
    Página 3 — Representante financeiro e Forma de Pagamento.
    Estratégia: Localizar label -> Limpar área (Redação) -> Escrever valor calibrado.
    """

    def escrever(x, y, valor, bold=False, fontsize=8):
        if not valor or str(valor).strip() == "":
            return
        fonte = HEBO if bold else HELV
        page.insert_text(
            (x, y),
            str(valor).strip(),
            fontname=fonte,
            fontsize=fontsize,
            color=BLACK,
        )

    def limpar_e_escrever(label_name, valor, index=1, off_x=5, off_y=12, bold=False, w=400):
        res = page.search_for(label_name)
        if len(res) > index:
            r = res[index]
            # Define área de limpeza (generosa para apagar placeholders)
            area = fitz.Rect(r.x1 + 1, r.y0 - 2, min(r.x1 + w, 560), r.y1 + 10)
            page.add_redact_annot(area, fill=WHITE)
            if valor:
                # Armazenar para escrever após apply_redactions
                return (r.x1 + off_x, r.y0 + off_y, str(valor), bold)
        return None

    comandos_escrita = []

    # 1. Marcador "Titular é Financeiro"
    if d.get("titular_e_financeiro"):
        res_sim = page.search_for("Sim")
        if res_sim:
            r = res_sim[0]
            # O box está à esquerda do "Sim". x0-12 é o centro do box.
            # No screenshot, y0+10 parece ideal para o centro do box.
            area = fitz.Rect(r.x0 - 15, r.y0 - 2, r.x0 - 2, r.y1 + 2)
            page.add_redact_annot(area, fill=WHITE)
            comandos_escrita.append((r.x0 - 12.5, r.y0 + 9.5, "X", True))

    # 2. Campos de Texto (Rep Financeiro)
    # Nota: index=1 para pegar a ocorrência da seção Rep Financeiro
    
    # Nome
    res = limpar_e_escrever("Nome Completo", d.get("rep_financeiro_nome", ""), index=1, off_y=5.0)
    if res: comandos_escrita.append(res)
    
    # Email (Label 'Mail')
    res = limpar_e_escrever("Mail", d.get("rep_financeiro_email", ""), index=1, off_y=5.0)
    if res: comandos_escrita.append(res)

    # CPF / RG / Data Nasc
    res = limpar_e_escrever("CPF", formatar_cpf(d.get("rep_financeiro_cpf", "")), index=1, off_y=5.0, w=130)
    if res: comandos_escrita.append(res)
    
    res = limpar_e_escrever("RG", d.get("rep_financeiro_rg", ""), index=1, off_y=5.0, w=130)
    if res: comandos_escrita.append(res)
    
    res = limpar_e_escrever("Data de nascimento", d.get("rep_financeiro_data_nascimento", ""), index=1, off_y=5.0, w=130)
    if res: comandos_escrita.append(res)

    # Sexo / Estado Civil / Parentesco / Telefone
    res = limpar_e_escrever("Sexo", d.get("rep_financeiro_sexo", ""), index=1, off_y=5.0, w=60)
    if res: comandos_escrita.append(res)
    
    res = limpar_e_escrever("Estado Civil", d.get("rep_financeiro_estado_civil", ""), index=1, off_y=5.0, w=100)
    if res: comandos_escrita.append(res)
    
    res = limpar_e_escrever("Grau de Parentesco", d.get("rep_financeiro_grau_parentesco", ""), index=1, off_y=5.0, w=100)
    if res: comandos_escrita.append(res)
    
    # Telefone (precisa limpar o ( ) que fica abaixo)
    res_tel = page.search_for("Telefone Celular")
    if len(res_tel) > 1:
        r = res_tel[1]
        # Limpa área maior para pegar o ( ) abaixo
        area_tel = fitz.Rect(r.x0, r.y1 - 2, r.x1 + 150, r.y1 + 15)
        page.add_redact_annot(area_tel, fill=WHITE)
        # Limpa à direita
        area_dir = fitz.Rect(r.x1 + 1, r.y0 - 2, 560, r.y1 + 5)
        page.add_redact_annot(area_dir, fill=WHITE)
        tel_f = formatar_telefone(d.get("rep_financeiro_telefone", ""))
        if tel_f:
            comandos_escrita.append((r.x1 + 5, r.y0 + 13, tel_f, False))

    # 3. Forma de Pagamento e Datas (Caixas à direita)
    # Calibração radical - o texto está saindo muito baixo.
    # Usando y0 + 4.0 para forçar o texto para cima (dentro da caixa).
    X_DATA = 190

    if "boleto" in str(d.get("forma_pagamento", "")).lower():
        res_bol = page.search_for("Boleto bancário")
        if res_bol:
            r = res_bol[0]
            # Mover para x=108 e subir o Y
            comandos_escrita.append((108, r.y0 + 4.0, "X", True))

    # Data Início
    res_ini = page.search_for("Data De Início")
    if res_ini:
        r = res_ini[0]
        area = fitz.Rect(165, r.y0 - 5, 500, r.y1 + 10)
        page.add_redact_annot(area, fill=WHITE)
        val = d.get("data_inicio_beneficio", "")
        if val: comandos_escrita.append((X_DATA, r.y0 + 4.0, val, False))

    # Data Vencimento
    res_venc = page.search_for("Data de vencimento")
    if res_venc:
        r = res_venc[0]
        area = fitz.Rect(165, r.y0 - 5, 500, r.y1 + 10)
        page.add_redact_annot(area, fill=WHITE)
        val = d.get("data_vencimento_boleto", "")
        if val: comandos_escrita.append((X_DATA, r.y0 + 4.0, val, False))

    # Aplicar todas as limpezas de uma vez
    page.apply_redactions()

    # Escrever os valores
    for x, y, texto, bold in comandos_escrita:
        escrever(x, y, texto, bold=bold)


def _bloco_assinatura(page: fitz.Page, d: dict,
                      cover: tuple,
                      local_xy: tuple,
                      nome_xy: tuple,
                      cpf_xy: tuple):
    """
    Helper genérico para qualquer bloco de assinatura.
    cover      = (x0,y0,x1,y1) — área do template a cobrir (linha de traços)
    local_xy   = (x, y) — onde escrever "Cidade, dd/mm/aaaa"
    nome_xy    = (x, y) — onde escrever "(ASSINADO ELETRONIcamente)" + nome
    cpf_xy     = (x, y) — onde escrever "CPF: ..."
    """
    hoje  = normalizar(d.get("data_assinatura"), data_hoje())
    # ERRO 6: "Belo Horizonte" hardcoded -> Usar cidade do endereço ou cadastro
    local = normalizar(d.get("endereco_cidade") or d.get("local_assinatura"), "Belo Horizonte")
    nome  = normalizar(d.get("titular_nome"))
    cpf   = normalizar(d.get("titular_cpf"))

    # Cobre linha do template (traços, barras de data, espaços)
    # Aumentamos a margem de cobertura para garantir limpeza total
    cobrir(page, cover[0] - 2, cover[1] - 2, cover[2] + 2, cover[3] + 2)

    # Escreve local e data
    tx(page, local_xy[0], local_xy[1], f"{local}, {hoje}", size=8)

    # Bloco de assinatura eletrônica
    nx, ny = nome_xy
    # Cobre também a área abaixo onde o nome será escrito se houver lixo
    cobrir(page, nx - 5, ny - 30, nx + 250, ny + 30)

    # Se houver imagem de assinatura (Base64)
    sig = d.get("signature")
    if sig and sig.get("image"):
        try:
            import base64
            img_data = sig.get("image")
            if "," in img_data:
                img_data = img_data.split(",")[1]
            img_bytes = base64.b64decode(img_data)
            
            # Rect onde a imagem será desenhada (acima do texto)
            # x_img, y_img, w_img, h_img calibrados para o centro do bloco
            sig_rect = fitz.Rect(nx, ny - 35, nx + 120, ny - 5)
            page.insert_image(sig_rect, stream=img_bytes)
        except Exception as e:
            print(f"Erro ao inserir imagem de assinatura: {e}")
    
    tx(page, nx,      ny,      "(ASSINADO ELETRONICAMENTE)", size=7, bold=True)
    tx(page, nx,      ny + 12, nome,                         size=7, bold=True)
    tx(page, cpf_xy[0], cpf_xy[1], f"CPF: {cpf}",           size=7)


def _pagina4(page: fitz.Page, d: dict):
    """Página 4 — 1ª Assinatura (Autorização do Contrato)."""
    _bloco_assinatura(
        page, d,
        cover=(40, 632, 530, 660),
        local_xy=(45, 648),
        nome_xy=(245, 618),
        cpf_xy=(245, 656),
    )


def _pagina6(page: fitz.Page, d: dict):
    """Página 6 — Composição mensal de valores por faixa etária."""
    deps = d.get("dependentes", [])
    dep_xs = [129, 216, 304, 391, 478]

    # Titular
    val_tit = _valor_faixa(d.get("titular_idade", 0))
    campo(page, 28, 117, 130, 138, fmt_brl(val_tit))

    total = val_tit
    for i, dep in enumerate(deps[:5]):
        v = _valor_faixa(dep.get("idade", 0))
        total += v
        x = dep_xs[i]
        campo(page, x - 8, 117, x + 72, 138, fmt_brl(v))

    # Total geral
    campo(page, 200, 174, 380, 196, fmt_brl(total), bold=True)


def _pagina7(page: fitz.Page, d: dict):
    """Página 7 — Anexo de Carências (lista de beneficiários)."""
    deps  = d.get("dependentes", [])
    plano = normalizar(d.get("plano_tipo"), "Rede Total Saúde")

    # Linha do titular
    cobrir(page, 80, 558, 535, 578)
    tx(page, 85, 572, normalizar(d.get("titular_nome")), size=8)
    tx(page, 370, 572, plano, size=8)

    # Linhas dos dependentes
    dep_ys = [590, 615, 639, 663, 685]
    for i, dep in enumerate(deps[:5]):
        y = dep_ys[i]
        cobrir(page, 80, y - 4, 535, y + 14)
        tx(page, 85,  y + 8, normalizar(dep.get("nome")), size=8)
        tx(page, 370, y + 8, plano, size=8)

    # Plano mencionado na parte inferior da página
    cobrir(page, 40, 702, 380, 720)
    tx(page, 47, 715, plano, size=8)


def _pagina8(page: fitz.Page, d: dict):
    """Página 8 — 2ª Assinatura (Carências)."""
    _bloco_assinatura(
        page, d,
        cover=(25, 462, 530, 490),
        local_xy=(30, 478),
        nome_xy=(263, 445),
        cpf_xy=(263, 492),
    )


def _pagina17(page: fitz.Page, d: dict):
    """Página 17 — Assinatura Principal / Disposições Gerais."""
    _bloco_assinatura(
        page, d,
        cover=(168, 600, 530, 628),
        local_xy=(265, 616),
        nome_xy=(181, 548),
        cpf_xy=(181, 576),
    )


def _pagina19(page: fitz.Page, d: dict):
    """Página 19 — Carta de Orientação / Assinatura do Beneficiário."""
    # Cobertura ampla para as linhas de data e local detected em find_lines
    _bloco_assinatura(
        page, d,
        cover=(25, 518, 530, 535),
        local_xy=(28, 527),
        nome_xy=(28, 590),
        cpf_xy=(65, 604),
    )
    # Limpeza adicional para os campos de assinatura na pág 19
    cobrir(page, 25, 550, 530, 610)
    tx(page, 50, 575, "(ASSINADO ELETRONICAMENTE)", size=7, bold=True)
    tx(page, 50, 587, normalizar(d.get("titular_nome")), size=7, bold=True)
    tx(page, 50, 600, f"CPF: {normalizar(d.get('titular_cpf'))}", size=7)


def _pagina21(page: fitz.Page, d: dict):
    """
    Página 21 — Declaração de Saúde:
      • Cabeçalho: nome / idade / peso / altura (titular + dependentes)
      • Q1-Q13: resposta S/N para cada pessoa
    """
    deps = d.get("dependentes", [])

    # ── Cabeçalho de identificação ────────────────────────────────
    # ERRO 2: Cabeçalho DEP N sobrepondo 1 -> Descer dados 15pts (topo~69, inicia em 94)
    cobrir(page, 115, 78, 555, 150)

    # Titular
    tx(page, IDENT_X[0], 94,  normalizar(d.get("titular_nome"),   ""), size=7)
    tx(page, IDENT_X[0], 110, normalizar(d.get("titular_idade"),  ""), size=7)
    tx(page, IDENT_X[0], 126, normalizar(d.get("titular_peso"),   ""), size=7)
    tx(page, IDENT_X[0], 142, normalizar(d.get("titular_altura"), ""), size=7)

    # Dependentes
    for i, dep in enumerate(deps[:5]):
        cx = IDENT_X[i + 1]
        tx(page, cx, 94,  normalizar(dep.get("nome",    "")), size=7)
        tx(page, cx, 110, normalizar(dep.get("idade",   "")), size=7)
        tx(page, cx, 126, normalizar(dep.get("peso",    "")), size=7)
        tx(page, cx, 142, normalizar(dep.get("altura",  "")), size=7)

    # ── Respostas S/N (Q1-Q13) ───────────────────────────────────
    _preencher_sn(page, d, SN_Y_P21, q_start=0)


def _pagina22(page: fitz.Page, d: dict):
    """Página 22 — Declaração de Saúde: Q14-Q33, resposta S/N."""
    _preencher_sn(page, d, SN_Y_P22, q_start=13)


def _pagina23(page: fitz.Page, d: dict):
    """
    Página 23 — Especificações de doenças / Médico orientador.
    """
    medico = d.get("medico_orientador", False)
    # ERRO 4: X fora da célula de opção médica -> Mover para a direita (coluna marking)
    if medico is False or medico == "dispensado":
        cobrir(page, 480, 492, 560, 510)
        tx(page, 518, 504, "X", size=9, bold=True)   # dispensou
    else:
        cobrir(page, 480, 515, 560, 533)
        tx(page, 518, 527, "X", size=9, bold=True)   # com médico

    # Especificações das doenças com resposta SIM
    saude_respostas = d.get("saude_respostas", {})
    saude_specs = d.get("saude_especificacoes", {})
    deps = d.get("dependentes", [])

    pessoas = [("titular", normalizar(d.get("titular_nome")))]
    for i, dep in enumerate(deps):
        pessoas.append((f"dep_{i}", normalizar(dep.get("nome", f"Dependente {i+1}"))))

    cur_y = 180
    for chave, label in pessoas:
        resps = saude_respostas.get(chave, {})
        specs = saude_specs.get(chave, {})

        # Reúne perguntas com SIM
        sim_qs = [
            k for k, v in resps.items()
            if resposta_sn(v) == "S"
        ]
        if not sim_qs:
            continue
        if cur_y > 450:
            break

        tx(page, 30, cur_y, label, size=7, bold=True)
        cur_y += 12

        for k in sim_qs:
            spec = specs.get(k) or specs.get(str(k), "")
            q_num = int(k) + 1 if str(k).isdigit() else k
            linha = f"Q{q_num}" + (f": {spec}" if spec else "")
            tx(page, 185, cur_y, linha, size=7)
            cur_y += 10
        cur_y += 5


def _pagina24(page: fitz.Page, d: dict):
    """Página 24 — Declaração de Saúde / Assinatura Final."""
    # ERRO 8: "N" solto antes da assinatura -> Limpeza agressiva da área central
    cobrir(page, 150, 380, 550, 480)
    
    _bloco_assinatura(
        page, d,
        cover=(168, 485, 530, 510),
        local_xy=(265, 498),
        nome_xy=(181, 408),
        cpf_xy=(200, 460),
    )
    # Nome legível (linha adicional logo abaixo do bloco de assinatura)
    tx(page, 200, 440, normalizar(d.get("titular_nome")), size=8)


# ═══════════════════════════════════════════════════════════════════════
# HELPER MÉDICO: preenche S/N para um conjunto de perguntas
# ═══════════════════════════════════════════════════════════════════════

def _preencher_sn(page: fitz.Page, d: dict,
                  sn_ys: list, q_start: int):
    """
    Preenche as células S/N de uma página médica.

    Args:
        sn_ys   : lista de Y (baseline) para cada linha de pergunta
        q_start : índice global da primeira pergunta desta página (0-based)
                  Pág 21 → q_start=0, Pág 22 → q_start=13

    Formato de dados esperado em d['saude_respostas']:
        {
          'titular': { 0: True, 1: False, ... },   # índice = Q número - 1
          'dep_0':   { 0: False, 1: True, ... },
          ...
        }
    Também aceita chaves como str(int) ou "pergunta_N" (retrocompat).
    """
    deps = d.get("dependentes", [])
    # (chave no dict de respostas, coluna X)
    pessoas = [("titular", SN_X[0])]
    for i in range(min(5, len(deps))):
        pessoas.append((f"dep_{i}", SN_X[i + 1]))

    saude_respostas = d.get("saude_respostas", {})

    for row_idx, y in enumerate(sn_ys):
        q_idx = q_start + row_idx  # índice global 0-based

        for chave, col_x in pessoas:
            resps = saude_respostas.get(chave, {})

            # Busca a resposta em 3 formatos possíveis de chave
            valor = (
                resps.get(q_idx) or
                resps.get(str(q_idx)) or
                resps.get(f"pergunta_{q_idx + 1}")
            )
            # Se não respondeu nada, padrao = "N"
            sn = resposta_sn(valor)

            # ERRO 7: Cobre a célula com margem maior para evitar "N N" duplicado
            cobrir(page, col_x - 4, y - 12, col_x + 16, y + 4)
            tx(page, col_x, y, sn, size=8, bold=True)


def _pagina4(page: fitz.Page, d: dict):
    """
    Página 4 — Autorização para Envio de Informações.
    Localiza os textos e insere o X no quadrado à esquerda se autorizado.
    """

    def inserir_x(x, y):
        page.insert_text(
            (x, y),
            "X",
            fontname="Helvetica-Bold",
            fontsize=8,
            color=(0, 0, 0),
        )

    # 1. Autorização de Comunicações
    r1 = page.search_for("Autorizo receber comunicações")
    if not r1:
        r1 = page.search_for("Autorizo receber comunica")
        
    if r1:
        # centro_y diagnosticado foi 238.63. Usando offset -1pt conforme solicitado.
        y1 = (r1[0].y0 + r1[0].y1) / 2 - 1
        x1 = r1[0].x0 - 15  # 64.94 - 15 = 49.94
        if d.get("autoriza_comunicacoes"):
            inserir_x(x1, y1)
            print(f"[PDF] Checkbox 1 MARCADO em x={x1:.2f}, y={y1:.2f}")
        else:
            print("[PDF] Checkbox 1 VAZIO")
    else:
        print("[ERRO] Texto do checkbox 1 não encontrado na Página 4")

    # 2. Autorização de Newsletters
    r2 = page.search_for("Autorizo receber newletters")
    if not r2:
        r2 = page.search_for("newsletters")
        
    if r2:
        # centro_y diagnosticado foi 285.22. Usando offset -1pt.
        y2 = (r2[0].y0 + r2[0].y1) / 2 - 1
        x2 = r2[0].x0 - 15  # 64.94 - 15 = 49.94
        if d.get("autoriza_newsletters"):
            inserir_x(x2, y2)
            print(f"[PDF] Checkbox 2 MARCADO em x={x2:.2f}, y={y2:.2f}")
        else:
            print("[PDF] Checkbox 2 VAZIO")
    else:
        print("[ERRO] Texto do checkbox 2 não encontrado na Página 4")


# ═══════════════════════════════════════════════════════════════════════
# MAPA DE PÁGINAS: número (1-based) → função preenchedora
# ═══════════════════════════════════════════════════════════════════════

_HANDLERS: dict = {
    1:  _pagina1,
    2:  _pagina2,
    3:  _pagina3,
    4:  _pagina4,
    6:  _pagina6,
    7:  _pagina7,
    8:  _pagina8,
    17: _pagina17,
    19: _pagina19,
    21: _pagina21,
    22: _pagina22,
    23: _pagina23,
    24: _pagina24,
}


# ═══════════════════════════════════════════════════════════════════════
# FUNÇÃO PÚBLICA PRINCIPAL
# ═══════════════════════════════════════════════════════════════════════

def gerar_pdf(dados: dict, template_path: str, output_path: str) -> str:
    """
    Gera o PDF de contrato preenchido a partir do template em branco.

    Args:
        dados         : Dicionário com todos os campos do formulário.
        template_path : Caminho absoluto ou relativo para 'Padrao em Branco.pdf'.
        output_path   : Caminho de saída do PDF final.

    Returns:
        output_path (str)

    Raises:
        FileNotFoundError : se template_path não existir.
        RuntimeError      : falha ao salvar o PDF de saída.
    """
    if not os.path.exists(template_path):
        raise FileNotFoundError(f"Template não encontrado: {template_path}")

    doc = fitz.open(template_path)
    n_pages = len(doc)

    for idx in range(n_pages):
        page = doc[idx]
        
        # REMOÇÃO de qualquer anotação ou widget remanescente
        for annot in page.annots():
            page.delete_annot(annot)
        for widget in page.widgets():
            page.delete_widget(widget)
        
        num = idx + 1          # número 1-based (igual ao número impresso na página)
        handler = _HANDLERS.get(num)
        if handler:
            try:
                handler(doc[idx], dados)
            except Exception as exc:
                # Nunca abortar por causa de uma página — logar e continuar
                import traceback
                print(f"[AVISO] Erro na pagina {num}: {exc}")
                traceback.print_exc()

    doc.save(output_path, garbage=4, deflate=True)
    doc.close()
    print(f"[OK] PDF gerado: {output_path}  ({n_pages} paginas)")
    return output_path
