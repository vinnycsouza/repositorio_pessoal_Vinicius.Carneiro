
import pandas as pd
from itertools import combinations

# 1. Ler abas do Excel
arquivo_excel = "levantamento viação cruzeiro.xlsx"
ativos_df = pd.read_excel(arquivo_excel, sheet_name="Ativos", dtype=str)
desligados_df = pd.read_excel(arquivo_excel, sheet_name="Desligados", dtype=str)

# 2. Converter valores
def converter_valor(valor_str):
    if pd.isna(valor_str):
        return None
    valor_str = str(valor_str).replace(".", "").replace(",", ".")
    try:
        return float(valor_str)
    except:
        return None

# 3. Criar listas por mês
def criar_listas_por_mes(df):
    listas = {}
    for _, row in df.iterrows():
        mes = str(row.iloc[0]).strip().lower()  # normaliza
        valores = [converter_valor(v) for v in row[1:]]
        valores = [v for v in valores if v is not None]
        listas[mes] = valores
    return listas

ativos_listas = criar_listas_por_mes(ativos_df)
desligados_listas = criar_listas_por_mes(desligados_df)

# ✅ Mostrar meses disponíveis
print("\nMeses disponíveis na aba 'Ativos':", list(ativos_listas.keys()))
print("Meses disponíveis na aba 'Desligados':", list(desligados_listas.keys()))

# 4. Função para encontrar subconjuntos
def encontrar_subconjuntos(numeros, target, margem=0.01):
    numeros_filtrados = [n for n in numeros if n > 0 and n <= target]
    subconjuntos_encontrados = []
    for r in range(1, len(numeros_filtrados) + 1):
        for combo in combinations(numeros_filtrados, r):
            if abs(sum(combo) - target) < margem:
                subconjuntos_encontrados.append(combo)
    return subconjuntos_encontrados

# 5. Exemplo
target_exemplo = 37832.21
mes_exemplo = "jan/21".strip().lower()

# ✅ Verificar se o mês existe
if mes_exemplo not in ativos_listas:
    print(f"\n⚠️ O mês '{mes_exemplo}' não foi encontrado na aba 'Ativos'.")
else:
    print("\n===== ATIVOS =====")
    sub_ativos = encontrar_subconjuntos(ativos_listas.get(mes_exemplo, []), target_exemplo)
    print(f"Total de subconjuntos encontrados: {len(sub_ativos)}")
    for s in sub_ativos:
        print(s)

if mes_exemplo not in desligados_listas:
    print(f"\n⚠️ O mês '{mes_exemplo}' não foi encontrado na aba 'Desligados'.")
else:
    print("\n===== DESLIGADOS =====")
    sub_desligados = encontrar_subconjuntos(desligados_listas.get(mes_exemplo, []), target_exemplo)
    print(f"Total de subconjuntos encontrados: {len(sub_desligados)}")
    for s in sub_desligados:
        print(s)
