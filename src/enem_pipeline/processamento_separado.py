"""
Processamento do layout separado do ENEM 2024–2025.

As bases de participantes e resultados são processadas
independentemente, pois não possuem chave individual comum.

A correspondência é avaliada somente de forma agregada,
por município de realização da prova.
"""

from pathlib import Path
from typing import Dict, List, Optional, Tuple

import duckdb
import pandas as pd

from .catalogo import obter_variaveis_ano
from .config import (
    CODIFICACAO_MICRODADOS_PADRAO,
    CODIFICACAO_MICRODADOS_POR_ANO,
)
from .extracao import extrair_csvs_principais
from .gravacao import (
    construir_caminho_parquet_separado,
    gravar_parquet_separado,
)
from .leitura import (
    citar_identificador,
    criar_conexao,
    criar_view_csv,
    escapar_texto_sql,
    obter_colunas_view,
)
from .transformacao import (
    criar_view_estado,
    obter_coluna_uf,
)


BASES_SEPARADAS = {
    "participantes": "NU_INSCRICAO",
    "resultados": "NU_SEQUENCIAL",
}


def validar_base_separada(
    conexao: duckdb.DuckDBPyConnection,
    nome_relacao: str,
    ano: int,
    uf: str,
    coluna_uf: str,
    identificador: str,
) -> Dict[str, int]:
    """
    Valida uma base individual de participantes ou resultados.
    """
    relacao_sql = citar_identificador(
        nome_relacao
    )

    coluna_uf_sql = citar_identificador(
        coluna_uf
    )

    identificador_sql = citar_identificador(
        identificador
    )

    uf = uf.strip().upper()

    resultado = conexao.execute(
        f"""
        SELECT
            COUNT(*) AS total_linhas,

            COUNT(*) - COUNT(
                DISTINCT {identificador_sql}
            ) AS duplicacoes,

            COUNT(*) FILTER (
                WHERE {identificador_sql} IS NULL
                   OR TRIM({identificador_sql}) = ''
            ) AS identificadores_nulos,

            COUNT(*) FILTER (
                WHERE {coluna_uf_sql} IS NULL
                   OR UPPER(
                       TRIM({coluna_uf_sql})
                   ) <> '{uf}'
            ) AS outras_ufs,

            COUNT(*) FILTER (
                WHERE NU_ANO IS NULL
                   OR NU_ANO <> {int(ano)}
            ) AS anos_invalidos

        FROM {relacao_sql}
        """
    ).fetchone()

    validacao = {
        "total_linhas": int(resultado[0]),
        "duplicacoes": int(resultado[1]),
        "identificadores_nulos": int(
            resultado[2]
        ),
        "outras_ufs": int(resultado[3]),
        "anos_invalidos": int(resultado[4]),
    }

    if validacao["total_linhas"] == 0:
        raise RuntimeError(
            f"Nenhum registro encontrado em "
            f"{nome_relacao}."
        )

    problemas = {
        chave: valor
        for chave, valor in validacao.items()
        if (
            chave != "total_linhas"
            and valor != 0
        )
    }

    if problemas:
        raise RuntimeError(
            f"Falha na validação de "
            f"{nome_relacao}: {problemas}"
        )

    return validacao


