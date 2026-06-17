#!/usr/bin/env python3
"""
Failover de Rede — Gamer Edition (GUI)
Interface gráfica com tkinter (já vem com Python).
Execute como Administrador no Windows.
"""

import subprocess, time, sys, os, platform, threading, queue, random, socket
from datetime import datetime
from collections import deque
import tkinter as tk
from tkinter import font as tkfont
from tkinter import messagebox

# ─── INSTÂNCIA ÚNICA ────────────────────────────────────────────────────────────
# Usa uma porta TCP local fixa como "trava": se já tem alguém escutando nela,
# é porque o programa já está aberto.
_SINGLE_INSTANCE_PORT = 51737
_single_instance_socket = None  # mantido vivo durante toda a execução

def acquire_single_instance_lock():
    """Tenta se tornar a única instância em execução. Retorna True se conseguiu."""
    global _single_instance_socket
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 0)
        s.bind(("127.0.0.1", _SINGLE_INSTANCE_PORT))
        s.listen(1)
        _single_instance_socket = s  # guarda referência para não ser coletado/fechado
        return True
    except OSError:
        return False

# ─── CONFIGURAÇÕES ────────────────────────────────────────────────────────────
PING_HOSTS       = ["8.8.8.8", "1.1.1.1", "8.8.4.4"]
PING_COUNT       = 2
PING_TIMEOUT     = 1
CHECK_INTERVAL   = 1
WIFI_CHECK_INTERVAL = 2   # Segundos entre checagens do Wi-Fi quando está em reserva (economiza banda)
FAIL_THRESHOLD   = 2
RECOVER_THRESHOLD = 3

# Limiares de qualidade de ping (ms)
PING_GOOD_MAX = 100   # abaixo disso = verde (ping bom)
PING_HIGH_MAX = 500   # entre GOOD e HIGH = amarelo (ping médio) | >= HIGH = vermelho (ping muito alto)

OS = platform.system()

# Flag para esconder janelas de console ao chamar subprocess no Windows
_SUBPROCESS_FLAGS = subprocess.CREATE_NO_WINDOW if OS == "Windows" else 0

def beep():
    """Toca um beep de alerta quando a internet cair."""
    try:
        if OS == "Windows":
            import winsound
            for _ in range(3):
                winsound.Beep(880, 300)
                time.sleep(0.1)
        elif OS == "Darwin":
            subprocess.run(["afplay", "/System/Library/Sounds/Basso.aiff"], capture_output=True, creationflags=_SUBPROCESS_FLAGS)
        else:
            subprocess.run(["paplay", "/usr/share/sounds/freedesktop/stereo/dialog-warning.oga"],
                           capture_output=True, creationflags=_SUBPROCESS_FLAGS)
    except Exception:
        pass

# ─── CORES (tema HUD / Cyberpunk) ──────────────────────────────────────────────
BG        = "#070b13"   # fundo quase preto
BG2       = "#0d1626"   # painéis
BG3       = "#1c2c45"   # bordas / divisores
ACCENT    = "#39e6ff"   # ciano neon (principal / Wi-Fi)
GREEN     = "#39ff8c"   # verde neon (status OK / Ethernet)
RED       = "#ff3b5c"   # vermelho neon (alerta)
YELLOW    = "#ffc857"   # âmbar (atenção)
PURPLE    = "#8b6cff"   # roxo neon (acentos)
GRAY      = "#3a4a63"
TEXT      = "#eaf6ff"
TEXT2     = "#8fa3bf"
TEXT3     = "#4f6680"
HUD_FONT  = "Consolas"

def beep_ping_high():
    """Toca um alerta diferente quando o ping sobe drasticamente (sem cair a conexão)."""
    try:
        if OS == "Windows":
            import winsound
            winsound.Beep(440, 220)  # tom único, mais grave e curto que a queda
        elif OS == "Darwin":
            subprocess.run(["afplay", "/System/Library/Sounds/Pop.aiff"], capture_output=True, creationflags=_SUBPROCESS_FLAGS)
        else:
            subprocess.run(["paplay", "/usr/share/sounds/freedesktop/stereo/message.oga"],
                           capture_output=True, creationflags=_SUBPROCESS_FLAGS)
    except Exception:
        pass

def latency_color(lat):
    """Retorna a cor correspondente à qualidade do ping."""
    if lat is None:
        return RED
    if lat < PING_GOOD_MAX:
        return GREEN
    elif lat < PING_HIGH_MAX:
        return YELLOW
    else:
        return RED

def latency_zone(lat):
    """Retorna a zona de qualidade do ping: 'green', 'yellow' ou 'red'."""
    if lat is None:
        return "red"
    if lat < PING_GOOD_MAX:
        return "green"
    elif lat < PING_HIGH_MAX:
        return "yellow"
    else:
        return "red"

# ─── LÓGICA DE REDE (igual ao script original) ────────────────────────────────

import socket

def get_iface_ip_windows(iface):
    try:
        out = subprocess.check_output(
            ["netsh", "interface", "ip", "show", "address", iface],
            text=True, encoding="cp850", errors="replace", stderr=subprocess.DEVNULL, creationflags=_SUBPROCESS_FLAGS)
        for line in out.splitlines():
            line = line.strip()
            if line.startswith("Endere") or line.startswith("IP Address"):
                parts = line.split(":")
                if len(parts) == 2:
                    ip = parts[1].strip()
                    if ip and ip[0].isdigit():
                        return ip
    except Exception:
        pass
    return None

