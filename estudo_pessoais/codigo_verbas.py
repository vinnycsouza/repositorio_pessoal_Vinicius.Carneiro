from itertools import combinations

# Lista de números
numeros = [
    1813.95, 7091.42, 722.68, 173.44, 
    762.32, 5441.89, 220.00, 
    244.28, 28709.12
]

# Soma alvo
target = 37832.21



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