def processar_base_separada(
    conexao: duckdb.DuckDBPyConnection,
    ano: int,
    uf: str,
    base: str,
    variaveis_catalogo: List[str],
    arquivo_csv: Optional[Path],
    codificacao: str,
    reutilizar_silver: bool,
) -> Tuple[Dict[str, object], str]:
    """
    Processa ou reutiliza uma das bases separadas.

    Retorna:
    - informações do processamento;
    - nome da relação DuckDB validada.
    """
    base = base.strip().lower()

    if base not in BASES_SEPARADAS:
        raise ValueError(
            f"Base inválida: {base}"
        )

    identificador = BASES_SEPARADAS[
        base
    ]

    destino = (
        construir_caminho_parquet_separado(
            ano=ano,
            uf=uf,
            base=base,
        )
    )

    # -----------------------------------------
    # Reutilização de Parquet existente
    # -----------------------------------------
    if destino.exists():
        if not reutilizar_silver:
            raise FileExistsError(
                f"O arquivo já existe: {destino}"
            )

        nome_view_existente = (
            f"{base}_{ano}_silver"
        )

        view_existente_sql = (
            citar_identificador(
                nome_view_existente
            )
        )

        caminho_sql = escapar_texto_sql(
            str(destino)
        )

        conexao.execute(
            f"""
            CREATE TEMP VIEW
                {view_existente_sql} AS

            SELECT *
            FROM read_parquet(
                '{caminho_sql}'
            )
            """
        )

        colunas_existentes = (
            obter_colunas_view(
                conexao=conexao,
                nome_view=nome_view_existente,
            )
        )

        coluna_uf = obter_coluna_uf(
            ano=ano,
            colunas_disponiveis=(
                colunas_existentes
            ),
        )

        validacao = validar_base_separada(
            conexao=conexao,
            nome_relacao=nome_view_existente,
            ano=ano,
            uf=uf,
            coluna_uf=coluna_uf,
            identificador=identificador,
        )

        return (
            {
                "base": base,
                "status": "reutilizado",
                "identificador": identificador,
                "coluna_uf": coluna_uf,
                "total_colunas": len(
                    colunas_existentes
                ),
                **validacao,
                "arquivo": destino,
                "tamanho_mb": (
                    destino.stat().st_size
                    / 1024**2
                ),
            },
            nome_view_existente,
        )

    # -----------------------------------------
    # Processamento a partir do CSV
    # -----------------------------------------
    if arquivo_csv is None:
        raise FileNotFoundError(
            f"CSV da base {base} não informado."
        )

    nome_view_raw = (
        f"{base}_{ano}_raw"
    )

    criar_view_csv(
        conexao=conexao,
        arquivo_csv=arquivo_csv,
        nome_view=nome_view_raw,
        codificacao=codificacao,
    )

    colunas_disponiveis = (
        obter_colunas_view(
            conexao=conexao,
            nome_view=nome_view_raw,
        )
    )

    variaveis_base = [
        variavel
        for variavel in variaveis_catalogo
        if variavel in colunas_disponiveis
    ]

    if identificador not in variaveis_base:
        raise KeyError(
            f"{identificador} não foi selecionada "
            f"para a base {base}."
        )

    nome_view_estado = (
        f"{base}_{ano}_{uf.lower()}"
    )

    coluna_uf = criar_view_estado(
        conexao=conexao,
        nome_view_origem=nome_view_raw,
        nome_view_destino=nome_view_estado,
        variaveis=variaveis_base,
        ano=ano,
        uf=uf,
    )

    nome_tabela_validada = (
        f"{base}_{ano}_{uf.lower()}_validado"
    )

    tabela_validada_sql = (
        citar_identificador(
            nome_tabela_validada
        )
    )

    view_estado_sql = (
        citar_identificador(
            nome_view_estado
        )
    )

    conexao.execute(
        f"""
        CREATE TEMP TABLE
            {tabela_validada_sql} AS

        SELECT *
        FROM {view_estado_sql}
        """
    )

    validacao = validar_base_separada(
        conexao=conexao,
        nome_relacao=nome_tabela_validada,
        ano=ano,
        uf=uf,
        coluna_uf=coluna_uf,
        identificador=identificador,
    )

    arquivo = gravar_parquet_separado(
        conexao=conexao,
        nome_view=nome_tabela_validada,
        ano=ano,
        uf=uf,
        base=base,
    )

    return (
        {
            "base": base,
            "status": "processado",
            "identificador": identificador,
            "coluna_uf": coluna_uf,
            "total_colunas": len(
                variaveis_base
            ),
            **validacao,
            "arquivo": arquivo,
            "tamanho_mb": (
                arquivo.stat().st_size
                / 1024**2
            ),
        },
        nome_tabela_validada,
    )


def validar_correspondencia_municipal(
    conexao: duckdb.DuckDBPyConnection,
    relacao_participantes: str,
    relacao_resultados: str,
) -> Dict[str, int]:
    """
    Compara as contagens das duas bases por município.

    Esta validação não estabelece relação individual.
    """
    participantes_sql = (
        citar_identificador(
            relacao_participantes
        )
    )

    resultados_sql = citar_identificador(
        relacao_resultados
    )

    resultado = conexao.execute(
        f"""
        WITH participantes AS (
            SELECT
                NU_ANO,
                CO_MUNICIPIO_PROVA,
                COUNT(*) AS total_participantes

            FROM {participantes_sql}

            GROUP BY
                NU_ANO,
                CO_MUNICIPIO_PROVA
        ),

        resultados AS (
            SELECT
                NU_ANO,
                CO_MUNICIPIO_PROVA,
                COUNT(*) AS total_resultados

            FROM {resultados_sql}

            GROUP BY
                NU_ANO,
                CO_MUNICIPIO_PROVA
        ),

        comparacao AS (
            SELECT
                COALESCE(
                    p.NU_ANO,
                    r.NU_ANO
                ) AS NU_ANO,

                COALESCE(
                    p.CO_MUNICIPIO_PROVA,
                    r.CO_MUNICIPIO_PROVA
                ) AS CO_MUNICIPIO_PROVA,

                p.total_participantes,
                r.total_resultados

            FROM participantes AS p

            FULL OUTER JOIN resultados AS r
                ON p.NU_ANO = r.NU_ANO
               AND p.CO_MUNICIPIO_PROVA
                   = r.CO_MUNICIPIO_PROVA
        )

        SELECT
            COUNT(*) AS municipios_total,

            COUNT(*) FILTER (
                WHERE total_participantes
                      IS DISTINCT FROM
                      total_resultados
            ) AS municipios_com_diferenca,

            COALESCE(
                SUM(
                    ABS(
                        COALESCE(
                            total_resultados,
                            0
                        )
                        - COALESCE(
                            total_participantes,
                            0
                        )
                    )
                ),
                0
            ) AS diferenca_absoluta_total

        FROM comparacao
        """
    ).fetchone()

    return {
        "municipios_total": int(
            resultado[0]
        ),
        "municipios_com_diferenca": int(
            resultado[1]
        ),
        "diferenca_absoluta_total": int(
            resultado[2]
        ),
    }


