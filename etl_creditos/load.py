def load_mensagens(mensagens):
    for item in mensagens:
        print("=" * 40)
        print("Para:", item["email"])
        print(item["mensagem"])
