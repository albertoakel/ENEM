#leitura.py
"""
Rotinas de leitura dos microdados do ENEM com DuckDB.

Este módulo cria conexões DuckDB em memória e views temporárias
sobre os CSVs extraídos na área de staging.

Os CSVs são inicialmente lidos como texto. A conversão de tipos,
a filtragem geográfica e a harmonização pertencem ao módulo de
transformação.
"""

from pathlib import Path
from typing import List,Dict
import re

import duckdb

from .config import SEPARADOR_MICRODADOS


def criar_conexao() -> duckdb.DuckDBPyConnection:
    """
    Cria uma conexão DuckDB em memória.
    """
    return duckdb.connect()


def escapar_texto_sql(valor: str) -> str:
    """
    Escapa aspas simples em textos usados no SQL.
    """
    return valor.replace("'", "''")


def citar_identificador(nome: str) -> str:
    """
    Protege nomes de colunas e views para uso em SQL.
    """
    return '"' + nome.replace('"', '""') + '"'


def validar_nome_view(nome_view: str) -> None:
    """
    Valida o nome de uma view temporária.
    """
    padrao = r"^[A-Za-z_][A-Za-z0-9_]*$"

    if re.fullmatch(padrao, nome_view) is None:
        raise ValueError(
            f"Nome de view inválido: {nome_view}"
        )


def criar_view_csv(
    conexao: duckdb.DuckDBPyConnection,
    arquivo_csv: Path,
    nome_view: str,
    separador: str = SEPARADOR_MICRODADOS,
    codificacao: str = "utf-8",
) -> None:
    """
    Cria uma view temporária sobre um CSV.

    Todas as colunas são inicialmente tratadas como VARCHAR.
    """
    if not arquivo_csv.exists():
        raise FileNotFoundError(
            f"CSV não encontrado: {arquivo_csv}"
        )

    validar_nome_view(nome_view)

    codificacoes_permitidas = {
        "utf-8",
        "utf-16",
        "latin-1",
    }
    codificacao = codificacao.strip().lower()

    if codificacao not in codificacoes_permitidas:
        raise ValueError(
            "Codificação não suportada: "
            f"{codificacao}"
        )

    caminho_sql = escapar_texto_sql(
        str(arquivo_csv)
    )

    separador_sql = escapar_texto_sql(
        separador
    )
    codificacao_sql = escapar_texto_sql(
        codificacao
    )

    view_sql = citar_identificador(
        nome_view
    )

    conexao.execute(
        f"""
        CREATE OR REPLACE TEMP VIEW {view_sql} AS

        SELECT *
        FROM read_csv(
            '{caminho_sql}',
            delim = '{separador_sql}',
            header = true,
            all_varchar = true,
            encoding = '{codificacao_sql}'
        )
        """
    )


def obter_colunas_view(
    conexao: duckdb.DuckDBPyConnection,
    nome_view: str,
) -> List[str]:
    """
    Retorna os nomes das colunas de uma view.
    """
    validar_nome_view(nome_view)

    view_sql = citar_identificador(
        nome_view
    )

    resultado = conexao.execute(
        f"""
        DESCRIBE {view_sql}
        """
    ).fetchall()

    return [
        linha[0]
        for linha in resultado
    ]


def contar_registros(
    conexao: duckdb.DuckDBPyConnection,
    nome_view: str,
) -> int:
    """
    Conta os registros de uma view.
    """
    validar_nome_view(nome_view)

    view_sql = citar_identificador(
        nome_view
    )

    resultado = conexao.execute(
        f"""
        SELECT COUNT(*)
        FROM {view_sql}
        """
    ).fetchone()

    return int(resultado[0])

