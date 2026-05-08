import os

erros = []
bad_patterns = [
    'dados.get("price"',
    'dados["price"]',
    'dados.get("product_url"',
    'dados["product_url"]',
    'result["price"]',
    'result.get("price"',
]

for root, dirs, files in os.walk("bot"):
    dirs[:] = [d for d in dirs if d != "__pycache__"]
    for fname in files:
        if not fname.endswith(".py"):
            continue
        fpath = os.path.join(root, fname)
        with open(fpath, encoding="utf-8") as f:
            linhas = f.readlines()
        for i, line in enumerate(linhas, 1):
            for pat in bad_patterns:
                if pat in line:
                    erros.append(f"[{pat}] {fpath}:{i}: {line.strip()}")

if erros:
    print("=== CHAVES INCORRETAS ENCONTRADAS ===")
    for e in erros:
        print(" ", e)
else:
    print("OK - nenhuma chave incorreta no pipeline.")
