maior_idade = 18
idade_especial = 17


idade = int(input("Informe sua idade: "))

if idade >= maior_idade:
    print("Maior de idade, pode tirar a CNH.")

if idade < maior_idade:
    print("Não pode tirar a CNH.")




if idade >= maior_idade:
    print("Maior de idade, pode tirar a CNH.")

else:
    print("Não pode tirar a CNH.")    





if idade >= maior_idade:
    print("Maior de idade, pode tirar a CNH.")

elif idade == idade_especial:
    print("Pode fazer as aulas teóricas, mas não pode fazer as aulas praticas")

else:
    print("Não pode tirar a CNH.")    