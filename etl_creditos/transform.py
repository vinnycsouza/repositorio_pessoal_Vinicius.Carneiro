def transform_empresas(df):
    mensagens = []

    for _, row in df.iterrows():
        saldo = (
            row["Valor total de levantamento em Sistema S"]
            - row["Valor já utilizado em compensação"]
        )

        possui_credito = row["Possui crédito"].strip().lower()

        if possui_credito == "sim":
            texto = (
                f"Olá {row['Nome Empresa']},\n\n"
                f"Você possui crédito disponível para compensação.\n"
                f"Valor disponível: R$ {saldo:,.2f}"
            )
        else:
            texto = (
                f"Olá {row['Nome Empresa']},\n\n"
                "No momento não há crédito disponível para compensação."
            )

        mensagens.append({
            "email": row["Email"],
            "mensagem": texto
        })

    return mensagens
