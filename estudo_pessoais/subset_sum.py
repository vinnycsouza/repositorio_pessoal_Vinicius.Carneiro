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
            6202.87, 0.00, 24006.04, 18608.38, 1074.01, 28506.40, 32175.44,
            6096.98, 850.00, 30134.10, 728.16, 610.48, 1813.33, 7507.49,
            19486.26, 300.00, 1500.00, 4077.33, 8286.49, 813.00, 186.30
         ],
        "target": 98834.04
    },
    {
        "numeros": [],
        "target": 0.00
    },
    {
        "numeros": [],
        "target": 0.00
    },
    {
        "numeros": [],
        "target": 0.00
    },
    {
        "numeros": [],
        "target": 0.00
    },
    {
        "numeros": [],
        "target": 0.00
    },
    {
        "numeros": [],
        "target": 0.00
    },
    {
        "numeros": [],
        "target": 0.00
    },
    {
        "numeros": [],
        "target": 0.00
    },
    {
        "numeros": [],
        "target": 0.00
    },

    {
        "numeros": [],
        "target": 0.00
    },
    {
        "numeros": [],
        "target": 0.00
    },
    {
        "numeros": [],
        "target": 0.00
    },
    {
        "numeros": [],
        "target": 0.00
    },
    {
        "numeros": [],
        "target": 0.00
    },
    {
        "numeros": [],
        "target": 0.00
    },
    {
        "numeros": [],
        "target": 0.00
    },
    {
        "numeros": [],
        "target": 0.00
    },
    {
        "numeros": [],
        "target": 0.00
    },
    {
        "numeros": [],
        "target": 0.00
    },

    {
        "numeros": [],
        "target": 0.00
    },
    {
        "numeros": [],
        "target": 0.00
    },
    {
        "numeros": [],
        "target": 0.00
    },
    {
        "numeros": [],
        "target": 0.00
    },
    {
        "numeros": [],
        "target": 0.00
    },
    {
        "numeros": [],
        "target": 0.00
    },
    {
        "numeros": [],
        "target": 0.00
    },
    {
        "numeros": [],
        "target": 0.00
    },
    {
        "numeros": [],
        "target": 0.00
    },
    {
        "numeros": [],
        "target": 0.00
    },

    {
        "numeros": [],
        "target": 0.00
    },
    {
        "numeros": [],
        "target": 0.00
    },
    {
        "numeros": [],
        "target": 0.00
    },
    {
        "numeros": [],
        "target": 0.00
    },
    {
        "numeros": [],
        "target": 0.00
    },
    {
        "numeros": [],
        "target": 0.00
    },
    {
        "numeros": [],
        "target": 0.00
    },
    {
        "numeros": [],
        "target": 0.00
    },
    {
        "numeros": [],
        "target": 0.00
    },
    {
        "numeros": [],
        "target": 0.00
    },

    {
        "numeros": [],
        "target": 0.00
    },
    {
        "numeros": [],
        "target": 0.00
    },
    {
        "numeros": [],
        "target": 0.00
    },
    {
        "numeros": [],
        "target": 0.00
    },
    {
        "numeros": [],
        "target": 0.00
    },
    {
        "numeros": [],
        "target": 0.00
    },
    {
        "numeros": [],
        "target": 0.00
    },
    {
        "numeros": [],
        "target": 0.00
    },
    {
        "numeros": [],
        "target": 0.00
    },
    {
        "numeros": [],
        "target": 0.00
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

