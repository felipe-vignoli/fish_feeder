#!/usr/bin/env python3
"""
Agenda do alimentador — roda NO RASPBERRY PI.

Guarda os agendamentos em agenda.json e traduz cada um para uma linha no
crontab do usuario, dentro de um bloco proprio:

    # inicio fish_feeder
    30 8 * * 1,3 /usr/bin/python3 /home/pi/Documents/fish_feeder/agenda.py disparar ag123
    # fim fish_feeder

Nada fora desse bloco e tocado, entao o resto do seu crontab continua intacto.
A linha do cron so chama `disparar`: a decisao de acionar ou nao (agendamento
desativado, data que ja passou) fica aqui no Python.

Uso:
    python3 agenda.py listar
    python3 agenda.py aplicar          # regrava o bloco no crontab
    python3 agenda.py limpar           # remove o bloco do crontab
    python3 agenda.py disparar ag123   # o que o cron executa
    python3 agenda.py agora ag123      # dispara ignorando dia/hora, para testar
"""

from __future__ import annotations

import subprocess
import sys
from datetime import date, datetime

import nucleo
from nucleo import AGENDA, BASE, LOG, anotar, carregar_json, normalizar, salvar_json

INICIO = "# inicio fish_feeder"
FIM = "# fim fish_feeder"

# nomes usados na tela -> numero do dia da semana no cron (0 = domingo)
DIAS = {"dom": 0, "seg": 1, "ter": 2, "qua": 3, "qui": 4, "sex": 5, "sab": 6}


# --------------------------------------------------------------------------
def listar() -> list:
    return carregar_json(AGENDA, [])


def gravar(itens: list) -> None:
    salvar_json(AGENDA, itens)


def novo(dados: dict) -> dict:
    item = {
        "id": datetime.now().strftime("ag%Y%m%d%H%M%S%f"),
        "nome": (dados.get("nome") or "").strip(),
        "hora": dados.get("hora") or "08:00",
        "tipo": "datas" if dados.get("tipo") == "datas" else "semanal",
        "dias": [d for d in dados.get("dias", []) if d in DIAS],
        "datas": sorted(set(dados.get("datas", []))),
        "ativo": True,
        "parametros": normalizar(dados.get("parametros", dados)),
    }
    itens = listar()
    itens.append(item)
    gravar(itens)
    aplicar()
    return item


def remover(ident: str) -> None:
    gravar([a for a in listar() if a["id"] != ident])
    aplicar()


def alternar(ident: str, ativo: bool) -> None:
    itens = listar()
    for a in itens:
        if a["id"] == ident:
            a["ativo"] = bool(ativo)
    gravar(itens)
    aplicar()


# --------------------------------------------------------------------------
def ler_crontab() -> str:
    r = subprocess.run(["crontab", "-l"], capture_output=True, text=True)
    return r.stdout if r.returncode == 0 else ""


def escrever_crontab(texto: str) -> None:
    if not texto.endswith("\n"):
        texto += "\n"
    r = subprocess.run(["crontab", "-"], input=texto, text=True, capture_output=True)
    if r.returncode != 0:
        raise RuntimeError(f"crontab recusou: {r.stderr.strip()}")


def sem_bloco(texto: str) -> list:
    linhas, dentro, fora = texto.splitlines(), False, []
    for l in linhas:
        if l.strip() == INICIO:
            dentro = True
            continue
        if l.strip() == FIM:
            dentro = False
            continue
        if not dentro:
            fora.append(l)
    while fora and not fora[-1].strip():
        fora.pop()
    return fora


def linhas_do_agendamento(a: dict) -> list:
    hora, minuto = a["hora"].split(":")
    minuto, hora = int(minuto), int(hora)
    cmd = (f"cd {BASE} && {sys.executable} {BASE / 'agenda.py'} disparar {a['id']} "
           f">> {LOG} 2>&1")
    saida = []

    if a["tipo"] == "datas":
        hoje = date.today()
        quando = set()
        for d in a.get("datas", []):
            try:
                dia = date.fromisoformat(d)
            except ValueError:
                continue
            if dia >= hoje:
                quando.add((dia.day, dia.month))
        for dia, mes in sorted(quando):
            saida.append(f"{minuto} {hora} {dia} {mes} * {cmd}")
    else:
        dias = sorted({DIAS[d] for d in a.get("dias", []) if d in DIAS})
        if dias:
            saida.append(f"{minuto} {hora} * * {','.join(str(d) for d in dias)} {cmd}")
    return saida


def aplicar() -> str:
    """Regrava o bloco fish_feeder no crontab a partir do agenda.json."""
    corpo = []
    for a in listar():
        if a.get("ativo", True):
            corpo += linhas_do_agendamento(a)

    fora = sem_bloco(ler_crontab())
    novo_texto = "\n".join(fora)
    if corpo:
        if novo_texto:
            novo_texto += "\n\n"
        novo_texto += "\n".join([INICIO] + corpo + [FIM])
    escrever_crontab(novo_texto)
    anotar(f"crontab atualizado: {len(corpo)} linha(s)")
    return "\n".join(corpo)


def limpar() -> None:
    escrever_crontab("\n".join(sem_bloco(ler_crontab())))
    anotar("bloco do alimentador removido do crontab")


def bloco_atual() -> str:
    texto, dentro, dentro_linhas = ler_crontab(), False, []
    for l in texto.splitlines():
        if l.strip() == INICIO:
            dentro = True
            continue
        if l.strip() == FIM:
            break
        if dentro:
            dentro_linhas.append(l)
    return "\n".join(dentro_linhas)


# --------------------------------------------------------------------------
def disparar(ident: str, forcar: bool = False) -> int:
    a = next((x for x in listar() if x["id"] == ident), None)
    if a is None:
        anotar(f"agendamento {ident} nao existe mais")
        return 1
    if not forcar:
        if not a.get("ativo", True):
            anotar(f"{ident} esta desativado")
            return 0
        if a["tipo"] == "datas" and date.today().isoformat() not in a.get("datas", []):
            return 0          # a linha do cron repete todo ano; a data manda
    nome = a.get("nome") or a["hora"]
    try:
        nucleo.executar(a["parametros"], origem=f"agenda/{nome}")
    except Exception as e:
        anotar(f"agenda falhou: {e}")
        return 1
    return 0


def main() -> int:
    cmd = sys.argv[1] if len(sys.argv) > 1 else "listar"
    if cmd == "listar":
        for a in listar():
            quando = (", ".join(a["datas"]) if a["tipo"] == "datas"
                      else " ".join(a["dias"]))
            marca = "ativo   " if a.get("ativo", True) else "desligado"
            print(f"{marca}  {a['hora']}  {a.get('nome') or a['id']}  ({quando})")
        print("\nno crontab agora:\n" + (bloco_atual() or "  (vazio)"))
        return 0
    if cmd == "aplicar":
        print(aplicar() or "(nenhuma linha)")
        return 0
    if cmd == "limpar":
        limpar()
        return 0
    if cmd in ("disparar", "agora"):
        if len(sys.argv) < 3:
            sys.exit("informe o id do agendamento")
        return disparar(sys.argv[2], forcar=(cmd == "agora"))
    sys.exit(f"comando desconhecido: {cmd}")


if __name__ == "__main__":
    sys.exit(main())
