from itertools import combinations

# Lista de números
numeros = [
   1433.27, 30866.79, 4299.83, 39346.25, 53380.53, 4562.87, 1000.00, 945.00,
   12985.99, 306.55, 1650.00, 848.22, 52.11, 53.50, 10265.66
]

# Soma alvo
target = 96543.77
 


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