def test_connectivity(iface_ip=None, debug_log=None):
    """
    Testa conectividade real fazendo um socket TCP.
    Se iface_ip for fornecido, vincula o socket àquela interface —
    isso funciona de verdade no Windows, ao contrário do ping -S.
    Tenta várias portas/hosts pois firewalls podem bloquear algumas.
    """
    targets = [
        ("8.8.8.8", 443),
        ("1.1.1.1", 443),
        ("8.8.4.4", 443),
        ("8.8.8.8", 53),
        ("1.1.1.1", 53),
        ("8.8.8.8", 80),
    ]
    last_err = None
    for host, port in targets:
        s = None
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(PING_TIMEOUT)
            if iface_ip:
                s.bind((iface_ip, 0))  # vincula ao IP da interface
            t0 = time.time()
            s.connect((host, port))
            elapsed = round((time.time() - t0) * 1000)
            s.close()
            return True, elapsed
        except Exception as e:
            last_err = f"{host}:{port} -> {type(e).__name__}: {e}"
        finally:
            if s is not None:
                try:
                    s.close()
                except Exception:
                    pass
    if debug_log is not None and last_err:
        debug_log(f"DEBUG ip={iface_ip}: {last_err}")
    return False, None

def ping(host, iface_ip=None):
    """Mantido para compatibilidade — usa test_connectivity internamente."""
    ok, _ = test_connectivity(iface_ip)
    return ok

def is_interface_up(iface):
    try:
        if OS == "Windows":
            out = subprocess.check_output(
                ["netsh", "interface", "show", "interface", iface],
                stderr=subprocess.DEVNULL, text=True, encoding="cp850", errors="replace", creationflags=_SUBPROCESS_FLAGS)
            return "Connected" in out or "Conectad" in out
        else:
            out = subprocess.check_output(["ip", "link", "show", iface],
                                          stderr=subprocess.DEVNULL, text=True, creationflags=_SUBPROCESS_FLAGS)
            return "UP" in out and "NO-CARRIER" not in out
    except Exception:
        return False

def get_interfaces():
    ifaces = {}
    if OS == "Windows":
        try:
            out = subprocess.check_output(
                ["netsh", "interface", "show", "interface"],
                text=True, encoding="cp850", errors="replace", creationflags=_SUBPROCESS_FLAGS)
            for line in out.splitlines():
                l = line.lower()
                if "ethernet" in l or "local" in l or "cabo" in l:
                    name = line.split()[-1]
                    if name and len(name) > 2:
                        ifaces["ethernet"] = name; break
            for line in out.splitlines():
                l = line.lower()
                if "wi-fi" in l or "wifi" in l or "wireless" in l or "sem fio" in l:
                    name = line.split()[-1]
                    if name and len(name) > 2:
                        ifaces["wifi"] = name; break
        except Exception:
            pass
        ifaces.setdefault("ethernet", "Ethernet")
        ifaces.setdefault("wifi", "Wi-Fi")
    else:
        try:
            out = subprocess.check_output(["ip", "link", "show"], text=True,
                                          stderr=subprocess.DEVNULL, creationflags=_SUBPROCESS_FLAGS)
            for line in out.splitlines():
                if ": " in line:
                    name = line.split(": ")[1].split(":")[0].strip("@").strip()
                    if any(name.startswith(p) for p in ["eth","enp","ens","eno","en0"]):
                        ifaces["ethernet"] = name
                    elif any(name.startswith(p) for p in ["wl","wlan","wifi"]):
                        ifaces["wifi"] = name
        except Exception:
            pass
        ifaces.setdefault("ethernet", "eth0")
        ifaces.setdefault("wifi", "wlan0")
    return ifaces

def disable_iface(iface):
    """Desativa a interface de rede (força o SO a usar a outra)."""
    try:
        if OS == "Windows":
            subprocess.run(
                ["netsh", "interface", "set", "interface", iface, "admin=disable"],
                check=True, capture_output=True, creationflags=_SUBPROCESS_FLAGS)
        else:
            subprocess.run(["ip", "link", "set", iface, "down"], capture_output=True, creationflags=_SUBPROCESS_FLAGS)
    except Exception:
        pass

def enable_iface(iface):
    """Reativa a interface de rede quando ela se recuperar."""
    try:
        if OS == "Windows":
            subprocess.run(
                ["netsh", "interface", "set", "interface", iface, "admin=enable"],
                check=True, capture_output=True, creationflags=_SUBPROCESS_FLAGS)
        else:
            subprocess.run(["ip", "link", "set", iface, "up"], capture_output=True, creationflags=_SUBPROCESS_FLAGS)
    except Exception:
        pass

def set_metric_windows(iface, metric):
    try:
        subprocess.run(["netsh","interface","ip","set","interface",iface,
                        f"metric={metric}"], check=True, capture_output=True, creationflags=_SUBPROCESS_FLAGS)
    except Exception:
        pass

def switch_to(iface_name, all_ifaces, current_primary):
    if iface_name == current_primary:
        return False
    eth  = all_ifaces["ethernet"]
    wifi = all_ifaces["wifi"]
    if OS == "Windows":
        if iface_name == eth:
            set_metric_windows(eth, 10); set_metric_windows(wifi, 20)
        else:
            set_metric_windows(wifi, 10); set_metric_windows(eth, 20)
    elif OS == "Linux":
        prefer = "ethernet" if iface_name == eth else "wifi"
        set_route_linux(eth, wifi, prefer)
    return True

def set_route_linux(eth, wifi, prefer):
    try:
        primary   = eth if prefer=="ethernet" else wifi
        secondary = wifi if prefer=="ethernet" else eth
        subprocess.run(["ip","route","change","default","dev",primary,
                        "metric","100"], capture_output=True, creationflags=_SUBPROCESS_FLAGS)
        subprocess.run(["ip","route","change","default","dev",secondary,
                        "metric","200"], capture_output=True, creationflags=_SUBPROCESS_FLAGS)
    except Exception:
        pass

def is_admin():
    try:
        if OS == "Windows":
            import ctypes
            return bool(ctypes.windll.shell32.IsUserAnAdmin())
        return os.geteuid() == 0
    except Exception:
        return False

# ─── BANDEJA DO SISTEMA ─────────────────────────────────────────────────────────

try:
    import pystray
    from PIL import Image, ImageDraw
    TRAY_AVAILABLE = True
except Exception:
    TRAY_AVAILABLE = False

