# Alimentador — painel no Raspberry Pi

Tudo roda no Pi, em `~/Documents/fish_feeder`. O computador (ou o celular
dentro de casa) só abre o navegador.

```
~/Documents/fish_feeder/
├── vibra_e_fotografa.py   seu script, agora com PWM e --json
├── nucleo.py              config, trava de concorrência, execução, histórico
├── agenda.py              agendamentos -> linhas no crontab
├── servidor.py            servidor web (Flask) na porta 8765
├── index.html             o painel
├── config.json            criado no primeiro acesso
├── agenda.json            os agendamentos
├── historico.json         o que cada acionamento gerou
├── alimentador.log        registro que aparece no painel
└── fotos/                 as fotos
```

## Instalar

```bash
cd ~/Documents/fish_feeder
sudo apt install python3-flask        # ou: pip install flask --break-system-packages
python3 servidor.py
```

Ele imprime o endereço. No computador abra `http://<ip-do-pi>:8765` ou
`http://raspberrypi.local:8765`.

Para subir sozinho no boot:

```bash
sudo cp alimentador@.service /etc/systemd/system/
sudo systemctl enable --now alimentador@$USER
```

## O que mudou no vibra_e_fotografa.py

O script continua funcionando exatamente como antes na linha de comando. O que
entrou:

- `-w/--pwm 1..100` — intensidade. Trocou `DigitalOutputDevice` por
  `PWMOutputDevice`, então `-w 100` é idêntico ao comportamento anterior.
- `-f/--frequencia` — frequência do PWM, padrão 1000 Hz.
- `--sem-motor` — só fotografa.
- `--json` — imprime um resumo na última linha, depois de `###JSON###`.
- `-o` agora tem como padrão `~/Documents/fish_feeder/fotos`, em vez de `fotos`
  relativo à pasta em que você estiver.
- `-c/--ciclos 1..5` e `--intervalo-ciclos` — veja "Ciclos de vibração" abaixo.

Ninguém chama o script direto: painel e agenda passam por `nucleo.executar()`,
que segura uma trava em arquivo. Assim dois acionamentos nunca disputam a
câmera — se você apertar o botão enquanto o cron está rodando, o painel avisa
em vez de estourar um erro da picamera2.

## Ciclos de vibração

Em vez de vibrar uma vez só, o alimentador pode repetir a vibração (e tirar
fotos de novo) várias vezes num mesmo acionamento — útil quando uma vibração
só não solta ração suficiente, ou quando ela cai aos poucos.

No painel, em "Acionar agora", os dois controles novos são:

- **Número de ciclos** (1 a 5) — quantas vezes o motor vibra nesse
  acionamento. Com 1 (padrão), o comportamento é exatamente o de antes.
- **Intervalo entre ciclos** — tempo do início de um ciclo até o início do
  próximo, em segundos. Tem duas regras:
  - nunca pode ser menor que **6 segundos**;
  - nunca pode ser menor que **fotos × intervalo entre fotos** (senão a
    câmera ainda estaria tirando foto do ciclo anterior quando o motor
    vibrasse de novo). O painel calcula esse mínimo sozinho e ajusta o campo.

As fotos são tiradas a cada ciclo (não só no final): com 3 fotos e 2 ciclos,
saem 6 fotos no total, 3 de cada vibrada.

Pela linha de comando:

```bash
python3 vibra_e_fotografa.py -c 3 --intervalo-ciclos 8   # 3 ciclos, 8s entre eles
```

Na agenda e no painel, esses dois valores também entram em "Salvar como
padrão" e ficam gravados em `config.json` (chaves `ciclos` e
`intervalo_ciclos`, tanto soltas quanto dentro de `padroes`).

## Agenda

Cada agendamento ativo vira uma linha dentro de um bloco delimitado no seu
crontab:

```
# inicio fish_feeder
30 8 * * 1,3 cd /home/pi/Documents/fish_feeder && /usr/bin/python3 .../agenda.py disparar ag2026...
# fim fish_feeder
```

Só esse bloco é reescrito; o resto do seu crontab fica intacto. A linha do cron
não carrega os parâmetros — ela só chama `disparar <id>`, e o Python lê os
valores em `agenda.json`. Assim, editar um horário no painel não exige mexer no
crontab de novo, e datas específicas (que no cron repetiriam todo ano) são
conferidas antes de acionar.

Pela linha de comando:

```bash
python3 agenda.py listar          # o que está marcado e o que está no cron
python3 agenda.py aplicar         # reescreve o bloco a partir do agenda.json
python3 agenda.py agora ag2026... # dispara ignorando dia e hora, para testar
python3 agenda.py limpar          # tira o bloco do crontab
```

## Fotos no computador

A galeria mostra as fotos servidas pelo Pi. O botão "baixar" de cada sessão
copia para o computador. Se você abrir o painel pelo Chrome e o navegador
permitir, dá para escolher uma pasta fixa e marcar "baixar sozinho a cada
acionamento" — aí cada acionamento já grava lá.

O seletor de pasta só existe em contexto seguro (https ou localhost). Abrindo
por `http://<ip-do-pi>:8765` o Chrome costuma recusar; nesse caso as fotos vão
para a pasta de downloads. Se quiser espelhamento automático de verdade,
o caminho mais simples é um `rsync` no computador:

```bash
rsync -av --ignore-existing pi@raspberrypi.local:~/Documents/fish_feeder/fotos/ ~/Pictures/fish_feeder/
```

## Pendente

O botão do celular fora de casa segue como mockup com cadeado, esperando o
Pub/Sub. Quando entrar, o assinante roda no mesmo Pi e pode chamar
`nucleo.executar()` — mesma trava, mesmo histórico, mesma galeria.

## Comando para verificar servidor
De agora em diante, nunca mais rode python3 servidor.py manualmente — isso criaria uma segunda instância brigando com a do systemd na mesma porta. Para controlar o serviço, use:


sudo systemctl status alimentador@vignoli-rasp    # ver status
sudo systemctl restart alimentador@vignoli-rasp   # reiniciar
sudo systemctl stop alimentador@vignoli-rasp      # parar
sudo journalctl -u alimentador@vignoli-rasp -f    # acompanhar logs em tempo real