def processar_ano_separado(
    ano: int,
    uf: str,
    catalogo: pd.DataFrame,
    reutilizar_silver: bool = True,
) -> Dict[str, object]:
    """
    Processa participantes e resultados separadamente.
    """
    if ano < 2024:
        raise ValueError(
            "O processamento separado é válido "
            "somente a partir de 2024."
        )

    uf = uf.strip().upper()

    conexao = criar_conexao()

    try:
        variaveis_catalogo = (
            obter_variaveis_ano(
                ano=ano,
                catalogo=catalogo,
            )
        )

        destinos = {
            base: (
                construir_caminho_parquet_separado(
                    ano=ano,
                    uf=uf,
                    base=base,
                )
            )
            for base in BASES_SEPARADAS
        }

        arquivos_por_base = {
            "participantes": None,
            "resultados": None,
        }

        # Extrai apenas quando alguma Silver está ausente.
        if not all(
            destino.exists()
            for destino in destinos.values()
        ):
            arquivos_csv = (
                extrair_csvs_principais(
                    ano=ano,
                    reutilizar_existentes=True,
                )
            )

            for arquivo in arquivos_csv:
                nome = arquivo.name.upper()

                if "PARTICIPANTES" in nome:
                    arquivos_por_base[
                        "participantes"
                    ] = arquivo

                elif "RESULTADOS" in nome:
                    arquivos_por_base[
                        "resultados"
                    ] = arquivo

        codificacao = (
            CODIFICACAO_MICRODADOS_POR_ANO.get(
                ano,
                CODIFICACAO_MICRODADOS_PADRAO,
            )
        )

        participantes, relacao_participantes = (
            processar_base_separada(
                conexao=conexao,
                ano=ano,
                uf=uf,
                base="participantes",
                variaveis_catalogo=(
                    variaveis_catalogo
                ),
                arquivo_csv=(
                    arquivos_por_base[
                        "participantes"
                    ]
                ),
                codificacao=codificacao,
                reutilizar_silver=(
                    reutilizar_silver
                ),
            )
        )

        resultados, relacao_resultados = (
            processar_base_separada(
                conexao=conexao,
                ano=ano,
                uf=uf,
                base="resultados",
                variaveis_catalogo=(
                    variaveis_catalogo
                ),
                arquivo_csv=(
                    arquivos_por_base[
                        "resultados"
                    ]
                ),
                codificacao=codificacao,
                reutilizar_silver=(
                    reutilizar_silver
                ),
            )
        )

        correspondencia = (
            validar_correspondencia_municipal(
                conexao=conexao,
                relacao_participantes=(
                    relacao_participantes
                ),
                relacao_resultados=(
                    relacao_resultados
                ),
            )
        )

        statuses = {
            participantes["status"],
            resultados["status"],
        }

        if statuses == {"reutilizado"}:
            status = "reutilizado"

        elif statuses == {"processado"}:
            status = "processado"

        else:
            status = "parcial"

        return {
            "ano": ano,
            "uf": uf,
            "status": status,
            "layout": "separado",
            "total_linhas": None,
            "total_participantes": (
                participantes[
                    "total_linhas"
                ]
            ),
            "total_resultados": (
                resultados[
                    "total_linhas"
                ]
            ),
            "participantes": participantes,
            "resultados": resultados,
            "correspondencia_municipal": (
                correspondencia
            ),
        }

    finally:
        conexao.close()