def make_tray_image(color_hex):
    """Cria um ícone triangular colorido para a bandeja do sistema."""
    size = 64
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    pad = 6
    points = [
        (size // 2, pad),          # topo
        (size - pad, size - pad),  # inferior direito
        (pad, size - pad),         # inferior esquerdo
    ]
    d.polygon(points, fill=color_hex)
    return img

# ─── MONITOR (roda em thread separada) ────────────────────────────────────────

class Monitor:
    def __init__(self, ifaces, event_queue):
        self.ifaces   = ifaces
        self.q        = event_queue
        self.running  = False
        self.fail     = {"ethernet": 0, "wifi": 0}
        self.ok       = {"ethernet": 0, "wifi": 0}
        self.status   = {"ethernet": True, "wifi": True}
        self.primary  = "ethernet"
        self.latency  = {"ethernet": None, "wifi": None}
        self.switches = 0
        self.log      = []

        # Estatísticas de uptime/downtime
        self.start_time   = time.time()
        self._last_tick_t = time.time()
        self.uptime       = {"ethernet": 0.0, "wifi": 0.0}
        self.downtime     = {"ethernet": 0.0, "wifi": 0.0}
        self.down_events  = {"ethernet": 0, "wifi": 0}

        # Controle de checagem do Wi-Fi (a cada N segundos quando em reserva)
        self._last_wifi_check = 0.0

        # Histórico de latência para o gráfico
        self.latency_hist = {"ethernet": deque(maxlen=120), "wifi": deque(maxlen=120)}

        # Zona de qualidade do ping (green/yellow/red) — para detectar picos
        self.ping_zone = {"ethernet": "green", "wifi": "green"}

        self._detect_initial_state()

    def _detect_initial_state(self):
        """Na inicialização, descobre quais interfaces têm internet de verdade."""
        # Testa Ethernet primeiro
        eth_iface = self.ifaces["ethernet"]
        eth_up = is_interface_up(eth_iface)
        if eth_up:
            eth_ip = get_iface_ip_windows(eth_iface) if OS == "Windows" else eth_iface
            eth_ok, eth_ms = test_connectivity(eth_ip, debug_log=self.add_log)
        else:
            eth_ok, eth_ms = False, None

        self.latency["ethernet"] = eth_ms
        self.latency_hist["ethernet"].append(eth_ms)

        if not eth_ok:
            self.status["ethernet"] = False
            self.fail["ethernet"] = FAIL_THRESHOLD
            self.ping_zone["ethernet"] = "red"
            self.add_log("❌ ETHERNET sem internet")
        else:
            self.ping_zone["ethernet"] = latency_zone(eth_ms)
            self.add_log("✅ ETHERNET com internet detectada")

        # Testa Wi-Fi depois (rota já estará correta)
        wifi_iface = self.ifaces["wifi"]
        wifi_up = is_interface_up(wifi_iface)
        if wifi_up:
            wifi_ip = get_iface_ip_windows(wifi_iface) if OS == "Windows" else wifi_iface
            wifi_ok, wifi_ms = test_connectivity(wifi_ip, debug_log=self.add_log)
        else:
            wifi_ok, wifi_ms = False, None

        self.latency["wifi"] = wifi_ms
        self.latency_hist["wifi"].append(wifi_ms)

        if not wifi_ok:
            self.status["wifi"] = False
            self.fail["wifi"] = FAIL_THRESHOLD
            self.ping_zone["wifi"] = "red"
            self.add_log("⚠  WIFI sem internet na inicialização")
        else:
            self.ping_zone["wifi"] = latency_zone(wifi_ms)
            self.add_log("✅ WIFI com internet detectada")

        self._last_wifi_check = time.time()

        if self.status["ethernet"]:
            self.primary = "ethernet"
        elif self.status["wifi"]:
            self.primary = "wifi"

    def test_iface(self, key):
        iface = self.ifaces[key]
        # Wi-Fi nunca é desativado — testa normalmente sempre
        if key == "wifi":
            up = is_interface_up(iface)
            if not up:
                self.latency[key] = None
                return False
            iface_ip = get_iface_ip_windows(iface) if OS == "Windows" else iface
            ok, ms = test_connectivity(iface_ip)
            self.latency[key] = ms
            return ok

        up = is_interface_up(iface)
        if not up:
            self.latency[key] = None
            return False

        iface_ip = get_iface_ip_windows(iface) if OS == "Windows" else iface
        ok, ms = test_connectivity(iface_ip, debug_log=self.add_log)
        self.latency[key] = ms
        return ok

    def add_log(self, msg):
        ts = datetime.now().strftime("%H:%M:%S")
        self.log.append(f"[{ts}] {msg}")
        if len(self.log) > 200:
            self.log.pop(0)

    def tick(self):
        # Tempo decorrido desde a última verificação (para uptime/downtime)
        now = time.time()
        dt = max(0.0, now - self._last_tick_t)
        self._last_tick_t = now

        spike_detected = {}

        for key in ("ethernet", "wifi"):
            # Wi-Fi em reserva: só testa a cada WIFI_CHECK_INTERVAL segundos (economiza banda).
            # Se o Wi-Fi for a conexão principal, testa a cada ciclo como o cabo.
            if key == "wifi" and self.primary != "wifi" \
                    and (now - self._last_wifi_check) < WIFI_CHECK_INTERVAL:
                self.latency_hist[key].append(self.latency[key])
                if self.status[key]:
                    self.uptime[key] += dt
                else:
                    self.downtime[key] += dt
                continue

            if key == "wifi":
                self._last_wifi_check = now

            ok = self.test_iface(key)

            # Histórico de latência (None quando sem resposta)
            self.latency_hist[key].append(self.latency[key])

            if ok:
                self.fail[key] = 0
                self.ok[key]  += 1
                if not self.status[key] and self.ok[key] >= RECOVER_THRESHOLD:
                    self.status[key] = True
                    msg = f"✅ {key.upper()} recuperada"
                    self.add_log(msg)
            else:
                self.ok[key]   = 0
                self.fail[key] += 1
                if self.status[key] and self.fail[key] >= FAIL_THRESHOLD:
                    self.status[key] = False
                    self.down_events[key] += 1
                    msg = f"❌ {key.upper()} caiu!"
                    self.add_log(msg)
                    threading.Thread(target=beep, daemon=True).start()

            # Acumula uptime/downtime com base no status atual
            if self.status[key]:
                self.uptime[key] += dt
            else:
                self.downtime[key] += dt

            # Detecta pico de ping (sem queda de conexão)
            lat = self.latency[key]
            if self.status[key]:
                zone = latency_zone(lat)

                if zone == "red" and self.ping_zone[key] != "red" and lat is not None:
                    spike_detected[key] = lat

                self.ping_zone[key] = zone
            else:
                self.ping_zone[key] = "red"

        eth_ok  = self.status["ethernet"]
        wifi_ok = self.status["wifi"]
        desired = ("ethernet" if eth_ok else ("wifi" if wifi_ok else None))

        if desired and desired != self.primary:
            iface_name = self.ifaces[desired]
            if switch_to(iface_name, self.ifaces, self.ifaces[self.primary]):
                self.switches += 1
                msg = f"⚡ Trocou para {desired.upper()}"
                self.add_log(msg)
                self.primary = desired

        # Alerta de ping alto somente para a conexão principal (ignora a reserva)
        if self.primary in spike_detected:
            lat = spike_detected[self.primary]
            self.add_log(f"⚠ PING ALTO em {self.primary.upper()}: {lat} ms")
            threading.Thread(target=beep_ping_high, daemon=True).start()

        self.q.put("update")

    def run(self):
        self.running = True
        while self.running:
            self.tick()
            time.sleep(CHECK_INTERVAL)

    def stop(self):
        self.running = False

    def uptime_pct(self, key):
        total = self.uptime[key] + self.downtime[key]
        if total <= 0:
            return None
        return (self.uptime[key] / total) * 100.0

    def downtime_str(self, key):
        secs = int(self.downtime[key])
        if secs < 60:
            return f"{secs}s"
        mins, s = divmod(secs, 60)
        if mins < 60:
            return f"{mins}m{s:02d}s"
        h, m = divmod(mins, 60)
        return f"{h}h{m:02d}m"

    def log_status_summary(self):
        """Registra no log uma descrição clara do estado atual de cada conexão."""
        labels = {"ethernet": "Ethernet (cabo)", "wifi": "Wi-Fi"}
        for key in ("ethernet", "wifi"):
            label = labels[key]
            if self.status[key]:
                lat = self.latency[key]
                qualidade = ""
                if lat is not None:
                    if lat < PING_GOOD_MAX:
                        qualidade = "ping bom"
                    elif lat < PING_HIGH_MAX:
                        qualidade = "ping médio"
                    else:
                        qualidade = "ping muito alto"
                    self.add_log(f"✅ Internet conectada via {label} — {lat} ms ({qualidade})")
                else:
                    self.add_log(f"✅ Internet conectada via {label}")
            else:
                self.add_log(f"❌ Internet desconectada em {label} — sem resposta dos servidores de teste")

# ─── GUI ──────────────────────────────────────────────────────────────────────

def round_rect(canvas, x1, y1, x2, y2, r=12, **kw):
    """Desenha um retângulo com cantos arredondados em um Canvas."""
    points = [
        x1+r, y1,  x2-r, y1,  x2, y1,  x2, y1+r,
        x2, y2-r,  x2, y2,    x2-r, y2, x1+r, y2,
        x1, y2,    x1, y2-r,  x1, y1+r, x1, y1,
    ]
    return canvas.create_polygon(points, smooth=True, **kw)


def corner_brackets(canvas, x1, y1, x2, y2, size=12, color=ACCENT, width=2):
    """Desenha cantos estilo HUD/mira nas 4 pontas de uma área."""
    canvas.create_line(x1, y1+size, x1, y1, x1+size, y1, fill=color, width=width)
    canvas.create_line(x2-size, y1, x2, y1, x2, y1+size, fill=color, width=width)
    canvas.create_line(x1, y2-size, x1, y2, x1+size, y2, fill=color, width=width)
    canvas.create_line(x2-size, y2, x2, y2, x2, y2-size, fill=color, width=width)


def layered_panel(canvas, x1, y1, x2, y2, accent_color, r=10, inner_fill=BG2, inner_outline=BG3):
    """Desenha um painel com moldura externa fina (cor de destaque) + painel interno,
    criando um efeito de camadas/bezel."""
    round_rect(canvas, x1, y1, x2, y2, r=r+3, fill="", outline=accent_color, width=1)
    round_rect(canvas, x1+4, y1+4, x2-4, y2-4, r=r, fill=inner_fill, outline=inner_outline, width=1)


def energy_sphere(canvas, cx, cy, r, color):
    """Desenha uma 'esfera de energia' — círculos concêntricos com brilho,
    retorna o id da camada externa (para animação de pulso)."""
    outer_r = r + 6
    mid_r   = r + 3

    glow_id = canvas.create_oval(cx-outer_r, cy-outer_r, cx+outer_r, cy+outer_r,
                                  fill=color, outline="", stipple="gray12")
    canvas.create_oval(cx-mid_r, cy-mid_r, cx+mid_r, cy+mid_r,
                       fill=color, outline="", stipple="gray25")
    canvas.create_oval(cx-r, cy-r, cx+r, cy+r, fill=color, outline="")

    return glow_id


CARD_W, CARD_H   = 212, 84
STATS_W, STATS_H = 456, 56
STATUS_W, STATUS_H = 456, 96
OVERLAY_W, OVERLAY_H = 184, 60

NORMAL_GEOMETRY  = "500x576"
OVERLAY_GEOMETRY = "198x74"


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("FAILOVER GAMER // v1.3")
        self.geometry(NORMAL_GEOMETRY)
        self.resizable(False, False)
        self.configure(bg=BG)
        self.protocol("WM_DELETE_WINDOW", self.on_close)

        # Tenta manter sempre no topo (útil durante jogo)
        self.attributes("-topmost", False)
        self._topmost     = False
        self._pulse_on    = False
        self.show_graph   = False
        self.overlay_mode = False
        self.tray_icon    = None
        self._tray_notified = False

        self.ifaces  = get_interfaces()
        self.q       = queue.Queue()
        self.monitor = Monitor(self.ifaces, self.q)

        self._build_ui()
        self._setup_tray()
        self._refresh()       # mostra imediatamente o estado já detectado na inicialização
        self._start_monitor()
        self._poll()
        self._animate()

    # ── construção da UI ──────────────────────────────────────────────────────

    def _build_ui(self):
        self.main_content = tk.Frame(self, bg=BG)
        self.main_content.pack(fill="both", expand=True)
        parent = self.main_content

        # ── Cabeçalho
        hdr = tk.Frame(parent, bg=BG)
        hdr.pack(fill="x", padx=22, pady=(10, 2))

        top_row = tk.Frame(hdr, bg=BG)
        top_row.pack(fill="x")

        tk.Label(top_row, text="◢ FAILOVER GAMER", bg=BG, fg=GREEN,
                 font=(HUD_FONT, 14, "bold")).pack(side="left")

        btns = tk.Frame(top_row, bg=BG)
        btns.pack(side="right")

        self.btn_check = self._hud_button(btns, "VERIFICAR", ACCENT, self._manual_check)
        self.btn_check.pack(side="right")
        self.btn_top = self._hud_button(btns, "FIXAR", PURPLE, self._toggle_topmost)
        self.btn_top.pack(side="right", padx=(0, 6))
        self.btn_overlay = self._hud_button(btns, "OVERLAY", GREEN, self._toggle_overlay)
        self.btn_overlay.pack(side="right", padx=(0, 6))

        tk.Label(hdr, text="NETWORK REDUNDANCY SYSTEM",
                 bg=BG, fg=ACCENT, font=(HUD_FONT, 7)).pack(anchor="w", pady=(2, 0))

        # ── faixa decorativa estilo "circuito"
        self._circuit_strip(parent)

        # ── Aviso de admin
        if not is_admin():
            warn = tk.Frame(parent, bg="#23121f", highlightbackground=RED, highlightthickness=1)
            warn.pack(fill="x", padx=22, pady=(6, 0))
            tk.Label(warn, text="⚠  EXECUTE COMO ADMINISTRADOR PARA TROCA AUTOMÁTICA",
                     bg="#23121f", fg=YELLOW,
                     font=(HUD_FONT, 8, "bold")).pack(pady=5)

        # ── Cards das interfaces
        cards = tk.Frame(parent, bg=BG)
        cards.pack(fill="x", padx=22, pady=(10, 0))
        cards.columnconfigure(0, weight=1)
        cards.columnconfigure(1, weight=1)

        self.eth_card  = self._iface_card(cards, "ETHERNET", "◈", "ethernet", 0)
        self.wifi_card = self._iface_card(cards, "WI-FI",    "◇", "wifi",     1)

        # ── Painel de estatísticas (uptime / quedas)
        self.stats_canvas = tk.Canvas(parent, width=STATS_W, height=STATS_H, bg=BG,
                                       highlightthickness=0)
        self.stats_canvas.pack(padx=22, pady=(8, 0))
        self._draw_stats_panel()

        # ── Painel "USANDO AGORA"
        self.status_canvas = tk.Canvas(parent, width=STATUS_W, height=STATUS_H, bg=BG,
                                        highlightthickness=0)
        self.status_canvas.pack(padx=22, pady=(8, 0))
        self._draw_status_panel("—", 0)

        # ── Log de eventos / Gráfico (alternáveis)
        log_outer = tk.Frame(parent, bg=BG)
        log_outer.pack(fill="both", expand=True, padx=22, pady=(10, 6))

        log_hdr = tk.Frame(log_outer, bg=BG)
        log_hdr.pack(fill="x")
        tk.Label(log_hdr, text="▸ LOG_DE_EVENTOS", bg=BG, fg=ACCENT,
                 font=(HUD_FONT, 8, "bold")).pack(side="left")
        self.lbl_cursor = tk.Label(log_hdr, text="_", bg=BG, fg=ACCENT,
                                    font=(HUD_FONT, 8, "bold"))
        self.lbl_cursor.pack(side="left", padx=(3, 0))

        self.btn_graph = self._hud_button(log_hdr, "MOSTRAR GRÁFICO", PURPLE, self._toggle_graph)
        self.btn_graph.pack(side="right")

        self.content_holder = tk.Frame(log_outer, bg=BG)
        self.content_holder.pack(fill="both", expand=True, pady=(5, 0))

        # Terminal de log
        self.term = tk.Frame(self.content_holder, bg="#03070d",
                             highlightbackground=BG3, highlightthickness=1)
        self.term.pack(fill="both", expand=True)

        self.log_text = tk.Text(
            self.term, bg="#03070d", fg=GREEN, width=10, height=4,
            font=(HUD_FONT, 8), relief="flat",
            state="disabled", wrap="word",
            highlightthickness=0, bd=0, insertbackground=GREEN)
        self.log_text.pack(fill="both", expand=True, padx=10, pady=8)

        # Gráfico de latência (oculto por padrão)
        self.graph_frame = tk.Frame(self.content_holder, bg="#03070d",
                                    highlightbackground=BG3, highlightthickness=1)
        self.graph_canvas = tk.Canvas(self.graph_frame, bg="#03070d", highlightthickness=0)
        self.graph_canvas.pack(fill="both", expand=True, padx=4, pady=4)

        # ── Rodapé
        foot = tk.Frame(parent, bg=BG)
        foot.pack(fill="x", padx=22, pady=(0, 10))
        self.lbl_time = tk.Label(foot, text="", bg=BG, fg=TEXT3, font=(HUD_FONT, 7))
        self.lbl_time.pack(side="left")
        tk.Label(foot, text=f"SCAN_INTERVAL: {CHECK_INTERVAL}s", bg=BG, fg=TEXT3,
                 font=(HUD_FONT, 7)).pack(side="right")

        if not TRAY_AVAILABLE:
            self.monitor.add_log("⚠ pystray não instalado — ícone de bandeja desativado")

        # ── Overlay compacto (oculto por padrão)
        self.overlay_frame = tk.Frame(self, bg=BG)
        self.overlay_canvas = tk.Canvas(self.overlay_frame, width=OVERLAY_W, height=OVERLAY_H,
                                        bg=BG, highlightthickness=0)
        self.overlay_canvas.pack(padx=4, pady=4)
        self.overlay_canvas.bind("<Button-1>", lambda e: self._toggle_overlay())
        self.overlay_glow_ids = {"ethernet": None, "wifi": None}
        self._draw_overlay()

    def _hud_button(self, parent, text, color, command):
        btn = tk.Label(parent, text=f" {text} ", bg=BG2, fg=color,
                       font=(HUD_FONT, 8, "bold"), cursor="hand2",
                       highlightbackground=color, highlightcolor=color,
                       highlightthickness=1, padx=5, pady=4)
        btn.bind("<Button-1>", lambda e: command())
        return btn

    def _circuit_strip(self, parent):
        """Faixa decorativa fina com padrão de circuito, só visual."""
        w = 456
        c = tk.Canvas(parent, width=w, height=10, bg=BG, highlightthickness=0)
        c.pack(padx=22, pady=(3, 0))
        y = 5
        c.create_line(0, y, w, y, fill=BG3, width=1)
        rnd = random.Random(42)
        x = 8
        palette = [ACCENT, GREEN, PURPLE, BG3]
        while x < w - 8:
            if rnd.random() < 0.45:
                r = 2
                color = rnd.choice(palette)
                c.create_oval(x-r, y-r, x+r, y+r, fill=color, outline="")
            x += rnd.randint(14, 38)

    def _iface_card(self, parent, label, icon, key, col):
        holder = tk.Frame(parent, bg=BG)
        holder.grid(row=0, column=col, sticky="nsew",
                    padx=(0, 8) if col == 0 else (8, 0))

        cv = tk.Canvas(holder, width=CARD_W, height=CARD_H, bg=BG, highlightthickness=0)
        cv.pack()

        data = {
            "canvas": cv, "label": label, "icon": icon, "key": key,
            "iface_name": self.ifaces[key],
            "glow_id": None,
        }
        self._draw_card(data, GRAY, GRAY, "INICIALIZANDO...", "—")
        return data

    def _draw_card(self, data, role_color, ping_color, status_text, ms_text):
        cv = data["canvas"]
        cv.delete("all")
        w, h = CARD_W, CARD_H

        layered_panel(cv, 2, 2, w-2, h-2, role_color, r=8)
        corner_brackets(cv, 6, 6, w-6, h-6, size=9, color=role_color, width=2)

        # Linha 1: ícone + nome
        cv.create_text(15, 17, anchor="w", text=data["icon"], fill=role_color,
                       font=(HUD_FONT, 12, "bold"))
        cv.create_text(33, 17, anchor="w", text=data["label"], fill=TEXT2,
                       font=(HUD_FONT, 9, "bold"))

        # Linha 2: esfera de energia (qualidade do ping, 50% menor) + status,
        # agrupados juntos e centralizados
        status_id = cv.create_text(0, 42, anchor="w", text=status_text, fill=role_color,
                                    font=(HUD_FONT, 9, "bold"))
        bbox = cv.bbox(status_id)
        text_w = bbox[2] - bbox[0]

        r = 2.5
        gap = 6
        dot_d = (r + 6) * 2  # diâmetro incluindo o halo externo

        start_x = (w - (dot_d + gap + text_w)) / 2
        dot_cx = start_x + (r + 6)
        cv.coords(status_id, start_x + dot_d + gap, 42)

        data["glow_id"] = energy_sphere(cv, dot_cx, 42, r, ping_color)

        # Linha 3: ping (centralizado)
        cv.create_text(w // 2, 65, text=ms_text, fill=ping_color, font=(HUD_FONT, 8, "bold"))

    def _draw_stats_panel(self):
        cv = self.stats_canvas
        cv.delete("all")
        w, h = STATS_W, STATS_H
        m = self.monitor

        layered_panel(cv, 2, 2, w-2, h-2, PURPLE, r=8)
        cv.create_line(w//2, 12, w//2, h-12, fill=BG3, width=1)

        for i, key in enumerate(("ethernet", "wifi")):
            cx = (w // 4) + i * (w // 2)
            color = GREEN if key == "ethernet" else ACCENT
            label = "ETHERNET" if key == "ethernet" else "WI-FI"

            pct = m.uptime_pct(key)
            pct_text = f"{pct:.1f}%" if pct is not None else "—"

            cv.create_text(cx, 14, text=f"◆ {label}", fill=color, font=(HUD_FONT, 8, "bold"))
            cv.create_text(cx, 30, text=f"UPTIME: {pct_text}", fill=TEXT2, font=(HUD_FONT, 8))
            cv.create_text(cx, 45,
                           text=f"QUEDAS: {m.down_events[key]}  OFFLINE: {m.downtime_str(key)}",
                           fill=TEXT3, font=(HUD_FONT, 7))

    def _draw_status_panel(self, primary_text, switches):
        cv = self.status_canvas
        cv.delete("all")
        w, h = STATUS_W, STATUS_H

        if primary_text == "—":
            color = GRAY
        elif "ETHERNET" in primary_text.upper() or "CABO" in primary_text.upper():
            color = GREEN
        else:
            color = ACCENT

        layered_panel(cv, 2, 2, w-2, h-2, color, r=10)
        corner_brackets(cv, 6, 6, w-6, h-6, size=14, color=color, width=2)

        cv.create_text(w//2, 20, text="◢ CONEXÃO ATIVA ◣", fill=TEXT3,
                       font=(HUD_FONT, 8, "bold"))
        cv.create_text(w//2, 50, text=primary_text, fill=color,
                       font=(HUD_FONT, 20, "bold"))

        plural = "S" if switches != 1 else ""
        cv.create_text(w//2, 78, text=f"{switches} TROCA{plural} REALIZADA{plural}",
                       fill=TEXT3, font=(HUD_FONT, 8))

    def _draw_overlay(self):
        cv = self.overlay_canvas
        cv.delete("all")
        w, h = OVERLAY_W, OVERLAY_H
        m = self.monitor

        layered_panel(cv, 2, 2, w-2, h-2, PURPLE, r=8)

        for i, key in enumerate(("ethernet", "wifi")):
            y = 19 + i * 24
            icon  = "◈" if key == "ethernet" else "◇"
            label = "ETH" if key == "ethernet" else "WIFI"

            ok      = m.status[key]
            primary = m.primary == key
            lat     = m.latency[key]

            if ok and primary:
                role_color = GREEN
            elif ok:
                role_color = ACCENT
            else:
                role_color = RED

            ping_color = latency_color(lat) if ok else RED
            ms_text = f"{lat} ms" if lat is not None else "—"

            cv.create_text(13, y, anchor="w", text=f"{icon} {label}", fill=role_color,
                           font=(HUD_FONT, 9, "bold"))

            dot_cx, dot_cy, r = w // 2 + 8, y, 5
            self.overlay_glow_ids[key] = energy_sphere(cv, dot_cx, dot_cy, r, ping_color)

            cv.create_text(w - 12, y, anchor="e", text=ms_text, fill=ping_color,
                           font=(HUD_FONT, 9, "bold"))

        cv.create_text(w - 9, 8, text="⤢", fill=TEXT3, font=(HUD_FONT, 8))

    def _draw_graph(self):
        cv = self.graph_canvas
        cv.update_idletasks()
        w = cv.winfo_width()
        h = cv.winfo_height()
        if w < 20 or h < 20:
            return
        cv.delete("all")

        m = self.monitor
        eth_hist  = list(m.latency_hist["ethernet"])
        wifi_hist = list(m.latency_hist["wifi"])
        n = len(eth_hist)

        if n < 2:
            cv.create_text(w//2, h//2, text="COLETANDO DADOS...",
                           fill=TEXT3, font=(HUD_FONT, 9, "bold"))
            return

        vals = [v for v in (eth_hist + wifi_hist) if v is not None]
        max_ms = max(50, int(max(vals) * 1.2)) if vals else 100

        pad_l, pad_r, pad_t, pad_b = 32, 8, 16, 16
        plot_w = max(1, w - pad_l - pad_r)
        plot_h = max(1, h - pad_t - pad_b)

        for frac in (0, 0.25, 0.5, 0.75, 1.0):
            y = pad_t + plot_h * (1 - frac)
            val = int(max_ms * frac)
            cv.create_line(pad_l, y, w - pad_r, y, fill=BG3, width=1)
            cv.create_text(pad_l - 4, y, text=str(val), fill=TEXT3,
                           font=(HUD_FONT, 7), anchor="e")

        def x_at(i):
            return pad_l + plot_w * i / (n - 1)

        def y_at(v):
            return pad_t + plot_h * (1 - min(v, max_ms) / max_ms)

        def plot(hist, color):
            pts = []
            for i, v in enumerate(hist):
                if v is None:
                    if len(pts) >= 4:
                        cv.create_line(*pts, fill=color, width=2, smooth=True)
                    pts = []
                    continue
                pts += [x_at(i), y_at(v)]
            if len(pts) >= 4:
                cv.create_line(*pts, fill=color, width=2, smooth=True)

        plot(eth_hist, GREEN)
        plot(wifi_hist, ACCENT)

        cv.create_text(pad_l + 4, 8, text="● ETHERNET", fill=GREEN,
                       font=(HUD_FONT, 7, "bold"), anchor="w")
        cv.create_text(pad_l + 80, 8, text="● WI-FI", fill=ACCENT,
                       font=(HUD_FONT, 7, "bold"), anchor="w")
        cv.create_text(w - pad_r, 8, text="ms", fill=TEXT3,
                       font=(HUD_FONT, 7), anchor="e")

    # ── animação (pulso dos indicadores + cursor do log) ───────────────────────

    def _animate(self):
        self._pulse_on = not self._pulse_on
        stip = "gray25" if self._pulse_on else "gray12"
        for card in (self.eth_card, self.wifi_card):
            try:
                card["canvas"].itemconfig(card["glow_id"], stipple=stip)
            except Exception:
                pass
        for key, gid in self.overlay_glow_ids.items():
            try:
                self.overlay_canvas.itemconfig(gid, stipple=stip)
            except Exception:
                pass
        self.lbl_cursor.configure(fg=ACCENT if self._pulse_on else BG)
        self.after(650, self._animate)

    # ── lógica ────────────────────────────────────────────────────────────────

    def _toggle_topmost(self):
        self._topmost = not self._topmost
        self.attributes("-topmost", self._topmost)
        if self._topmost:
            self.btn_top.configure(bg=PURPLE, fg=BG)
        else:
            self.btn_top.configure(bg=BG2, fg=PURPLE)

    def _toggle_overlay(self):
        self.overlay_mode = not self.overlay_mode
        if self.overlay_mode:
            self.main_content.pack_forget()
            self.title("FG")
            self.geometry(OVERLAY_GEOMETRY)
            self.overlay_frame.pack(fill="both", expand=True)
            self._draw_overlay()
            self.attributes("-topmost", True)
        else:
            self.overlay_frame.pack_forget()
            self.title("FAILOVER GAMER // v1.3")
            self.geometry(NORMAL_GEOMETRY)
            self.main_content.pack(fill="both", expand=True)
            self.attributes("-topmost", self._topmost)

    def _toggle_graph(self):
        self.show_graph = not self.show_graph
        if self.show_graph:
            self.term.pack_forget()
            self.graph_frame.pack(fill="both", expand=True)
            self.btn_graph.configure(text=" OCULTAR GRÁFICO ")
            self.after(50, self._draw_graph)
        else:
            self.graph_frame.pack_forget()
            self.term.pack(fill="both", expand=True)
            self.btn_graph.configure(text=" MOSTRAR GRÁFICO ")

    def _manual_check(self):
        self.btn_check.configure(text=" VERIFICANDO... ")
        self.monitor.add_log("🔄 Verificação manual iniciada...")
        self.q.put("update")
        def run():
            try:
                self.monitor.tick()
                self.monitor.log_status_summary()
            except Exception as e:
                self.monitor.add_log(f"ERRO no tick: {type(e).__name__}: {e}")
            finally:
                self.q.put("update")
                self.after(0, lambda: self.btn_check.configure(text=" VERIFICAR "))
        threading.Thread(target=run, daemon=True).start()

    def _start_monitor(self):
        t = threading.Thread(target=self.monitor.run, daemon=True)
        t.start()

    # ── bandeja do sistema ──────────────────────────────────────────────────────

    def _setup_tray(self):
        if not TRAY_AVAILABLE:
            return
        try:
            image = make_tray_image(GRAY)
            menu = pystray.Menu(
                pystray.MenuItem("Mostrar Failover Gamer",
                                 lambda icon, item: self.q.put("show"), default=True),
                pystray.MenuItem("Sair",
                                 lambda icon, item: self.q.put("quit")),
            )
            self.tray_icon = pystray.Icon("failover_gamer", image, "Failover Gamer", menu)

            def _run():
                try:
                    self.tray_icon.run()
                except Exception:
                    pass

            threading.Thread(target=_run, daemon=True).start()
        except Exception:
            self.tray_icon = None

    def _restore_window(self):
        self.deiconify()
        self.lift()
        self.focus_force()

    def _update_tray_icon(self):
        if self.tray_icon is None:
            return
        m = self.monitor
        if m.status["ethernet"] and m.primary == "ethernet":
            color = GREEN
        elif m.status["wifi"] and m.primary == "wifi":
            color = ACCENT
        elif not m.status["ethernet"] and not m.status["wifi"]:
            color = RED
        else:
            color = YELLOW
        try:
            self.tray_icon.icon = make_tray_image(color)
        except Exception:
            pass

    # ── loop principal de atualização ───────────────────────────────────────────

    def _poll(self):
        try:
            while True:
                item = self.q.get_nowait()
                if item == "show":
                    self._restore_window()
                elif item == "quit":
                    self._quit_app()
                    return
                else:
                    self._refresh()
        except queue.Empty:
            pass
        self.after(300, self._poll)

    def _refresh(self):
        m = self.monitor

        if self.overlay_mode:
            self._draw_overlay()
            self._update_tray_icon()
            return

        self._update_card(self.eth_card,  "ethernet")
        self._update_card(self.wifi_card, "wifi")
        self._draw_stats_panel()

        primary_label = "ETHERNET (CABO)" if m.primary == "ethernet" else "WI-FI"
        self._draw_status_panel(primary_label, m.switches)

        if self.show_graph:
            self._draw_graph()

        self._update_tray_icon()

        self.lbl_time.configure(
            text=datetime.now().strftime("ÚLTIMA VERIFICAÇÃO: %H:%M:%S"))

        # Atualiza log
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.tag_configure("red",    foreground=RED)
        self.log_text.tag_configure("green",  foreground=GREEN)
        self.log_text.tag_configure("accent", foreground=ACCENT)
        self.log_text.tag_configure("yellow", foreground=YELLOW)
        self.log_text.tag_configure("normal", foreground=TEXT2)
        for line in m.log[-40:]:
            if "❌" in line or "caiu" in line.lower():
                tag = "red"
            elif "✅" in line or "recuper" in line.lower():
                tag = "green"
            elif "⚡" in line or "trocou" in line.lower():
                tag = "accent"
            elif "⚠ PING ALTO" in line:
                tag = "yellow"
            else:
                tag = "normal"
            self.log_text.insert("end", f"> {line}\n", tag)
        self.log_text.configure(state="disabled")
        self.log_text.see("end")

    def _update_card(self, card, key):
        m   = self.monitor
        ok      = m.status[key]
        primary = m.primary == key
        lat     = m.latency[key]

        if ok and primary:
            role_color, status_text = GREEN, "ATIVO (PRINCIPAL)"
        elif ok:
            role_color, status_text = ACCENT, "ATIVO (RESERVA)"
        elif m.fail[key] > 0 and m.status[key] is False:
            role_color, status_text = RED, "SEM CONEXÃO"
        else:
            role_color, status_text = YELLOW, "VERIFICANDO..."

        ping_color = latency_color(lat) if ok else RED
        ms_text = f"{lat} ms" if lat is not None else "—"
        self._draw_card(card, role_color, ping_color, status_text, ms_text)

    def on_close(self):
        if TRAY_AVAILABLE and self.tray_icon is not None:
            if not self._tray_notified:
                try:
                    self.tray_icon.notify(
                        "Failover Gamer continua rodando em segundo plano.\n"
                        "Clique no ícone da bandeja para abrir ou sair.",
                        "Minimizado")
                except Exception:
                    pass
                self._tray_notified = True
            self.withdraw()
        else:
            self._quit_app()

    def _quit_app(self):
        self.monitor.stop()
        if self.tray_icon is not None:
            try:
                self.tray_icon.stop()
            except Exception:
                pass
        self.destroy()
        sys.exit(0)

# ─── MAIN ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    if not acquire_single_instance_lock():
        # Já existe uma instância rodando — avisa e encerra sem abrir nada novo
        try:
            root = tk.Tk()
            root.withdraw()
            messagebox.showwarning(
                "Failover Gamer",
                "⚠ O programa já está aberto!\n\nVerifique a bandeja do sistema "
                "(perto do relógio) ou a barra de tarefas — só é permitida uma "
                "instância por vez."
            )
            root.destroy()
        except Exception:
            print("Programa já aberto.")
        sys.exit(1)

    app = App()
    app.mainloop()