#---------------------------
def criar_view_arquivos_principais(
    conexao: duckdb.DuckDBPyConnection,
    arquivos_csv: List[Path],
    nome_view: str,
    separador: str = SEPARADOR_MICRODADOS,
    codificacao: str = "utf-8",

) -> str:
    """
    Cria uma view unificada a partir dos CSVs principais.

    Layouts aceitos:
    - arquivo único: MICRODADOS_ENEM_AAAA.csv;
    - layout dividido: PARTICIPANTES_AAAA.csv e
      RESULTADOS_AAAA.csv.

    No layout dividido, os arquivos são unidos por NU_INSCRICAO.
    Colunas existentes nos dois arquivos são preservadas apenas
    a partir do arquivo de participantes.

    Retorna o layout identificado:
    - "unico";
    - "separado".
    """
    validar_nome_view(nome_view)

    arquivos_csv = [
        Path(arquivo)
        for arquivo in arquivos_csv
    ]

    if len(arquivos_csv) == 1:
        criar_view_csv(
            conexao=conexao,
            arquivo_csv=arquivos_csv[0],
            nome_view=nome_view,
            separador=separador,
            codificacao=codificacao,

        )

        return "unico"

    if len(arquivos_csv) != 2:
        raise ValueError(
            "Era esperado um arquivo único ou dois "
            "arquivos do layout separado."
        )

    arquivo_participantes = next(
        (
            arquivo
            for arquivo in arquivos_csv
            if "PARTICIPANTES" in arquivo.name.upper()
        ),
        None,
    )

    arquivo_resultados = next(
        (
            arquivo
            for arquivo in arquivos_csv
            if "RESULTADOS" in arquivo.name.upper()
        ),
        None,
    )

    if (
        arquivo_participantes is None
        or arquivo_resultados is None
    ):
        raise ValueError(
            "Não foi possível identificar os arquivos "
            "de participantes e resultados."
        )

    nome_view_participantes = (
        f"{nome_view}_participantes"
    )
    nome_view_resultados = (
        f"{nome_view}_resultados"
    )

    criar_view_csv(
        conexao=conexao,
        arquivo_csv=arquivo_participantes,
        nome_view=nome_view_participantes,
        separador=separador,
        codificacao=codificacao,

    )

    criar_view_csv(
        conexao=conexao,
        arquivo_csv=arquivo_resultados,
        nome_view=nome_view_resultados,
        separador=separador,
        codificacao=codificacao,

    )

    colunas_participantes = obter_colunas_view(
        conexao=conexao,
        nome_view=nome_view_participantes,
    )

    colunas_resultados = obter_colunas_view(
        conexao=conexao,
        nome_view=nome_view_resultados,
    )

    chave = "NU_INSCRICAO"

    if chave not in colunas_participantes:
        raise KeyError(
            f"{chave} ausente no arquivo de participantes."
        )

    if chave not in colunas_resultados:
        raise KeyError(
            f"{chave} ausente no arquivo de resultados."
        )

    conjunto_participantes = set(
        colunas_participantes
    )

    colunas_exclusivas_resultados = [
        coluna
        for coluna in colunas_resultados
        if coluna not in conjunto_participantes
    ]

    expressoes_participantes = [
        (
            f"p.{citar_identificador(coluna)} "
            f"AS {citar_identificador(coluna)}"
        )
        for coluna in colunas_participantes
    ]

    expressoes_resultados = [
        (
            f"r.{citar_identificador(coluna)} "
            f"AS {citar_identificador(coluna)}"
        )
        for coluna in colunas_exclusivas_resultados
    ]

    expressoes = (
        expressoes_participantes
        + expressoes_resultados
    )

    selecao_sql = ",\n    ".join(
        expressoes
    )

    view_destino_sql = citar_identificador(
        nome_view
    )

    view_participantes_sql = citar_identificador(
        nome_view_participantes
    )

    view_resultados_sql = citar_identificador(
        nome_view_resultados
    )

    chave_sql = citar_identificador(
        chave
    )

    conexao.execute(
        f"""
        CREATE OR REPLACE TEMP VIEW
            {view_destino_sql} AS

        SELECT
            {selecao_sql}

        FROM {view_participantes_sql} AS p

        INNER JOIN {view_resultados_sql} AS r
            ON p.{chave_sql} = r.{chave_sql}
        """
    )

    return "separado"

#----------
def validar_layout_separado(
    conexao: duckdb.DuckDBPyConnection,
    nome_view_base: str,
) -> Dict[str, int]:
    """
    Valida a correspondência entre participantes e resultados.

    As views devem ter sido criadas por
    criar_view_arquivos_principais().
    """
    validar_nome_view(nome_view_base)

    nome_participantes = (
        f"{nome_view_base}_participantes"
    )
    nome_resultados = (
        f"{nome_view_base}_resultados"
    )

    validar_nome_view(nome_participantes)
    validar_nome_view(nome_resultados)

    participantes_sql = citar_identificador(
        nome_participantes
    )

    resultados_sql = citar_identificador(
        nome_resultados
    )

    chave_sql = citar_identificador(
        "NU_INSCRICAO"
    )

    resumo_participantes = conexao.execute(
        f"""
        SELECT
            COUNT(*) AS total,

            COUNT({chave_sql})
            - COUNT(DISTINCT {chave_sql})
                AS duplicacoes,

            COUNT(*) FILTER (
                WHERE NULLIF(
                    TRIM({chave_sql}),
                    ''
                ) IS NULL
            ) AS chaves_nulas

        FROM {participantes_sql}
        """
    ).fetchone()

    resumo_resultados = conexao.execute(
        f"""
        SELECT
            COUNT(*) AS total,

            COUNT({chave_sql})
            - COUNT(DISTINCT {chave_sql})
                AS duplicacoes,

            COUNT(*) FILTER (
                WHERE NULLIF(
                    TRIM({chave_sql}),
                    ''
                ) IS NULL
            ) AS chaves_nulas

        FROM {resultados_sql}
        """
    ).fetchone()

    correspondencia = conexao.execute(
        f"""
        SELECT
            (
                SELECT COUNT(*)
                FROM {participantes_sql} AS p

                WHERE NULLIF(
                    TRIM(p.{chave_sql}),
                    ''
                ) IS NOT NULL

                  AND NOT EXISTS (
                      SELECT 1
                      FROM {resultados_sql} AS r
                      WHERE
                          r.{chave_sql}
                          = p.{chave_sql}
                  )
            ) AS participantes_sem_resultado,

            (
                SELECT COUNT(*)
                FROM {resultados_sql} AS r

                WHERE NULLIF(
                    TRIM(r.{chave_sql}),
                    ''
                ) IS NOT NULL

                  AND NOT EXISTS (
                      SELECT 1
                      FROM {participantes_sql} AS p
                      WHERE
                          p.{chave_sql}
                          = r.{chave_sql}
                  )
            ) AS resultados_sem_participante
        """
    ).fetchone()

    return {
        "total_participantes": int(
            resumo_participantes[0]
        ),
        "duplicacoes_participantes": int(
            resumo_participantes[1]
        ),
        "chaves_nulas_participantes": int(
            resumo_participantes[2]
        ),
        "total_resultados": int(
            resumo_resultados[0]
        ),
        "duplicacoes_resultados": int(
            resumo_resultados[1]
        ),
        "chaves_nulas_resultados": int(
            resumo_resultados[2]
        ),
        "participantes_sem_resultado": int(
            correspondencia[0]
        ),
        "resultados_sem_participante": int(
            correspondencia[1]
        ),
    }