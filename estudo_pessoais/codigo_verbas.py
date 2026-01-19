from itertools import combinations

# Lista de números
numeros = [
    18494.46, 110512.13, 10933.18, 284.55, 56669.33, 33075.77, 613.92, 56358.78,
    263.00, 755.93, 83.97, 19026.65, 7938.12, 303.04, 44763.71, 2649.96, 76627.47,
    220.00, 5822.67, 440.00, 5701.82
]

# Soma alvo
target = 119042.29





 
# Filtrar números: ignorar zero e números maiores que o target
numeros_filtrados = [n for n in numeros if n > 0 and n <= target]

# Lista para armazenar os subconjuntos encontrados
subconjuntos_encontrados = []

# Verificar todos os subconjuntos possíveis
for r in range(1, len(numeros_filtrados) + 1):
    for combo in combinations(numeros_filtrados, r):
        if abs(sum(combo) - target) < 0.01:  # margem mínima para evitar erro de float
            subconjuntos_encontrados.append(combo)

# Mostrar resultados
print(f"Foram encontrados {len(subconjuntos_encontrados)} subconjuntos que somam {target}:")
for s in subconjuntos_encontrados:
    print(s)
