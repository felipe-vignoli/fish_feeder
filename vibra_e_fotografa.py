#!/usr/bin/env python3
"""Aciona o motor de vibracao do alimentador e fotografa logo apos a vibracao.

Sequencia executada:
  1. abre e aquece a camera (para a primeira foto sair sem atraso);
  2. liga o motor pelo tempo escolhido;
  3. desliga o motor e tira as fotos no intervalo configurado.

Exemplos:
  python3 vibra_e_fotografa.py                  # vibra 1 s (padrao), 3 fotos de 1 em 1 s
  python3 vibra_e_fotografa.py -t 2.5           # vibra 2,5 s
  python3 vibra_e_fotografa.py -t 2 -i 0.33     # 3 fotos dentro de 1 segundo
  python3 vibra_e_fotografa.py -t 2 -n 5 -i 0.5 # 5 fotos, uma a cada 0,5 s
  python3 vibra_e_fotografa.py -w 60            # vibra a 60% da intensidade (PWM)
  python3 vibra_e_fotografa.py --json           # imprime o resultado em JSON no final

O painel web e a agenda chamam este mesmo arquivo, so mudando os argumentos.
"""

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path

from gpiozero import PWMOutputDevice

PINO_PADRAO = 18  # GPIO18 (BCM) = pino fisico 12
BASE = Path(__file__).resolve().parent
PASTA_PADRAO = BASE / "fotos"
MARCADOR = "###JSON###"


def argumentos():
    p = argparse.ArgumentParser(
        description="Vibra o motor por um tempo regulavel e tira fotos em seguida.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("-t", "--duracao", type=float, default=1.0,
                   help="tempo de vibracao em segundos (padrao: 1.0)")
    p.add_argument("-p", "--pino", type=int, default=PINO_PADRAO,
                   help="GPIO (numeracao BCM) ligado ao driver do motor")
    p.add_argument("-n", "--fotos", type=int, default=3,
                   help="quantidade de fotos apos a vibracao")
    p.add_argument("-i", "--intervalo", type=float, default=1.0,
                   help="intervalo entre as fotos, em segundos")
    p.add_argument("-w", "--pwm", type=float, default=100.0,
                   help="intensidade da vibracao, de 1 a 100 (PWM)")
    p.add_argument("-f", "--frequencia", type=int, default=1000,
                   help="frequencia do PWM em Hz")
    p.add_argument("-o", "--pasta", type=Path, default=PASTA_PADRAO,
                   help="pasta onde as fotos sao gravadas")
    p.add_argument("-r", "--resolucao", default="1296x972",
                   help="resolucao das fotos, no formato LARGURAxALTURA")
    p.add_argument("--ativo-baixo", action="store_true",
                   help="usar se o modulo rele/driver liga com nivel baixo")
    p.add_argument("--aquecimento", type=float, default=0.5,
                   help="tempo de ajuste automatico da camera antes de vibrar")
    p.add_argument("--sem-camera", action="store_true",
                   help="apenas vibra, sem fotografar (util para testar o motor)")
    p.add_argument("--sem-motor", action="store_true",
                   help="apenas fotografa, sem acionar o motor")
    p.add_argument("--json", action="store_true",
                   help="imprime um resumo em JSON na ultima linha (usado pelo painel)")
    return p.parse_args()


def resolucao(texto):
    try:
        largura, altura = (int(v) for v in texto.lower().split("x"))
    except ValueError:
        sys.exit(f"Resolucao invalida: {texto!r}. Use o formato LARGURAxALTURA, ex.: 1296x972")
    return largura, altura


def abrir_camera(tamanho, aquecimento):
    """Abre a camera e deixa a exposicao estabilizar antes do disparo."""
    from picamera2 import Picamera2

    camera = Picamera2()
    camera.configure(camera.create_still_configuration(main={"size": tamanho}))
    camera.start()
    if aquecimento > 0:
        time.sleep(aquecimento)
    return camera


def vibrar(pino, duracao, ativo_baixo, pwm=100.0, frequencia=1000):
    """Liga o motor por `duracao` segundos. `pwm` vai de 1 a 100."""
    intensidade = max(0.0, min(1.0, pwm / 100.0))
    motor = PWMOutputDevice(pino, active_high=not ativo_baixo,
                            initial_value=0, frequency=frequencia)
    try:
        print(f"Vibrando por {duracao:g} s no GPIO{pino} a {pwm:g}% ({frequencia} Hz)...")
        motor.value = intensidade
        time.sleep(duracao)
    finally:
        motor.off()   # garante o desligamento tambem em erro ou Ctrl+C
        motor.close()
    print("Vibracao encerrada.")


def fotografar(camera, quantidade, intervalo, pasta):
    """Tira as fotos em horarios fixos, sem acumular o atraso de cada captura."""
    pasta.mkdir(parents=True, exist_ok=True)
    inicio = time.monotonic()
    arquivos = []

    for indice in range(quantidade):
        espera = inicio + indice * intervalo - time.monotonic()
        if espera > 0:
            time.sleep(espera)
        carimbo = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]  # milissegundos
        caminho = pasta / f"{carimbo}.jpg"
        camera.capture_file(str(caminho))
        arquivos.append(caminho)
        print(f"Foto {indice + 1}/{quantidade}: {caminho} (+{time.monotonic() - inicio:.2f} s)")

    return arquivos


def main():
    args = argumentos()

    if args.fotos < 0:
        sys.exit("A quantidade de fotos nao pode ser negativa.")
    if args.intervalo < 0:
        sys.exit("O intervalo entre fotos nao pode ser negativo.")

    duracao = args.duracao
    usar_motor = not args.sem_motor
    if usar_motor and duracao <= 0:
        sys.exit("O tempo de vibracao deve ser maior que zero.")
    if not 1 <= args.pwm <= 100:
        sys.exit("A intensidade (--pwm) deve ficar entre 1 e 100.")

    camera = None
    if not args.sem_camera and args.fotos > 0:
        print("Preparando a camera...")
        camera = abrir_camera(resolucao(args.resolucao), args.aquecimento)

    inicio = datetime.now()
    arquivos = []
    try:
        if usar_motor:
            vibrar(args.pino, duracao, args.ativo_baixo, args.pwm, args.frequencia)
        if camera is not None:
            arquivos = fotografar(camera, args.fotos, args.intervalo, args.pasta)
    except KeyboardInterrupt:
        print("\nInterrompido pelo usuario.")
        return 1
    finally:
        if camera is not None:
            camera.stop()
            camera.close()

    if args.json:
        print(MARCADOR)
        print(json.dumps({
            "ok": True,
            "inicio": inicio.isoformat(timespec="seconds"),
            "fim": datetime.now().isoformat(timespec="seconds"),
            "modo": "foto" if not usar_motor else "alimentacao",
            "pasta": str(args.pasta),
            "arquivos": [a.name for a in arquivos],
            "parametros": {
                "pwm": args.pwm, "duracao": duracao if usar_motor else 0,
                "fotos": args.fotos, "intervalo": args.intervalo,
                "pino": args.pino, "resolucao": args.resolucao,
            },
        }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
