import secrets

def generate_tracking_code() -> str:
    """
    Генерирует трек-номер вида otk-XXXX-XXXX с использованием криптографически 
    стойкого генератора, исключая визуально спорные символы (0, O, I, 1).
    """
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    part1 = "".join(secrets.choice(alphabet) for _ in range(4))
    part2 = "".join(secrets.choice(alphabet) for _ in range(4))
    return f"otk-{part1}-{part2}"