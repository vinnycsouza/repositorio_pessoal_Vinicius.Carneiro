from itertools import combinations

# Lista de números
numeros = [
    119.26, 13902.94, 3357.78, 33261.70, 51747.38, 3628.02, 5190.14,
    1395.00, 10272.55, 1472.76, 900.00, 287.34, 1385.37, 12937.10,
    23817.45, 300.00, 12.12, 4509.00, 1214.40, 14215.96, 24465.62,
    813.00, 412.80
]

# Soma alvo
target = 110147.51
 


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
