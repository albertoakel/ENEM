#processamento.py
"""
Orquestração do processamento anual dos microdados do ENEM.

Fluxo executado:
1. consulta o catálogo;
2. extrai os CSVs principais;
3. cria a view DuckDB;
4. une participantes e resultados quando necessário;
5. filtra a UF;
6. converte os tipos;
7. materializa e valida os dados;
8. grava o Parquet na camada Silver.
9. grava o Parquet na camada Silver.

"""

from pathlib import Path
from typing import Dict

import pandas as pd
from .config import (
    CODIFICACAO_MICRODADOS_PADRAO,
    CODIFICACAO_MICRODADOS_POR_ANO,
)
from .catalogo import obter_variaveis_ano
from .extracao import extrair_csvs_principais
from .gravacao import (
    construir_caminho_parquet,
    contar_registros_parquet,
    gravar_parquet,
)
from .leitura import (
    citar_identificador,
    criar_conexao,
    criar_view_arquivos_principais,
    escapar_texto_sql,
    obter_colunas_view,
    validar_layout_separado,
)

from .transformacao import (
    criar_view_estado,
    obter_coluna_uf,
)

from collections.abc import Iterable

def validar_tabela_processada(
    conexao,
    nome_tabela: str,
    ano: int,
    uf: str,
    coluna_uf: str,
) -> Dict[str, int]:

    """
    Valida quantidade, inscrições, UF e ano.
    """
    tabela_sql = citar_identificador(nome_tabela)

    coluna_uf_sql = citar_identificador(coluna_uf)

    uf_sql = escapar_texto_sql(uf.strip().upper())

    resultado = conexao.execute(
        f"""
        SELECT
            COUNT(*) AS total_linhas,

            COUNT(*) - COUNT(
                DISTINCT NU_INSCRICAO
            ) AS duplicacoes,

            COUNT(*) FILTER (
                WHERE {coluna_uf_sql} IS NULL
                   OR UPPER(
                       TRIM({coluna_uf_sql})
                   ) <> '{uf_sql}'
            ) AS outras_ufs,

            COUNT(*) FILTER (
                WHERE NU_ANO IS NULL
                   OR NU_ANO <> {int(ano)}
            ) AS anos_invalidos

        FROM {tabela_sql}
        """
    ).fetchone()

    validacao = {
        "total_linhas": int(resultado[0]),
        "duplicacoes": int(resultado[1]),
        "outras_ufs": int(resultado[2]),
        "anos_invalidos": int(resultado[3]),
    }

    if validacao["total_linhas"] == 0:
        raise RuntimeError(
            f"Nenhum registro encontrado para {uf} em {ano}."
        )

    problemas = {
        chave: valor
        for chave, valor in validacao.items()
        if chave != "total_linhas" and valor != 0
    }

    if problemas:
        raise RuntimeError(
            f"Falha na validação de {ano}: {problemas}"
        )

    return validacao


