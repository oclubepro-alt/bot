"""
telegram_utils.py - utilitários para lidar com a API do Telegram
"""
import re

def normalize_chat_id(chat_id: str | int) -> str | int:
    """
    Normaliza o chat_id para o formato esperado pela API do Telegram.
    - Se for um link de canal (https://t.me/...), converte para @username.
    - Se for um ID numérico de canal privado, garante o prefixo -100.
    """
    if isinstance(chat_id, int):
        # Para canais, IDs negativos costumam começar com -100.
        # Se for um ID de canal (positivo e longo), prefixamos com -100.
        if chat_id > 0 and len(str(chat_id)) >= 9:
            return int(f"-100{chat_id}")
        return chat_id

    chat_id = chat_id.strip()

    # Se for link do tipo https://t.me/username
    if "t.me/" in chat_id:
        username = chat_id.split("t.me/")[-1].split("/")[0]
        if not username.startswith("@"):
            return f"@{username}"
        return username

    # Se for link do tipo t.me/username
    if chat_id.startswith("t.me/"):
        username = chat_id.replace("t.me/", "")
        if not username.startswith("@"):
            return f"@{username}"
        return username

    # Se for um ID numérico em string
    if re.match(r"^-?\d+$", chat_id):
        val = int(chat_id)
        # Se for positivo e parecer um ID de canal (não de usuário), coloca -100
        if val > 0 and len(chat_id) >= 9:
            return f"-100{chat_id}"
        # Se for um ID de canal mas sem o -100 (ex: -456789), garante o -100
        if val < 0 and not chat_id.startswith("-100") and len(chat_id) >= 10:
             # Às vezes o ID do Telegram já vem com o '-', precisamos cuidar
             raw_id = chat_id.lstrip("-")
             return f"-100{raw_id}"
        
        return chat_id

    # Se for @username, mantém
    if chat_id.startswith("@"):
        return chat_id

    return chat_id
