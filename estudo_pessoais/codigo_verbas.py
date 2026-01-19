from itertools import combinations

# Lista de números
numeros = [
    802.32, 47682.93, 2406.99, 885.76, 44572.62, 30674.68, 601.75, 550.00, 63850.57,
    1067.11, 252.67, 876.13, 1.62, 11171.40, 7361.83, 21964.45, 7.20, 46547.46,
    220.00, 6123.33, 22.00, 627.00, 14126.62
]

# Soma alvo
target = 137391.15


 
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
