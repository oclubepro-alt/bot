import fitz

doc = fitz.open("Padrao em Branco.pdf")
page = doc[1]  # página 2 = índice 1

print("=== MAPEAMENTO COMPLETO DA PÁGINA 2 ===\n")

# Labels que precisamos localizar
labels = [
    "1 - Nome Completo",
    "2 - Nome Completo",
    "3 - Nome Completo",
    "4 - Nome Completo",
    "5 - Nome Completo",
    "Data de nascimento",
    "Sexo",
    "Estado Civil",
    "Parentesco",
    "CPF",
    "Nome da mãe completo",
]

encontrados = {}
nao_encontrados = []

for label in labels:
    resultados = page.search_for(label)
    if resultados:
        r = resultados[0]
        encontrados[label] = r
        print(f"ENCONTRADO | {label}")
        print(f"  x0={r.x0:.2f}, y0={r.y0:.2f}, x1={r.x1:.2f}, y1={r.y1:.2f}")
        print(f"  altura_label={r.y1 - r.y0:.2f}pt")
        print()
    else:
        nao_encontrados.append(label)
        print(f"NÃO ENCONTRADO | {label}")
        print()

# Tentar variações para os não encontrados
variacoes = {
    "Nome da mãe completo": [
        "Nome da mãe",
        "mae completo",
        "mãe completo",
        "Nome da me completo",
    ],
    "Data de nascimento": [
        "Data de nascimento",
        "nascimento",
    ],
}

print("\n=== TENTANDO VARIAÇÕES PARA NÃO ENCONTRADOS ===\n")
for original, tentativas in variacoes.items():
    if original in nao_encontrados:
        for tentativa in tentativas:
            res = page.search_for(tentativa)
            if res:
                r = res[0]
                print(f"Variação encontrada para '{original}': '{tentativa}'")
                print(f"  x0={r.x0:.2f}, y0={r.y0:.2f}")
                break

# Dimensões da página
print(f"\n=== DIMENSÕES DA PÁGINA ===")
print(f"Largura: {page.rect.width:.2f}pt")
print(f"Altura: {page.rect.height:.2f}pt")

doc.close()
