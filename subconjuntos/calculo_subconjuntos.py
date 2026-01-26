import pandas as pd
from itertools import combinations

# ================================
# 1. Ler abas do Excel
# ================================
arquivo_excel = "levantamento viação cruzeiro.xlsx"

ativos_df = pd.read_excel(arquivo_excel, sheet_name="Ativos")
desligados_df = pd.read_excel(arquivo_excel, sheet_name="Desligados")
base_df = pd.read_excel(arquivo_excel, sheet_name="Base de calculo")

# ================================
# 2. Extrair targets
# ================================
def extrair_targets(df, tipo):
    if tipo == "Ativos":
        coluna_target = "H"
    else:
        coluna_target = "I"
    targets_df = df[["G", coluna_target]].copy()
    targets_df.columns = ["Mes", "Target"]
    targets_df["Tipo"] = tipo
    return targets_df

ativos_targets = extrair_targets(ativos_df, "Ativos")
desligados_targets = extrair_targets(desligados_df, "Desligados")
todos_targets = pd.concat([ativos_targets, desligados_targets], ignore_index=True)

# ================================
# 3. Criar listas por mês automaticamente
# ================================
# Vamos assumir que a primeira coluna da aba Base de calculo é "Mes"
# e as demais colunas contém valores que podem ser somados
# Ajuste os nomes das colunas se forem diferentes
listas_por_mes = {}

for mes in base_df["Mes"].unique():
    # Pega todas as linhas daquele mês, ignora NaN e transforma em lista
    valores = base_df.loc[base_df["Mes"] == mes].drop(columns=["Mes"]).values.flatten()
    valores = [v for v in valores if pd.notna(v)]
    listas_por_mes[mes] = valores

# ================================
# 4. Função para encontrar subconjuntos
# ================================
def encontrar_subconjuntos(numeros, target, margem=0.01):
    numeros_filtrados = [n for n in numeros if n > 0 and n <= target]
    subconjuntos_encontrados = []

    for r in range(1, len(numeros_filtrados) + 1):
        for combo in combinations(numeros_filtrados, r):
            if abs(sum(combo) - target) < margem:
                subconjuntos_encontrados.append(combo)
    return subconjuntos_encontrados

# ================================
# 5. Rodar cálculo para todos os targets
# ================================
resultados = []

for _, row in todos_targets.iterrows():
    mes = row["Mes"]
    target = row["Target"]
    tipo = row["Tipo"]
    
    if mes not in listas_por_mes:
        print(f"Atenção: lista do mês {mes} não encontrada. Pulando...")
        continue
    
    numeros = listas_por_mes[mes]
    subconjuntos = encontrar_subconjuntos(numeros, target)
    
    resultados.append({
        "Mes": mes,
        "Tipo": tipo,
        "Target": target,
        "Subconjuntos": subconjuntos
    })

# ================================
# 6. Mostrar resultados
# ================================
for res in resultados:
    print(f"\nMês: {res['Mes']} | Tipo: {res['Tipo']} | Target: {res['Target']}")
    print(f"Subconjuntos encontrados ({len(res['Subconjuntos'])}):")
    for s in res["Subconjuntos"]:
        print(s)
