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

