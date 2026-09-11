#transformação.py
"""
Transformação dos microdados do ENEM para a camada Silver.

Este módulo seleciona as variáveis definidas no catálogo, aplica
o recorte geográfico por UF, normaliza valores vazios e converte
os tipos das colunas.

Os identificadores e códigos geográficos são preservados como texto.
Notas e percentuais são convertidos para DOUBLE. Variáveis categóricas
numéricas são convertidas para SMALLINT.
"""

from typing import List, Set

import duckdb

from .leitura import (
    citar_identificador,
    escapar_texto_sql,
    obter_colunas_view,
    validar_nome_view,
)


VARIAVEIS_CATEGORICAS_TEXTO: Set[str] = {
    "TP_SEXO",
    "TP_STATUS_REDACAO",
}


def definir_tipo_sql(
    variavel: str,
) -> str:
    """
    Define o tipo SQL de uma variável.
    """
    if variavel == "NU_ANO":
        return "SMALLINT"

    if (
        variavel.startswith("NU_NOTA_")
        or variavel.startswith("VL_PERC_")
    ):
        return "DOUBLE"

    if (
        variavel.startswith("TP_")
        and variavel
        not in VARIAVEIS_CATEGORICAS_TEXTO
    ):
        return "SMALLINT"

    return "VARCHAR"


def criar_expressao_transformacao(
    variavel: str,
) -> str:
    """
    Cria a expressão SQL de limpeza e conversão.
    """
    coluna = citar_identificador(
        variavel
    )

    tipo_sql = definir_tipo_sql(
        variavel
    )

    if tipo_sql == "VARCHAR":
        return (
            f"NULLIF(TRIM({coluna}), '') "
            f"AS {coluna}"
        )

    return (
        f"CAST(NULLIF(TRIM({coluna}), '') "
        f"AS {tipo_sql}) AS {coluna}"
    )


def obter_coluna_uf(
    ano: int,
    colunas_disponiveis: List[str],
) -> str:
    """
    Define a variável territorial usada no recorte.

    1998–2007: UF de residência.
    2008–2025: UF de realização da prova.
    """
    if ano <= 2007:
        coluna_uf = "SG_UF_RESIDENCIA"
    else:
        coluna_uf = "SG_UF_PROVA"

    if coluna_uf not in colunas_disponiveis:
        raise KeyError(
            f"A variável territorial {coluna_uf} "
            f"não existe nos dados de {ano}."
        )

    return coluna_uf


def criar_view_estado(
    conexao: duckdb.DuckDBPyConnection,
    nome_view_origem: str,
    nome_view_destino: str,
    variaveis: List[str],
    ano: int,
    uf: str,
) -> str:
    """
    Cria uma view tipada e filtrada para uma UF.

    Retorna o nome da variável territorial utilizada.
    """
    validar_nome_view(nome_view_origem)
    validar_nome_view(nome_view_destino)

    uf = uf.strip().upper()

    if len(uf) != 2 or not uf.isalpha():
        raise ValueError(
            f"Sigla de UF inválida: {uf}"
        )
    uf_sql = escapar_texto_sql(uf)
    colunas_disponiveis = obter_colunas_view(
        conexao=conexao,
        nome_view=nome_view_origem,
    )

    variaveis_ausentes = sorted(
        set(variaveis)
        - set(colunas_disponiveis)
    )

    if variaveis_ausentes:
        raise KeyError(
            "Variáveis selecionadas ausentes "
            f"no CSV: {variaveis_ausentes}"
        )

    coluna_uf = obter_coluna_uf(
        ano=ano,
        colunas_disponiveis=colunas_disponiveis,
    )

    expressoes = [
        criar_expressao_transformacao(
            variavel
        )
        for variavel in variaveis
    ]

    selecao_sql = ",\n    ".join(
        expressoes
    )

    view_origem_sql = citar_identificador(
        nome_view_origem
    )

    view_destino_sql = citar_identificador(
        nome_view_destino
    )

    coluna_uf_sql = citar_identificador(
        coluna_uf
    )

    conexao.execute(
        f"""
        CREATE OR REPLACE TEMP VIEW
            {view_destino_sql} AS

        SELECT
            {selecao_sql}

        FROM {view_origem_sql}

        WHERE UPPER(TRIM({coluna_uf_sql})) = '{uf_sql}'
        """
    )

    return coluna_uf