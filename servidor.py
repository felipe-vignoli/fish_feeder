#!/usr/bin/env python3
"""
Painel do alimentador — roda NO RASPBERRY PI.

Sobe um servidor HTTP na rede local. O computador (ou qualquer aparelho da
casa) so abre o navegador em http://<ip-do-pi>:8765 e configura daqui.

    pip install flask
    python3 servidor.py
"""

from __future__ import annotations

import fcntl
import os
import re
import socket
import subprocess
from pathlib import Path

from flask import Flask, abort, jsonify, request, send_from_directory

import agenda as ag
import nucleo
from nucleo import (BASE, LOG, PASTA_FOTOS, anotar, carregar_config,
                    carregar_json, HISTORICO, salvar_config)

PORTA = int(os.environ.get("FEEDER_PORT", 8765))
app = Flask(__name__, static_folder=None)


def ocupado() -> bool:
    if not nucleo.TRAVA.exists():
        return False
    try:
        with nucleo.TRAVA.open("r") as f:
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
            fcntl.flock(f, fcntl.LOCK_UN)
        return False
    except BlockingIOError:
        return True
    except OSError:
        return False


def seguro(nome: str) -> bool:
    return bool(re.fullmatch(r"[\w\-\.]+\.jpg", nome))


# --------------------------------------------------------------------------
@app.get("/")
def index():
    return send_from_directory(BASE, "index.html")


@app.get("/api/estado")
def estado():
    temp = ""
    try:
        temp = subprocess.run(["vcgencmd", "measure_temp"], capture_output=True,
                              text=True, timeout=5).stdout.strip().replace("temp=", "")
    except Exception:
        pass
    return jsonify({
        "ok": True,
        "host": socket.gethostname(),
        "temp": temp,
        "ocupado": ocupado(),
        "pasta": str(PASTA_FOTOS),
        "config": carregar_config(),
        "cron": ag.bloco_atual(),
    })


@app.get("/api/config")
def get_config():
    return jsonify(carregar_config())


@app.post("/api/config")
def set_config():
    novo = request.get_json(force=True) or {}
    cfg = carregar_config()
    for chave, tipo in (("pino", int), ("frequencia", int), ("aquecimento", float)):
        if chave in novo and str(novo[chave]).strip() != "":
            cfg[chave] = tipo(novo[chave])
    if "resolucao" in novo and re.fullmatch(r"\d+x\d+", str(novo["resolucao"]).strip()):
        cfg["resolucao"] = str(novo["resolucao"]).strip()
    if "ativo_baixo" in novo:
        cfg["ativo_baixo"] = bool(novo["ativo_baixo"])
    if "padroes" in novo:
        cfg["padroes"] = nucleo.normalizar(novo["padroes"])
        cfg["padroes"].pop("modo", None)
    salvar_config(cfg)
    anotar("configuracao salva pelo painel")
    return jsonify({"ok": True, "config": cfg})


@app.post("/api/acionar")
def acionar():
    corpo = request.get_json(force=True) or {}
    try:
        r = nucleo.executar(corpo, origem="painel")
        return jsonify({"ok": True, **r})
    except Exception as e:
        return jsonify({"ok": False, "erro": str(e)})


# --------------------------------------------------------------------------
@app.get("/api/sessoes")
def sessoes():
    PASTA_FOTOS.mkdir(parents=True, exist_ok=True)
    existentes = {f.name for f in PASTA_FOTOS.glob("*.jpg")}
    saida, usadas = [], set()

    for h in carregar_json(HISTORICO, []):
        fotos = [n for n in h.get("arquivos", []) if n in existentes]
        if not fotos:
            continue
        usadas.update(fotos)
        saida.append({
            "id": h["id"], "quando": h.get("inicio", ""), "modo": h.get("modo", ""),
            "origem": h.get("origem", ""), "parametros": h.get("parametros", {}),
            "fotos": [{"nome": n, "url": f"/fotos/{n}"} for n in fotos],
        })

    avulsas = sorted(existentes - usadas, reverse=True)
    if avulsas:
        saida.append({
            "id": "avulsas", "quando": "", "modo": "", "origem": "fora do painel",
            "parametros": {},
            "fotos": [{"nome": n, "url": f"/fotos/{n}"} for n in avulsas],
        })
    return jsonify({"pasta": str(PASTA_FOTOS), "sessoes": saida[:60]})


@app.get("/fotos/<nome>")
def foto(nome):
    if not seguro(nome):
        abort(404)
    return send_from_directory(PASTA_FOTOS, nome)


@app.delete("/api/sessoes/<ident>")
def apagar_sessao(ident):
    hist = carregar_json(HISTORICO, [])
    alvo = next((h for h in hist if h["id"] == ident), None)
    nomes = alvo["arquivos"] if alvo else []
    if ident == "avulsas":
        return jsonify({"ok": False, "erro": "apague as avulsas uma a uma"})
    for n in nomes:
        if seguro(n):
            (PASTA_FOTOS / n).unlink(missing_ok=True)
    nucleo.salvar_json(HISTORICO, [h for h in hist if h["id"] != ident])
    anotar(f"sessao {ident} apagada")
    return jsonify({"ok": True})


# --------------------------------------------------------------------------
@app.get("/api/agenda")
def get_agenda():
    return jsonify({"agendamentos": ag.listar(), "cron": ag.bloco_atual()})


@app.post("/api/agenda")
def add_agenda():
    item = ag.novo(request.get_json(force=True) or {})
    return jsonify({"ok": True, "agendamento": item})


@app.patch("/api/agenda/<ident>")
def patch_agenda(ident):
    corpo = request.get_json(force=True) or {}
    ag.alternar(ident, bool(corpo.get("ativo", True)))
    return jsonify({"ok": True})


@app.delete("/api/agenda/<ident>")
def del_agenda(ident):
    ag.remover(ident)
    return jsonify({"ok": True})


@app.post("/api/agenda/<ident>/testar")
def testar_agenda(ident):
    codigo = ag.disparar(ident, forcar=True)
    return jsonify({"ok": codigo == 0})


@app.get("/api/log")
def log():
    if not LOG.exists():
        return jsonify({"linhas": []})
    linhas = LOG.read_text(encoding="utf-8", errors="replace").splitlines()
    return jsonify({"linhas": linhas[-80:], "ocupado": ocupado()})


@app.errorhandler(Exception)
def erro(e):
    anotar(f"erro: {e}")
    return jsonify({"ok": False, "erro": str(e)}), 200


if __name__ == "__main__":
    PASTA_FOTOS.mkdir(parents=True, exist_ok=True)
    ip = socket.gethostbyname(socket.gethostname())
    print(f"\n  Painel do alimentador:  http://{ip}:{PORTA}"
          f"  ou  http://{socket.gethostname()}.local:{PORTA}\n")
    app.run(host="0.0.0.0", port=PORTA, threaded=True)
