#catalogo.py
"""
Módulo de leitura e consulta do catálogo de variáveis do ENEM.

Este módulo utiliza o arquivo `variaveis_enem_por_ano.csv` para
identificar quais variáveis foram selecionadas e estão disponíveis
em cada edição do ENEM entre 1998 e 2025.

As rotinas removem células vazias, títulos de seção e eventuais
duplicações, preservando a ordem original das variáveis no catálogo.

Responsabilidades:
- carregar o catálogo de variáveis;
- validar a existência do arquivo e do ano solicitado;
- distinguir nomes de variáveis de títulos de seção;
- retornar a lista de variáveis correspondente a cada edição.

Este módulo reflete a estrutura original de cada ano. Ele não cria
variáveis ausentes, não converte tipos e não realiza harmonização
temporal. Essas operações pertencem à etapa de transformação.
"""
import sys

from pathlib import Path
from typing import Optional

import pandas as pd
from .config import CATALOGO_VARIAVEIS

from .config import (CATALOGO_VARIAVEIS,SEPARADOR_CATALOGO)

def carregar_catalogo(
    caminho: Path = CATALOGO_VARIAVEIS,
) -> pd.DataFrame:
    """
    Carrega o catálogo de variáveis do ENEM.
    """
    if not caminho.exists():
        raise FileNotFoundError(
            f"Catálogo não encontrado: {caminho}"
        )

    catalogo = pd.read_csv(
        caminho,
        sep=SEPARADOR_CATALOGO,
        dtype="string",
    )
    return catalogo


def nome_valido_variavel(valor: str) -> bool:
    """
    Identifica se uma célula contém uma variável,
    descartando títulos e células auxiliares.
    """
    valor = valor.strip()

    if not valor:
        return False

    if valor.upper().startswith("VARIÁVEIS "):
        return False

    if valor.lower() == "nome da variável":
        return False

    return True


def obter_variaveis_ano(
    ano: int,
    catalogo: Optional[pd.DataFrame] = None,
) -> list[str]:
    """
    Retorna as variáveis selecionadas para uma edição.
    """
    if catalogo is None:
        catalogo = carregar_catalogo()

    coluna_ano = str(ano)

    if coluna_ano not in catalogo.columns:
        raise KeyError(
            f"O ano {ano} não existe no catálogo."
        )

    valores = (
        catalogo[coluna_ano]
        .dropna()
        .str.strip()
        .tolist()
    )

    variaveis = [
        valor
        for valor in valores
        if nome_valido_variavel(valor)
    ]

    variaveis = list(
        dict.fromkeys(variaveis)
    )

    return variaveis