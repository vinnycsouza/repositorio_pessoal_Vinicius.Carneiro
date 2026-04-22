import itertools
import bisect
import pandas as pd
import numpy as np

from util_formatacao import normalizar_colunas, padronizar_dt_comp, converter_valor


# =========================
# Leitura dos arquivos
# =========================
def ler_manad(arquivo):
    df_k300 = pd.read_excel(arquivo, sheet_name="K300_FILTRADO")
    df_k150 = pd.read_excel(arquivo, sheet_name="K150_SELECIONADAS")

    df_k300 = normalizar_colunas(df_k300)
    df_k150 = normalizar_colunas(df_k150)

    if "DT_COMP" not in df_k300.columns:
        raise ValueError("A aba K300_FILTRADO não possui a coluna DT_COMP.")

    if "COD_RUBR" not in df_k300.columns:
        raise ValueError("A aba K300_FILTRADO não possui a coluna COD_RUBR.")

    if "VLR_RUBR" not in df_k300.columns:
        raise ValueError("A aba K300_FILTRADO não possui a coluna VLR_RUBR.")

    df_k300["DT_COMP"] = df_k300["DT_COMP"].apply(padronizar_dt_comp)
    df_k300["COD_RUBR"] = df_k300["COD_RUBR"].astype(str).str.strip()
    df_k300["VLR_RUBR"] = converter_valor(df_k300["VLR_RUBR"])

    # Normalização flexível da K150
    mapa_cod = None
    mapa_desc = None

    for col in df_k150.columns:
        nome = str(col).strip().upper()
        if nome in ["COD_RUBRICA", "COD_RUBR", "CODIGO_RUBRICA", "CODIGO"]:
            mapa_cod = col
        if nome in ["DESC_RUBRICA", "DESCRICAO_RUBRICA", "DESCRICAO", "NOME_RUBRICA"]:
            mapa_desc = col

    if mapa_cod is None:
        raise ValueError(
            f"Não encontrei a coluna de código da rubrica na K150_SELECIONADAS. Colunas encontradas: {list(df_k150.columns)}"
        )

    if mapa_desc is None:
        raise ValueError(
            f"Não encontrei a coluna de descrição da rubrica na K150_SELECIONADAS. Colunas encontradas: {list(df_k150.columns)}"
        )

    df_k150 = df_k150.rename(columns={mapa_cod: "COD_RUBRICA", mapa_desc: "DESC_RUBRICA"})
    df_k150["COD_RUBRICA"] = df_k150["COD_RUBRICA"].astype(str).str.strip()
    df_k150["DESC_RUBRICA"] = df_k150["DESC_RUBRICA"].astype(str).str.strip()

    return df_k300, df_k150


def ler_esocial(arquivo):
    df = pd.read_excel(arquivo)
    df = normalizar_colunas(df)

    colunas_originais = df.columns.tolist()
    colunas_padronizadas = {
        col: str(col).strip().upper().replace(" ", "_")
        for col in colunas_originais
    }
    df = df.rename(columns=colunas_padronizadas)

    possiveis_colunas_base = [
        "BASE_INSS_ESOCIAL",
        "BASE_ESOCIAL",
        "VALOR_ESOCIAL",
        "VALORES_ESOCIAL",
        "VALOR_SOMADO",
        "BASE_INSS",
        "11_-_BASE_DE_CALCULO_DA_CONTRIBUICAO_PREVIDENCIARIA",
        "BASE_DE_CALCULO_DA_CONTRIBUICAO_PREVIDENCIARIA",
    ]

    coluna_base_encontrada = None
    for col in possiveis_colunas_base:
        if col in df.columns:
            coluna_base_encontrada = col
            break

    if "DT_COMP" not in df.columns:
        raise ValueError(
            f"O arquivo do eSocial não possui a coluna DT_COMP. Colunas encontradas: {list(df.columns)}"
        )

    if coluna_base_encontrada is None:
        raise ValueError(
            f"Não encontrei a coluna da base do eSocial. Colunas encontradas: {list(df.columns)}"
        )

    df = df.rename(columns={coluna_base_encontrada: "BASE_INSS_ESOCIAL"})
    df["DT_COMP"] = df["DT_COMP"].apply(padronizar_dt_comp)
    df["BASE_INSS_ESOCIAL"] = converter_valor(df["BASE_INSS_ESOCIAL"])

    return df[["DT_COMP", "BASE_INSS_ESOCIAL"]].copy()


