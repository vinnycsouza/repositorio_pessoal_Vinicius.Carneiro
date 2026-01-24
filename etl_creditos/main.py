from etl_creditos.extract import extract_csv
from etl_creditos.transform import transform_empresas
from etl_creditos.load import load_mensagens

def main():
    df = extract_csv("lista_empresa.csv")
    mensagens = transform_empresas(df)
    load_mensagens(mensagens)

if __name__ == "__main__":
    main()
