from itertools import combinations

# Lista de números
numeros = [
    1774.82, 43982.78, 5324.45, 39346.25, 53672.77, 4678.87, 2490.77, 180.00,
    18304.39, 1800.00, 812.88, 667.77, 591.91, 7951.49, 21175.05, 300.00, 4857.07,
    1214.40, 20289.41, 0.00, 382.44, 7225.39, 813.00, 335.40
]

# Soma alvo
target = 115265.02

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
