import pandas as pd
from pathlib import Path

def exportar_excel(resultado):

    exports = Path("exports")
    exports.mkdir(exist_ok=True)

    caminho = exports / "analise_icms_pis_cofins.xlsx"

    with pd.ExcelWriter(
        caminho,
        engine="xlsxwriter",
        engine_kwargs={"options": {"constant_memory": True}}
    ) as writer:

        for nome, df in resultado.items():

            if isinstance(df, pd.DataFrame):
                df.to_excel(
                    writer,
                    sheet_name=nome[:31],
                    index=False
                )

    return caminho
