from extract import extract_csv
from transform import transform_empresas
from load import load_mensagens

def main():
    df = extract_csv("lista_empresas.csv")
    mensagens = transform_empresas(df)
    load_mensagens(mensagens)

if __name__ == "__main__":
    main()