# =========================
# Base analítica do MANAD
# =========================
def classificar_natureza_rubrica(descricao):
    desc = str(descricao).strip().upper()

    palavras_indenizatorias = [
        "INDENIZ",
        "REEMBOL",
        "RESTITU",
        "AVISO PREVIO INDEN",
        "DESCANSO INDEN",
        "DIARIA",
        "AJUDA DE CUSTO",
        "BOLSA",
        "MULTA",
    ]

    palavras_remuneratorias = [
        "SALARIO",
        "HORA EXTRA",
        "HE ",
        "HORA NOTURNA",
        "ADICIONAL",
        "INSALUBR",
        "PERICUL",
        "NOTURNO",
        "COMISSAO",
        "GRATIFIC",
        "DSR",
        "DESCANSO SEMANAL",
        "FERIAS",
        "13",
        "DECIMO",
        "PRO LABORE",
        "MATERNIDADE",
        "PATERNIDADE",
    ]

    for p in palavras_indenizatorias:
        if p in desc:
            return "INDENIZATORIA_POTENCIAL"

    for p in palavras_remuneratorias:
        if p in desc:
            return "REMUNERATORIA_POTENCIAL"

    return "NAO_CLASSIFICADA"


def prioridade_natureza(natureza):
    prioridades = {
        "REMUNERATORIA_POTENCIAL": 0,
        "NAO_CLASSIFICADA": 1,
        "INDENIZATORIA_POTENCIAL": 2,
    }
    return prioridades.get(natureza, 9)


def montar_base_manad(df_k300, df_k150):
    df = (
        df_k300.groupby(["DT_COMP", "COD_RUBR"], as_index=False)["VLR_RUBR"]
        .sum()
    )

    df = df.merge(
        df_k150[["COD_RUBRICA", "DESC_RUBRICA"]],
        left_on="COD_RUBR",
        right_on="COD_RUBRICA",
        how="left"
    )

    df = df.drop(columns=["COD_RUBRICA"], errors="ignore")
    df["DESC_RUBRICA"] = df["DESC_RUBRICA"].fillna("SEM DESCRICAO")
    df["NATUREZA_ANALITICA"] = df["DESC_RUBRICA"].apply(classificar_natureza_rubrica)
    df["FOI_USADA_NA_COMPOSICAO"] = "NAO"

    return df


# =========================
# Busca de composição
# =========================
def _gerar_subsets(valores):
    resultados = []
    n = len(valores)
    for mascara in range(1 << n):
        soma = 0.0
        indices = []
        for i in range(n):
            if mascara & (1 << i):
                soma += valores[i]
                indices.append(i)
        resultados.append((soma, indices))
    return resultados


