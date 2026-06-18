Failover Gamer

Programa para Windows que monitora duas conexões de internet (cabo Ethernet e Wi-Fi) e troca automaticamente entre elas quando uma cai — pensado para quem joga online e não pode perder a conexão durante uma partida.

Download

Baixe a versão mais recente já compilada (.exe) na seção Releases deste repositório — não precisa instalar Python nem nada além disso.


⚠️ Aviso sobre antivírus: alguns antivírus podem marcar o .exe como suspeito (falso positivo). Isso é um problema comum e conhecido de executáveis gerados pelo PyInstaller — o programa empacota o Python inteiro num único arquivo e o extrai ao abrir, um padrão de comportamento que se parece com o de alguns malwares aos olhos de detecção heurística, mesmo sem haver nada malicioso de fato. O código-fonte completo está neste repositório para quem quiser revisar antes de executar.



Como funciona


O cabo Ethernet é a conexão principal e é verificado a cada 1 segundo.
O Wi-Fi fica como reserva e é verificado a cada 2 segundos (para economizar dados), passando a ser verificado a cada 1 segundo automaticamente caso assuma como principal.
Se o cabo cair, o programa ajusta a métrica de rota do Windows para o Wi-Fi assumir o tráfego em poucos segundos, sem desconectar o jogo.
Quando o cabo voltar, ele retoma a posição de conexão principal automaticamente.


Funcionalidades


Interface gráfica com tema cyberpunk/HUD
Indicador de qualidade do ping (verde / amarelo / vermelho) com alerta sonoro diferenciado para picos de latência na conexão principal
Painel de estatísticas (uptime, número de quedas, tempo offline)
Gráfico de latência em tempo real (alternável)
Modo overlay compacto para deixar sobre o jogo
Ícone na bandeja do sistema
Bloqueio de instância única (não deixa abrir duas vezes)


Requisitos


Windows 10/11 (também funciona em Linux com ajustes)
Python 3.10+
Privilégios de administrador (necessário para alterar métricas de rota)


Dependências opcionais

Para o ícone na bandeja do sistema funcionar:

bashpip install pystray pillow

Uso

bashpython failover_gui.py

Execute como Administrador para a troca automática de rota funcionar.

Gerando um executável (.exe)

bashpip install pyinstaller
python -m PyInstaller --onefile --windowed --icon=icone.ico --name="Failover Gamer" failover_gui.py

O executável final fica em dist/Failover Gamer.exe.

Aviso

Este programa precisa de permissões administrativas para ajustar as configurações de rede do Windows (netsh). Revise o código antes de executar como administrador, como em qualquer programa baixado da internet.
