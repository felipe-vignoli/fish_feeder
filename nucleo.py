#!/usr/bin/env python3
"""
Nucleo do alimentador — roda NO RASPBERRY PI.

Reune o que servidor.py e agenda.py precisam em comum: onde ficam os arquivos
do projeto, como ler/gravar config.json e os outros .json, o registro no log,
a trava que impede dois acionamentos ao mesmo tempo, e a funcao executar(),
que de fato aciona o motor e a camera reaproveitando as funcoes de
vibra_e_fotografa.py.
"""

from __future__ import annotations

import fcntl
import json
from datetime import datetime
from pathlib import Path

import vibra_e_fotografa as vf

BASE = Path(__file__).resolve().parent
PASTA_FOTOS = BASE / "fotos"
CONFIG = BASE / "config.json"
AGENDA = BASE / "agenda.json"
HISTORICO = BASE / "historico.json"
LOG = BASE / "alimentador.log"
TRAVA = BASE / "alimentador.lock"

CONFIG_PADRAO = {
    "pino": vf.PINO_PADRAO,
    "frequencia": 1000,
    "resolucao": "1296x972",
    "ativo_baixo": False,
    "aquecimento": 0.5,
    "pwm": 80.0,
    "duracao": 1.0,
    "fotos": 5,
    "intervalo": 2.0,
    "pasta": "fotos",
    "sem_camera": False,
    "sem_motor": False,
    "pasta_download_local": "",
    "padroes": {"pwm": 80.0, "duracao": 1.0, "fotos": 5, "intervalo": 2.0},
    "ssh": {"host": "", "usuario": "", "porta": 22, "senha": ""},
}


# --------------------------------------------------------------------------
def anotar(mensagem: str) -> None:
    """Grava uma linha com hora no log do painel (e imprime no terminal)."""
    linha = f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {mensagem}"
    with LOG.open("a", encoding="utf-8") as f:
        f.write(linha + "\n")
    print(linha)


def carregar_json(caminho: Path, padrao):
    try:
        with caminho.open("r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return padrao


def salvar_json(caminho: Path, dados) -> None:
    caminho.write_text(json.dumps(dados, ensure_ascii=False, indent=2), encoding="utf-8")


def carregar_config() -> dict:
    """Le config.json, criando com os padroes na primeira vez."""
    cfg = carregar_json(CONFIG, None)
    if cfg is None:
        cfg = json.loads(json.dumps(CONFIG_PADRAO))  # copia profunda
        salvar_json(CONFIG, cfg)
        return cfg
    mudou = False
    for chave, valor in CONFIG_PADRAO.items():
        if chave not in cfg:
            cfg[chave] = valor
            mudou = True
    if mudou:
        salvar_json(CONFIG, cfg)
    return cfg


def salvar_config(cfg: dict) -> None:
    salvar_json(CONFIG, cfg)


def normalizar(dados: dict) -> dict:
    """Extrai pwm/duracao/fotos/intervalo (e modo, se vier) de um dict solto."""
    padroes = CONFIG_PADRAO["padroes"]
    saida = {
        "pwm": float(dados.get("pwm", padroes["pwm"])),
        "duracao": float(dados.get("duracao", padroes["duracao"])),
        "fotos": int(dados.get("fotos", padroes["fotos"])),
        "intervalo": float(dados.get("intervalo", padroes["intervalo"])),
    }
    if "modo" in dados:
        saida["modo"] = dados["modo"]
    return saida


# --------------------------------------------------------------------------
def _rodar(parametros: dict, origem: str) -> dict:
    cfg = carregar_config()
    p = normalizar(parametros)
    modo = p.pop("modo", parametros.get("modo", "alimentacao"))
    usar_motor = modo != "foto"

    camera = None
    if not cfg.get("sem_camera") and p["fotos"] > 0:
        camera = vf.abrir_camera(vf.resolucao(cfg.get("resolucao", "1296x972")),
                                 float(cfg.get("aquecimento", 0.5)))

    inicio = datetime.now()
    arquivos = []
    try:
        if usar_motor:
            vf.vibrar(int(cfg.get("pino", vf.PINO_PADRAO)), p["duracao"],
                     bool(cfg.get("ativo_baixo", False)), p["pwm"],
                     int(cfg.get("frequencia", 1000)))
        if camera is not None:
            arquivos = vf.fotografar(camera, p["fotos"], p["intervalo"], PASTA_FOTOS)
    finally:
        if camera is not None:
            camera.stop()
            camera.close()

    resultado = {
        "id": inicio.strftime("s%Y%m%d%H%M%S%f"),
        "inicio": inicio.isoformat(timespec="seconds"),
        "fim": datetime.now().isoformat(timespec="seconds"),
        "modo": modo,
        "origem": origem,
        "pasta": str(PASTA_FOTOS),
        "arquivos": [a.name for a in arquivos],
        "parametros": {**p, "pino": cfg.get("pino"), "resolucao": cfg.get("resolucao")},
    }

    hist = carregar_json(HISTORICO, [])
    hist.append(resultado)
    salvar_json(HISTORICO, hist[-200:])  # nao deixa o historico crescer para sempre
    anotar(f"{modo} concluida ({origem}): {len(resultado['arquivos'])} foto(s)")
    return resultado


def executar(parametros: dict, origem: str = "desconhecido") -> dict:
    """Executa uma alimentacao/foto, garantindo que so uma rode por vez."""
    TRAVA.touch(exist_ok=True)
    with TRAVA.open("r+") as f:
        try:
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError("ja tem um acionamento em andamento, espere terminar")
        try:
            return _rodar(parametros, origem)
        except Exception as e:
            anotar(f"falha ao executar ({origem}): {e}")
            raise
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)
