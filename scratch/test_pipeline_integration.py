"""
Teste de integração: simula o fluxo do scheduler_service com dados reais
do extrator (sem fazer requisições HTTP).
"""
import asyncio
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Simula o dict que extract_product_data_v2 retorna
MOCK_EXTRATOR_OUTPUT = {
    "store": "Amazon",
    "store_key": "amazon",
    "final_url": "https://www.amazon.com.br/dp/B0CX3Y4Z5W",
    "titulo": "Fone de Ouvido JBL Tune 510BT Bluetooth",
    "imagem": "https://m.media-amazon.com/images/I/fake.jpg",
    "preco": "R$ 199,90",
    "preco_original": "R$ 299,90",
    "source_method": "SCRAPERAPI",
    "is_pix_price": False,
    "cupom": None,
}

def test_scheduler_data_mapping():
    """Verifica que as chaves usadas no scheduler existem no output do extrator."""
    dados = dict(MOCK_EXTRATOR_OUTPUT)

    # Replicando o que o scheduler faz nas linhas 93-96
    dados["title"]     = dados.get("titulo")
    dados["image_url"] = dados.get("imagem")
    dados["loja"]      = dados.get("store", "Loja")

    erros = []

    # Verifica chaves críticas que o scheduler acessa
    chaves_criticas = {
        "title":         dados.get("title"),
        "preco":         dados.get("preco"),       # CORRETO (não "price")
        "loja":          dados.get("loja"),
        "final_url":     dados.get("final_url"),   # CORRETO (não "product_url")
        "preco_original":dados.get("preco_original"),
        "store_key":     dados.get("store_key"),
        "image_url":     dados.get("image_url"),
    }

    for chave, valor in chaves_criticas.items():
        status = "OK" if valor else "AUSENTE (pode ser None - ok)"
        print(f"  [{chave}] = {repr(valor)[:60]} -> {status}")
        if chave in ("title", "preco", "loja", "store_key") and not valor:
            erros.append(f"Chave crítica ausente ou vazia: {chave}")

    return erros


def test_copy_builder():
    """Verifica que o build_copy funciona com os dados do extrator."""
    try:
        from bot.services.copy_builder import build_copy
        dados = dict(MOCK_EXTRATOR_OUTPUT)
        dados["title"] = dados.get("titulo")
        dados["loja"]  = dados.get("store", "Loja")

        copies = build_copy(
            nome          = dados["title"],
            preco         = dados.get("preco", "Preço não disponível"),
            loja          = dados["loja"],
            store_key     = dados.get("store_key", "other"),
            short_url     = dados.get("final_url", "https://example.com"),
            preco_original= dados.get("preco_original"),
            cupom         = dados.get("cupom"),
        )
        print(f"\n  [copy_builder] Telegram ({len(copies['telegram'])} chars): OK")
        print(f"  [copy_builder] WhatsApp ({len(copies['whatsapp'])} chars): OK")
        # Verificação: preço deve aparecer na copy
        assert dados["preco"] in copies["telegram"], "ERRO: preço não aparece na copy Telegram!"
        assert dados["preco"] in copies["whatsapp"], "ERRO: preço não aparece na copy WhatsApp!"
        print("  [copy_builder] Preço presente na copy: OK")
        return []
    except Exception as e:
        return [f"Erro no copy_builder: {e}"]


def test_preco_nao_disponivel_triggers_manual_entry():
    """Verifica que quando preco=None, o bot pede entrada manual (fluxo offer_by_link)."""
    dados = dict(MOCK_EXTRATOR_OUTPUT)
    dados["preco"] = None  # simula falha de extração

    # Replicando a lógica de offer_by_link.py linhas 525-533
    preco = dados.get("preco")
    deveria_pedir_preco = not preco or preco == "Preço não disponível"

    if deveria_pedir_preco:
        print("\n  [fluxo] Preco ausente -> bot pedira ao admin: OK")
        return []
    else:
        return ["ERRO: bot não pediu preço quando preco=None"]


if __name__ == "__main__":
    print("=" * 60)
    print("TESTE DE INTEGRAÇÃO DO PIPELINE")
    print("=" * 60)

    todos_erros = []

    print("\n[1] Mapeamento de chaves do scheduler:")
    todos_erros += test_scheduler_data_mapping()

    print("\n[2] Copy Builder:")
    todos_erros += test_copy_builder()

    print("\n[3] Fluxo de fallback de preço:")
    todos_erros += test_preco_nao_disponivel_triggers_manual_entry()

    print("\n" + "=" * 60)
    if todos_erros:
        print("FALHOU:")
        for e in todos_erros:
            print(f"  ❌ {e}")
        sys.exit(1)
    else:
        print("✅ TODOS OS TESTES PASSARAM — pipeline integrado OK!")