def processar_ano(
    ano: int,
    uf: str,
    catalogo: pd.DataFrame,
    reutilizar_silver: bool = True,
) -> Dict[str, object]:
    """
    Executa o processamento completo de uma edição.
    """
    uf = uf.strip().upper()

    # -----------------------------------------
    # processamento para anos >=2024
    # -----------------------------------------
    if ano >= 2024:

        from .processamento_separado import (
            processar_ano_separado,
        )

        return processar_ano_separado(
            ano=ano,
            uf=uf,
            catalogo=catalogo,
            reutilizar_silver=(
                reutilizar_silver
            ),
        )

    destino = construir_caminho_parquet(
        ano=ano,
        uf=uf,
    )

    conexao = criar_conexao()

    try:
        # -----------------------------------------
        # Reutilização de uma Silver já existente
        # -----------------------------------------
        if destino.exists():
            if not reutilizar_silver:
                raise FileExistsError(
                    f"O arquivo já existe: {destino}"
                )

            nome_view_existente = (
                f"enem_{ano}_{uf.lower()}_silver"
            )

            view_existente_sql = citar_identificador(
                nome_view_existente
            )

            caminho_parquet_sql = escapar_texto_sql(
                str(destino)
            )

            conexao.execute(
                f"""
                CREATE TEMP VIEW
                    {view_existente_sql} AS

                SELECT *
                FROM read_parquet(
                    '{caminho_parquet_sql}'
                )
                """
            )

            colunas_existentes = obter_colunas_view(
                conexao=conexao,
                nome_view=nome_view_existente,
            )

            coluna_uf = obter_coluna_uf(
                ano=ano,
                colunas_disponiveis=colunas_existentes,
            )

            validacao = validar_tabela_processada(
                conexao=conexao,
                nome_tabela=nome_view_existente,
                ano=ano,
                uf=uf,
                coluna_uf=coluna_uf,
            )

            return {
                "ano": ano,
                "uf": uf,
                "status": "reutilizado",
                "layout": "unico",
                "validacao_layout": None,
                **validacao,
                "arquivo": destino,
                "tamanho_mb": (
                        destino.stat().st_size / 1024 ** 2
                ),
            }

        variaveis = obter_variaveis_ano(
            ano=ano,
            catalogo=catalogo,
        )

        arquivos_csv = extrair_csvs_principais(
            ano=ano,
            reutilizar_existentes=True,
        )

        nome_view_raw = f"enem_{ano}_raw"

        codificacao_csv = (
            CODIFICACAO_MICRODADOS_POR_ANO.get(
                ano,
                CODIFICACAO_MICRODADOS_PADRAO,
            )
        )

        layout = criar_view_arquivos_principais(
            conexao=conexao,
            arquivos_csv=arquivos_csv,
            nome_view=nome_view_raw,
            codificacao=codificacao_csv,
        )
        # -----------------------------------------
        # Validação do layout separado
        # -----------------------------------------
        validacao_layout = None

        if layout == "separado":
            validacao_layout = validar_layout_separado(
                conexao=conexao,
                nome_view_base=nome_view_raw,
            )

            campos_invalidos = {
                chave: valor
                for chave, valor
                in validacao_layout.items()
                if (
                        chave
                        not in {
                            "total_participantes",
                            "total_resultados",
                        }
                        and valor != 0
                )
            }

            totais_divergentes = (
                    validacao_layout[
                        "total_participantes"
                    ]
                    != validacao_layout[
                        "total_resultados"
                    ]
            )

            if campos_invalidos or totais_divergentes:
                raise RuntimeError(
                    "Relacionamento inválido entre "
                    "participantes e resultados: "
                    f"{validacao_layout}"
                )

        # -----------------------------------------
        # Criação da view filtrada e tipada
        # -----------------------------------------
        nome_view_estado = (
            f"enem_{ano}_{uf.lower()}"
        )

        coluna_uf = criar_view_estado(
            conexao=conexao,
            nome_view_origem=nome_view_raw,
            nome_view_destino=nome_view_estado,
            variaveis=variaveis,
            ano=ano,
            uf=uf,
 )

        # -----------------------------------------
        # Materialização das transformações
        # -----------------------------------------
        nome_tabela_validada = (
            f"enem_{ano}_{uf.lower()}_validado"
        )

        tabela_validada_sql = citar_identificador(
            nome_tabela_validada
        )

        view_estado_sql = citar_identificador(
            nome_view_estado
        )

        conexao.execute(
            f"""
            CREATE TEMP TABLE
                {tabela_validada_sql} AS

            SELECT *
            FROM {view_estado_sql}
            """
        )

        # -----------------------------------------
        # Validação dos dados transformados
        # -----------------------------------------
        validacao = validar_tabela_processada(
            conexao=conexao,
            nome_tabela=nome_tabela_validada,
            ano=ano,
            uf=uf,
            coluna_uf=coluna_uf,
        )

        # -----------------------------------------
        # Gravação do Parquet
        # -----------------------------------------
        arquivo = gravar_parquet(
            conexao=conexao,
            nome_view=nome_tabela_validada,
            ano=ano,
            uf=uf,
        )

        return {
            "ano": ano,
            "uf": uf,
            "status": "processado",
            "layout": layout,
            "validacao_layout": validacao_layout,
            **validacao,
            "arquivo": arquivo,
            "tamanho_mb": (
                arquivo.stat().st_size / 1024**2
            ),
        }

    finally:
        conexao.close()

