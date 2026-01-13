from itertools import combinations

from itertools import combinations

def encontrar_um_subconjunto(numeros, target, tolerancia=0.01):
    for r in range(1, len(numeros) + 1):
        for combo in combinations(numeros, r):
            if abs(sum(combo) - target) < tolerancia:
                return combo  # 👈 PARA AQUI

    return None  # se não encontrar



# =========================
# DEFINIÇÃO DOS 60 CASOS
# =========================

casos = [
    {
        "numeros": [
            1774.82, 43982.78, 5324.45, 39346.25, 53672.77, 4678.87, 2490.77, 180.00,
            18304.39, 1800.00, 812.88, 667.77, 591.91, 7951.49, 21175.05, 300.00,
            4857.07, 1214.40, 20289.41, 0.00, 382.44, 7225.39, 813.00, 335.40
        ],
        "target": 115265.02
    },

    # 👇 copie esse bloco até completar os 60
    {
        "numeros": [
           
        ],
        "target": 0000.00
    },

    {
        "numeros": [
             
        ],
        "target": 0000.00
    }

    


]


# =========================
# EXECUÇÃO
# =========================

for i, caso in enumerate(casos, 1):
    resultado = encontrar_um_subconjunto(
        caso["numeros"],
        caso["target"]
    )

    print(f"\nCaso {i}")
    print(f"Target: {caso['target']}")

    if resultado:
        print("Combinação encontrada:")
        print(resultado)
    else:
        print("Nenhuma combinação encontrada.")