def encontrar_melhor_composicao(df_comp, alvo, top_n=24):
    df_local = df_comp.copy()
    df_local = df_local[df_local["VLR_RUBR"] > 0].copy()

    if df_local.empty:
        return [], 0.0, alvo

    # Ordena priorizando:
    # 1) natureza remuneratória
    # 2) maiores valores
    df_local["PRIORIDADE"] = df_local["NATUREZA_ANALITICA"].apply(prioridade_natureza)
    df_local = df_local.sort_values(
        by=["PRIORIDADE", "VLR_RUBR"],
        ascending=[True, False]
    ).reset_index(drop=True)

    # Limita o universo para manter performance
    candidatos = df_local.head(top_n).copy().reset_index(drop=False)
    candidatos = candidatos.rename(columns={"index": "IDX_ORIGINAL"})

    valores = candidatos["VLR_RUBR"].tolist()
    n = len(valores)

    if n == 0:
        return [], 0.0, alvo

    meio = n // 2
    valores_a = valores[:meio]
    valores_b = valores[meio:]

    subsets_a = _gerar_subsets(valores_a)
    subsets_b = _gerar_subsets(valores_b)

    subsets_b.sort(key=lambda x: x[0])
    somas_b = [x[0] for x in subsets_b]

    melhor_diff = float("inf")
    melhor_soma = 0.0
    melhor_indices = []

    for soma_a, idx_a in subsets_a:
        restante = alvo - soma_a
        pos = bisect.bisect_left(somas_b, restante)

        for cand_pos in [pos - 1, pos, pos + 1]:
            if 0 <= cand_pos < len(subsets_b):
                soma_b, idx_b = subsets_b[cand_pos]
                soma_total = soma_a + soma_b
                diff = abs(alvo - soma_total)

                if diff < melhor_diff:
                    melhor_diff = diff
                    melhor_soma = soma_total
                    melhor_indices = idx_a + [i + meio for i in idx_b]

    indices_reais = candidatos.iloc[melhor_indices]["IDX_ORIGINAL"].tolist()
    diferenca = alvo - melhor_soma

    return indices_reais, melhor_soma, diferenca


def analisar_composicao_base(df_base_manad, df_esocial, top_n=24):
    df_base = df_base_manad.copy()
    df_base["FOI_USADA_NA_COMPOSICAO"] = "NAO"

    resultados_resumo = []
    detalhes_composicao = []

    competencias = sorted(set(df_base["DT_COMP"].dropna().astype(str)) | set(df_esocial["DT_COMP"].dropna().astype(str)))

    for comp in competencias:
        df_mes = df_base[df_base["DT_COMP"].astype(str) == str(comp)].copy()

        valor_esocial = df_esocial.loc[
            df_esocial["DT_COMP"].astype(str) == str(comp),
            "BASE_INSS_ESOCIAL"
        ].sum()

        valor_esocial = float(valor_esocial) if pd.notna(valor_esocial) else 0.0

        idx_escolhidos, soma_encontrada, diferenca = encontrar_melhor_composicao(
            df_mes,
            alvo=valor_esocial,
            top_n=top_n
        )

        if idx_escolhidos:
            df_base.loc[df_mes.iloc[idx_escolhidos].index, "FOI_USADA_NA_COMPOSICAO"] = "SIM"

        df_usadas = df_base.loc[df_mes.iloc[idx_escolhidos].index].copy() if idx_escolhidos else df_mes.iloc[0:0].copy()

        tem_indenizatoria = "SIM" if not df_usadas[df_usadas["NATUREZA_ANALITICA"] == "INDENIZATORIA_POTENCIAL"].empty else "NAO"

        resultados_resumo.append({
            "DT_COMP": comp,
            "BASE_INSS_ESOCIAL": valor_esocial,
            "SOMA_ENCONTRADA_MANAD": soma_encontrada,
            "DIFERENCA": diferenca,
            "QTD_RUBRICAS_USADAS": len(df_usadas),
            "TEM_INDENIZATORIA_POTENCIAL": tem_indenizatoria,
            "STATUS": "OK" if abs(diferenca) <= 0.05 else "REVISAR"
        })

        if not df_usadas.empty:
            detalhes_composicao.append(df_usadas.copy())

    df_resumo = pd.DataFrame(resultados_resumo).sort_values("DT_COMP").reset_index(drop=True)

    if detalhes_composicao:
        df_composicao = pd.concat(detalhes_composicao, ignore_index=True)
    else:
        df_composicao = df_base.iloc[0:0].copy()

    return df_resumo, df_base, df_composicao