#-------------------------
def processar_varios_anos(
    anos: Iterable[int],
    uf: str,
    catalogo: pd.DataFrame,
    reutilizar_silver: bool = True,
    continuar_em_erro: bool = False,
    limpar_staging_apos_sucesso: bool = False,
) -> pd.DataFrame:
    """
    Processa várias edições sequencialmente.

    Se limpar_staging_apos_sucesso=True, remove os CSVs
    principais do staging depois que a Silver estiver
    gravada e validada.
    """
    anos = list(
        dict.fromkeys(anos)
    )

    if not anos:
        raise ValueError(
            "Nenhum ano foi informado."
        )

    resultados = []

    for posicao, ano in enumerate(
        anos,
        start=1,
    ):
        print(
            f"[{posicao}/{len(anos)}] "
            f"Processando {ano}..."
        )

        try:
            resultado = processar_ano(
                ano=ano,
                uf=uf,
                catalogo=catalogo,
                reutilizar_silver=(
                    reutilizar_silver
                ),
            )

        except Exception as erro:
            resultado = {
                "ano": ano,
                "uf": uf.strip().upper(),
                "status": "erro",
                "layout": None,
                "total_linhas": None,
                "total_participantes": None,
                "total_resultados": None,
                "participantes": None,
                "resultados": None,
                "correspondencia_municipal": None,
                "arquivo": None,
                "tamanho_mb": None,
                "erro": (
                    f"{type(erro).__name__}: "
                    f"{erro}"
                ),
                "staging_liberado_mb": 0.0,
                "erro_limpeza": None,
            }

            print(
                f"  erro: {resultado['erro']}"
            )

            resultados.append(
                resultado
            )

            if not continuar_em_erro:
                raise

            continue

        resultado["erro"] = None
        resultado["staging_liberado_mb"] = 0.0
        resultado["erro_limpeza"] = None

        if resultado["layout"] == "separado":
            print(
                f"  {resultado['status']}: "
                f"{resultado['total_participantes']:,} "
                "participantes | "
                f"{resultado['total_resultados']:,} "
                "resultados."
            )

        else:
            print(
                f"  {resultado['status']}: "
                f"{resultado['total_linhas']:,} "
                "registros."
            )

        if limpar_staging_apos_sucesso:
            try:
                from .limpeza import (
                    limpar_staging_ano,
                )

                limpeza = limpar_staging_ano(
                    ano=ano,
                    uf=uf,
                    simular=False,
                )

                espaco_liberado = float(
                    limpeza["espaco_mb"]
                )

                resultado[
                    "staging_liberado_mb"
                ] = espaco_liberado

                print(
                    f"  staging: "
                    f"{espaco_liberado:.2f} MB "
                    "liberados."
                )

            except Exception as erro_limpeza:
                mensagem_limpeza = (
                    f"{type(erro_limpeza).__name__}: "
                    f"{erro_limpeza}"
                )

                resultado[
                    "erro_limpeza"
                ] = mensagem_limpeza

                print(
                    f"  erro na limpeza: "
                    f"{mensagem_limpeza}"
                )

                resultados.append(
                    resultado
                )

                if not continuar_em_erro:
                    raise

                continue

        resultados.append(
            resultado
        )

    return pd.DataFrame(
        resultados
    )