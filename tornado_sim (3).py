"""
╔══════════════════════════════════════════════════════════════════╗
║   TWISTEX — Simulador de Tornados · Vórtice de Rankine v5.0     ║
║   Proyecto Científico SIL 2026 — Paraguay                        ║
║                                                                  ║
║   CÓMO EJECUTAR:                                                 ║
║     1. pip install -r requirements.txt                           ║
║     2. streamlit run tornado_sim.py                              ║
║     3. Abrir http://localhost:8501                               ║
║                                                                  ║
║   NOVEDADES v5.0:                                                ║
║   · Fix: la animación ya no expulsa las partículas del core      ║
║     (integración en coordenadas polares, rotación exacta)        ║
║   · Fix: el inflow se frena en la pared del core (antes violaba  ║
║     la conservación de masa y apilaba todo en el eje)            ║
║   · Fix: preset por callback, sin warnings de session_state      ║
║   · Fix: bandas Fujita invertidas con vientos bajos              ║
║   · Fix: estilos de métricas y fondo en Streamlit actual         ║
║   · Nuevo: pestaña CALIBRACIÓN (ajuste de Rankine a mediciones   ║
║     del anemómetro del prototipo físico)                         ║
║   · Nuevo: giro horario (hemisferio sur) y circulación Γ         ║
║   · Textos corregidos: daños por viento, datos del evento real   ║
╚══════════════════════════════════════════════════════════════════╝
"""

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

# ─── CONSTANTES ─────────────────────────────────────────────────────────────────
RHO_AIRE = 1.225           # densidad del aire a nivel del mar [kg/m³]
TNT_J = 4.184e9            # energía de 1 tonelada de TNT [J]
ANIM_MAX_PARTICLES = 1500  # cap de partículas para la animación (rendimiento)
SENTIDO = -1               # -1 = giro horario visto desde arriba (ciclónico en el hemisferio sur)

# ─── CONFIG DE PÁGINA ───────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Twistex — Simulador de Tornados",
    page_icon="🌪️",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ─── CSS ────────────────────────────────────────────────────────────────────────
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Orbitron:wght@400;700;900&family=Share+Tech+Mono&display=swap');

html, body, .stApp, [data-testid="stAppViewContainer"] { background-color: #070b14; color: #c8d8f0; }
[data-testid="stHeader"] { background: transparent; }

h1 {
    font-family: 'Orbitron', monospace !important;
    font-weight: 900 !important; font-size: 2.4rem !important;
    letter-spacing: 0.12em !important;
    background: linear-gradient(135deg, #4af0ff 0%, #7b5fff 50%, #ff6b35 100%);
    -webkit-background-clip: text; -webkit-text-fill-color: transparent;
    background-clip: text; margin-bottom: 0 !important;
}
h2, h3 {
    font-family: 'Orbitron', monospace !important; font-weight: 700 !important;
    color: #4af0ff !important; letter-spacing: 0.08em !important;
}
[data-testid="stSidebar"] {
    background: linear-gradient(180deg, #0a1020 0%, #0d1525 100%) !important;
    border-right: 1px solid #1a2a4a;
}
[data-testid="stSidebar"] label {
    font-family: 'Share Tech Mono', monospace !important;
    color: #8ab4d8 !important; font-size: 0.85rem !important;
}
[data-testid="stMetric"], [data-testid="metric-container"] {
    background: rgba(74,240,255,0.05) !important;
    border: 1px solid rgba(74,240,255,0.2) !important;
    border-radius: 8px !important; padding: 12px !important;
}
[data-testid="stMetricLabel"], [data-testid="stMetricLabel"] p {
    font-family: 'Share Tech Mono', monospace !important;
    color: #8ab4d8 !important; font-size: 0.75rem !important;
}
[data-testid="stMetricValue"] {
    font-family: 'Orbitron', monospace !important;
    color: #4af0ff !important; font-size: 1.1rem !important;
}
hr { border-color: #1a2a4a !important; }
[data-testid="stPlotlyChart"] {
    border: 1px solid #1a2a4a; border-radius: 12px; overflow: hidden;
}
</style>
""", unsafe_allow_html=True)

MONO = "font-family:Share Tech Mono,monospace"


def nota(texto, color="#4a6a8a", size="0.82rem"):
    st.markdown(f"<span style='{MONO};color:{color};font-size:{size}'>{texto}</span>",
                unsafe_allow_html=True)


# ─── ESCALA FUJITA ──────────────────────────────────────────────────────────────
# v_min = umbral inferior de la categoría [m/s]. El límite superior es el v_min siguiente.
FUJITA = [
    {"cat": "F0", "v_min": 0,   "color": "#6ee7b7", "bg": "rgba(110,231,183,0.15)",
     "label": "Débil",         "damage": "Daño leve. Ramas rotas, carteles caídos, daño superficial en techos."},
    {"cat": "F1", "v_min": 33,  "color": "#fbbf24", "bg": "rgba(251,191,36,0.15)",
     "label": "Moderado",      "damage": "Daño moderado. Techos dañados, autos desplazados, árboles derribados."},
    {"cat": "F2", "v_min": 50,  "color": "#f97316", "bg": "rgba(249,115,22,0.15)",
     "label": "Significativo", "damage": "Daño considerable. Techos arrancados, casas de madera destruidas, autos volcados."},
    {"cat": "F3", "v_min": 70,  "color": "#ef4444", "bg": "rgba(239,68,68,0.15)",
     "label": "Severo",        "damage": "Daño severo. Paredes derrumbadas, trenes volcados, árboles desarraigados."},
    {"cat": "F4", "v_min": 93,  "color": "#dc2626", "bg": "rgba(220,38,38,0.15)",
     "label": "Devastador",    "damage": "Daño devastador. Casas bien construidas destruidas totalmente."},
    {"cat": "F5", "v_min": 117, "color": "#9b1c1c", "bg": "rgba(155,28,28,0.15)",
     "label": "Increíble",     "damage": "Daño increíble. Estructuras de hormigón dañadas, autos lanzados a cientos de metros."},
]


def get_fujita(v_ms):
    """Categoría Fujita para una velocidad en m/s (sin huecos entre categorías)."""
    actual = FUJITA[0]
    for f in FUJITA:
        if v_ms >= f["v_min"]:
            actual = f
    return actual


def rango_fujita(i):
    """Texto del rango de velocidades de la categoría i."""
    if i == len(FUJITA) - 1:
        return f"≥ {FUJITA[i]['v_min']} m/s"
    if i == 0:
        return f"< {FUJITA[1]['v_min']} m/s"
    return f"{FUJITA[i]['v_min']}–{FUJITA[i+1]['v_min'] - 1} m/s"


# ─── PARÁMETROS ─────────────────────────────────────────────────────────────────
DEFAULTS = {
    "R_c": 150, "max_wind": 70, "updraft_strength": 30,
    "inflow_angle": 20, "n_particles": 2000, "max_height": 2000,
}

# Preset: tornado F1 de Santa Rosa del Monday (21 de diciembre de 2025).
# Lo único documentado es la categoría (F1, DMH) y ráfagas de más de 130 km/h.
# 40 m/s = 144 km/h queda dentro de ese rango. El resto son supuestos razonables
# para un F1, no mediciones.
SANTA_ROSA_PRESET = {
    "R_c": 120, "max_wind": 40, "updraft_strength": 25,
    "inflow_angle": 18, "n_particles": 2500, "max_height": 1800,
}

for _k, _v in DEFAULTS.items():
    st.session_state.setdefault(_k, _v)


def aplicar(valores):
    st.session_state.update(valores)


# ─── SIDEBAR ────────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("## 🌪️ CONTROLES DEL VÓRTICE")
    st.markdown("---")
    st.button("⚡ Preset: Santa Rosa del Monday F1", width="stretch",
              on_click=aplicar, args=(SANTA_ROSA_PRESET,))
    st.button("↺ Valores por defecto", width="stretch",
              on_click=aplicar, args=(DEFAULTS,))
    st.markdown("---")

    st.markdown("### ESTRUCTURA")
    R_c = st.slider("Radio del core (R_c) [m]", 50, 500, step=10, key="R_c",
                    help="Radio de vientos máximos.")
    max_wind = st.slider("Viento máximo [m/s]", 20, 150, step=5, key="max_wind",
                         help="Velocidad tangencial en el borde del core. Define la categoría Fujita.")

    st.markdown("### DINÁMICA")
    updraft_strength = st.slider("Fuerza del updraft [m/s]", 5, 80, step=5, key="updraft_strength",
                                 help="Velocidad vertical máxima, en el eje y en la cima del dominio.")
    inflow_angle = st.slider("Ángulo de inflow [°]", 5, 45, step=1, key="inflow_angle",
                             help="Ángulo con que el aire entra en espiral lejos del core. "
                                  "Cerca de la pared del core el inflow se frena y el aire gira hacia arriba.")

    st.markdown("### VISUALIZACIÓN")
    n_particles = st.slider("Cantidad de partículas", 500, 5000, step=100, key="n_particles",
                            help="Densidad visual (no afecta la física). La animación usa hasta 1500.")
    max_height = st.slider("Altura de simulación [m]", 500, 5000, step=100, key="max_height",
                           help="Extensión vertical de la columna simulada.")
    color_mode = st.selectbox("Colorear por",
                              ["Velocidad total", "Velocidad tangencial", "Velocidad vertical", "Radio"])

    st.markdown("### ANIMACIÓN")
    n_frames = st.slider("Frames de animación", 20, 80, 40, 5,
                         help="Más frames = animación más larga, pero tarda más en generar.")
    anim_speed = st.slider("Retardo por frame [ms]", 30, 200, 70, 10,
                           help="Menor valor = animación más rápida.")

    st.markdown("---")
    st.caption("Twistex · Modelo de Vórtice de Rankine · SIL 2026 · Paraguay")


# ─── HELPERS DE ESTILO ──────────────────────────────────────────────────────────
def axis_style(label):
    return dict(
        title=dict(text=label, font=dict(family="Share Tech Mono", color="#4af0ff", size=11)),
        tickfont=dict(family="Share Tech Mono", color="#4a6a8a", size=9),
        gridcolor="#0f1e30", showbackground=True,
        backgroundcolor="rgba(7,11,20,0.5)", zerolinecolor="#1a2a4a",
    )


def axis_2d(label):
    return dict(
        title=dict(text=label, font=dict(family="Share Tech Mono", color="#4af0ff", size=12)),
        tickfont=dict(family="Share Tech Mono", color="#4a6a8a", size=10),
        gridcolor="#0f1e30", zerolinecolor="#1a2a4a", showgrid=True,
    )


def colorbar(titulo, **kw):
    return dict(
        title=dict(text=titulo, side="right",
                   font=dict(family="Share Tech Mono", color="#8ab4d8", size=11)),
        thickness=14, tickfont=dict(family="Share Tech Mono", color="#8ab4d8", size=10), **kw)


BASE_LAYOUT = dict(
    paper_bgcolor="#070b14", plot_bgcolor="#070b14",
    font=dict(family="Share Tech Mono", color="#8ab4d8"),
)
LEGEND_STYLE = dict(bgcolor="rgba(7,11,20,0.8)", bordercolor="#1a2a4a", borderwidth=1,
                    font=dict(family="Share Tech Mono", size=11, color="#8ab4d8"))
SCENE = dict(bgcolor="#070b14",
             xaxis=axis_style("X [m]"), yaxis=axis_style("Y [m]"), zaxis=axis_style("Altura [m]"),
             aspectmode="manual", aspectratio=dict(x=1, y=1, z=1.4))
PLOT_CFG = {"displayModeBar": True, "displaylogo": False}
PLOT_CFG_MIN = {"displayModeBar": False, "displaylogo": False}


# ─── FÍSICA ─────────────────────────────────────────────────────────────────────
def rankine_vtheta(r, R_c, V_max):
    """Perfil tangencial de Rankine: rotación sólida adentro, decaimiento 1/r afuera."""
    r = np.asarray(r, dtype=float)
    r_safe = np.maximum(r, 1e-9)
    return np.where(r <= R_c, V_max * r / R_c, V_max * R_c / r_safe)


def rankine_presion_deficit(r, R_c, V_max, rho=RHO_AIRE):
    """
    Déficit de presión del vórtice de Rankine (balance ciclostrófico dp/dr = ρ·v²/r).
      r ≤ R_c : Δp(r) = ρ·V² · (1 − r²/(2R_c²))
      r > R_c : Δp(r) = ρ·V² · R_c²/(2r²)
    En el centro Δp = ρ·V². Retorna Pa (positivo = presión menor que el ambiente).
    """
    r = np.asarray(r, dtype=float)
    r_safe = np.maximum(r, 1e-9)
    return np.where(r <= R_c,
                    rho * V_max**2 * (1.0 - r**2 / (2.0 * R_c**2)),
                    rho * V_max**2 * R_c**2 / (2.0 * r_safe**2))


def energia_cinetica_rankine(R_c, V_max, H, rho=RHO_AIRE, corte=3.0):
    """
    Energía cinética rotacional, integrada analíticamente hasta corte·R_c:
      E/H = ∫ ½ρ·v²·2πr dr = πρ·V²·R_c² · (1/4 + ln(corte))
    La integral diverge logarítmicamente sin corte; 3·R_c es la frontera práctica.
    Retorna (E_total [J], E_por_metro [J/m]).
    """
    e_por_m = np.pi * rho * V_max**2 * R_c**2 * (0.25 + np.log(corte))
    return e_por_m * H, e_por_m


def campo(r, z, R_c, V_max, alpha, W, H):
    """
    Campo de velocidad en coordenadas cilíndricas (V_θ, V_r, V_z). Vectorizado.

    V_θ : Rankine.
    V_r : inflow en espiral, −V_θ·tan(α) lejos del core. Se multiplica por
          (1 − R_c²/r²), que lo lleva a cero en la pared del core: ahí el aire
          deja de converger y gira hacia arriba. Sin ese factor, una
          convergencia uniforme dentro del core exigiría un updraft de cientos
          de m/s para conservar la masa. Decae con la altura (el inflow es un
          fenómeno de capa baja).
    V_z : updraft gaussiano centrado en el eje, creciente con la altura.
    """
    r = np.maximum(np.asarray(r, dtype=float), 1e-6)
    zc = np.clip(z, 0.0, H)
    V_th = rankine_vtheta(r, R_c, V_max)
    freno = np.clip(1.0 - (R_c / r)**2, 0.0, 1.0)
    V_r = -V_th * np.tan(alpha) * np.exp(-zc / (0.6 * H)) * freno
    V_z = W * np.exp(-0.5 * (r / R_c)**2) * (0.5 + 0.5 * zc / H)
    return V_th, V_r, V_z


def paso(r, th, z, dt, R_c, V_max, alpha, W, H):
    """
    Avanza partículas un paso dt en coordenadas polares.

    En polares la rotación es exacta: el radio solo cambia por el inflow. El
    Euler cartesiano anterior movía cada partícula por la tangente, así que en
    cada paso el radio crecía un poco y el core se vaciaba solo.
    El radio usa s = r² − R_c², que cumple ds/dt = −k·s/r²; se integra como
    exponencial, así nunca cruza la pared del core con ningún dt.
    """
    r = np.maximum(np.asarray(r, dtype=float), 1e-6)
    V_th, V_r, V_z = campo(r, z, R_c, V_max, alpha, W, H)
    th2 = th + SENTIDO * (V_th / r) * dt
    k = 2.0 * V_max * R_c * np.tan(alpha) * np.exp(-np.clip(z, 0.0, H) / (0.6 * H))
    s = np.maximum(r**2 - R_c**2, 0.0)
    r2 = np.where(r > R_c, np.sqrt(R_c**2 + s * np.exp(-k * dt / r**2)), r)
    z2 = z + V_z * dt
    return r2, th2, z2, V_th, V_r, V_z


def muestrear_radios(rng, n, R_c):
    """Mitad uniforme hasta 3·R_c, mitad lognormal concentrada cerca del core."""
    return np.concatenate([
        rng.uniform(0.01 * R_c, 3.0 * R_c, n // 2),
        np.clip(rng.lognormal(np.log(R_c), 0.6, n - n // 2), 0.01 * R_c, 3.0 * R_c),
    ])


@st.cache_data(show_spinner=False)
def simulate_tornado(R_c, max_wind, updraft_strength, inflow_angle, n_particles, max_height):
    """Snapshot estático: posiciones al azar y la velocidad del campo en cada una."""
    rng = np.random.default_rng(seed=42)
    r = muestrear_radios(rng, n_particles, R_c)
    theta = rng.uniform(0, 2 * np.pi, n_particles)
    z = rng.uniform(0, max_height, n_particles)
    V_th, V_r, V_z = campo(r, z, R_c, max_wind, np.radians(inflow_angle),
                           updraft_strength, max_height)
    V_tot = np.sqrt(V_th**2 + V_r**2 + V_z**2)
    return r * np.cos(theta), r * np.sin(theta), z, r, V_th, V_r, V_z, V_tot


def dt_animacion(R_c, max_wind):
    """dt por frame: el core gira ~0.5 rad por frame, así el giro se ve continuo."""
    return float(np.clip(0.5 * R_c / max_wind, 0.25, 1.2))


@st.cache_data(show_spinner=False)
def build_animation_frames(R_c, max_wind, updraft_strength, inflow_angle,
                           n_particles, max_height, n_frames):
    n = min(n_particles, ANIM_MAX_PARTICLES)
    rng = np.random.default_rng(seed=7)
    r0 = muestrear_radios(rng, n, R_c)
    r = r0.copy()
    th = rng.uniform(0, 2 * np.pi, n)
    z = rng.uniform(0, max_height, n)
    alpha = np.radians(inflow_angle)
    dt = dt_animacion(R_c, max_wind)
    frames = []

    for _ in range(n_frames):
        r, th, z, V_th, V_r, V_z = paso(r, th, z, dt, R_c, max_wind, alpha,
                                        updraft_strength, max_height)
        # Reciclar las partículas que salen por arriba: vuelven a entrar por abajo
        sale = z > max_height
        n_sale = int(sale.sum())
        if n_sale:
            z[sale] = rng.uniform(0, 0.05 * max_height, n_sale)
            r[sale] = r0[sale]
            th[sale] = rng.uniform(0, 2 * np.pi, n_sale)
        spd = np.sqrt(V_th**2 + V_r**2 + V_z**2)
        # Redondeo a 1 decimal: achica el JSON que viaja al navegador
        frames.append((np.round(r * np.cos(th), 1), np.round(r * np.sin(th), 1),
                       np.round(z, 1), np.round(spd, 1)))
    return frames


@st.cache_data(show_spinner=False)
def compute_trajectory(R_c, max_wind, updraft_strength, inflow_angle,
                       max_height, r_start, theta_deg, t_total):
    """
    Sigue una partícula desde el suelo. El paso se adapta para que gire como
    mucho 0.15 rad por punto, así la hélice sale suave con cualquier viento.
    Retorna x, y, z, rapidez, tiempo y ángulo total girado.
    """
    alpha = np.radians(inflow_angle)
    r, th, z, t = float(max(r_start, 1.0)), np.radians(theta_deg), 0.0, 0.0
    th0 = th
    xs, ys, zs, ts, vs = [r * np.cos(th)], [r * np.sin(th)], [z], [t], []

    while t < t_total and len(xs) < 8000:
        V_th = float(rankine_vtheta(r, R_c, max_wind))
        dt = min(0.5, 0.15 * r / max(V_th, 1e-9), t_total - t)
        r2, th2, z2, a, b, c = paso(r, th, z, dt, R_c, max_wind, alpha,
                                    updraft_strength, max_height)
        r, th, z, t = float(r2), float(th2), float(z2), t + dt
        vs.append(float(np.sqrt(a**2 + b**2 + c**2)))
        if z > max_height:
            break
        xs.append(r * np.cos(th)); ys.append(r * np.sin(th)); zs.append(z); ts.append(t)

    return (np.array(xs), np.array(ys), np.array(zs), np.array(vs),
            np.array(ts), abs(th - th0))


def compute_streamlines(R_c, inflow_angle, n_lines=8, r_ini=2.9, n_pts=300):
    """
    Líneas de flujo del inflow a nivel del suelo. Tienen solución exacta:
      r(θ)² = R_c² + (r₀² − R_c²)·exp(−2·tan(α)·Δθ)
    Lejos del core son espirales logarítmicas; cerca se enrollan sobre la pared.
    """
    ta = np.tan(np.radians(inflow_angle))
    dth = np.linspace(0, 3.0 / ta, n_pts)
    r = R_c * np.sqrt(1.0 + (r_ini**2 - 1.0) * np.exp(-2.0 * ta * dth))
    lineas = []
    for th0 in np.linspace(0, 2 * np.pi, n_lines, endpoint=False):
        th = th0 + SENTIDO * dth
        lineas.append((r * np.cos(th), r * np.sin(th)))
    return lineas


def ajustar_rankine(r, v):
    """
    Ajusta un perfil de Rankine a mediciones (r, v) por mínimos cuadrados.
    Para cada R_c candidato, el V_max óptimo tiene fórmula cerrada
    (V = Σv·g / Σg², con g el perfil normalizado), así que alcanza con barrer R_c.
    Retorna R_c, V_max, RMSE, R² y si el R_c cayó en el borde de los datos.
    """
    r = np.asarray(r, dtype=float)
    v = np.asarray(v, dtype=float)
    cand = np.linspace(r.min(), r.max(), 800)
    g = np.where(r[None, :] <= cand[:, None], r[None, :] / cand[:, None], cand[:, None] / r[None, :])
    V = (g @ v) / np.sum(g**2, axis=1)
    sse = np.sum((v[None, :] - V[:, None] * g)**2, axis=1)
    i = int(np.argmin(sse))
    ss_tot = float(np.sum((v - v.mean())**2))
    r2 = 1.0 - sse[i] / ss_tot if ss_tot > 0 else float("nan")
    en_borde = i == 0 or i == len(cand) - 1
    return float(cand[i]), float(V[i]), float(np.sqrt(sse[i] / len(r))), float(r2), en_borde


# ─── ENCABEZADO Y MÉTRICAS ──────────────────────────────────────────────────────
st.markdown("# 🌪️ TWISTEX — SIMULADOR DE TORNADOS")
nota("Modelo de Vórtice de Rankine · Campo de partículas 3D interactivo · Control en tiempo real",
     size="0.85rem")
st.markdown("---")

x, y, z, r, V_theta, V_r, V_z, V_total = simulate_tornado(
    R_c, max_wind, updraft_strength, inflow_angle, n_particles, max_height)

fuj = get_fujita(max_wind)
dp_central_hpa = RHO_AIRE * max_wind**2 / 100.0
E_total, E_por_m = energia_cinetica_rankine(R_c, max_wind, max_height)
tnt_eq = E_total / TNT_J
circulacion = 2 * np.pi * R_c * max_wind

c1, c2, c3, c4, c5, c6 = st.columns(6)
c1.metric("Radio del core", f"{R_c} m")
c2.metric("Viento máx.", f"{max_wind} m/s", f"{max_wind*3.6:.0f} km/h", delta_color="off")
c3.metric("Escala Fujita", fuj["cat"], fuj["label"], delta_color="off")
c4.metric("Caída de presión", f"−{dp_central_hpa:.1f} hPa",
          help="Déficit de presión en el centro del vórtice ideal (Δp = ρ·V²max).")
c5.metric("Energía cinética", f"{E_total/1e9:,.0f} GJ", f"≈ {tnt_eq:,.0f} t TNT", delta_color="off",
          help="Energía rotacional del vórtice, integrada hasta 3·R_c y en toda la altura simulada.")
c6.metric("Circulación Γ", f"{circulacion/1000:.1f}k m²/s",
          help="Γ = 2π·R_c·V_max. Mide la 'cantidad de giro' del vórtice; es constante fuera del core.")

st.markdown("<br>", unsafe_allow_html=True)

tab1, tab2, tab3, tab4, tab5, tab6, tab7 = st.tabs([
    "📡  VISTA 3D", "▶  ANIMACIÓN", "📊  PERFILES FÍSICOS", "🗺️  VISTA SUPERIOR",
    "🎯  RASTREADOR", "🧪  CALIBRACIÓN", "ℹ️  ACERCA DE",
])


# ══════════════════════════════════════════════════════════════════════════════════
# TAB 1 — VISTA 3D + PANEL FUJITA
# ══════════════════════════════════════════════════════════════════════════════════
with tab1:
    col_plot, col_info = st.columns([3, 1])

    with col_info:
        st.markdown("### ESCALA FUJITA")
        for i, f in enumerate(FUJITA):
            actual = f["cat"] == fuj["cat"]
            borde = f"3px solid {f['color']}" if actual else f"1px solid {f['color']}33"
            dano = (f"<br><span style='{MONO};font-size:0.7rem;color:#c8d8f0'>{f['damage']}</span>"
                    if actual else "")
            st.markdown(
                f"<div style='background:{f['bg']};border:{borde};border-radius:8px;"
                f"padding:8px 12px;margin-bottom:6px;'>"
                f"<span style='font-family:Orbitron,monospace;font-size:1.1rem;font-weight:900;"
                f"color:{f['color']}'>{f['cat']}</span>"
                f"<span style='{MONO};font-size:0.78rem;color:#8ab4d8;margin-left:8px'>{f['label']}</span><br>"
                f"<span style='{MONO};font-size:0.72rem;color:#4a6a8a'>{rango_fujita(i)}</span>"
                f"{dano}</div>", unsafe_allow_html=True)

        st.markdown("<br>", unsafe_allow_html=True)
        sr = SANTA_ROSA_PRESET
        st.markdown(
            f"<div style='background:rgba(74,240,255,0.07);border:1px solid #1a2a4a;"
            f"border-radius:8px;padding:10px;{MONO};font-size:0.78rem;color:#8ab4d8'>"
            f"<b style='color:#4af0ff'>Santa Rosa del Monday</b><br>"
            f"21 de diciembre de 2025 · Alto Paraná<br>"
            f"Clasificación DMH: <b style='color:{FUJITA[1]['color']}'>F1</b><br>"
            f"Ráfagas reportadas: más de 130 km/h<br>"
            f"Zona rural, corta duración<br><br>"
            f"<span style='color:#4a6a8a'>Preset: V_max {sr['max_wind']} m/s "
            f"({sr['max_wind']*3.6:.0f} km/h), R_c {sr['R_c']} m. "
            f"El radio y el updraft son supuestos, no mediciones.</span>"
            f"</div>", unsafe_allow_html=True)

    with col_plot:
        color_map = {
            "Velocidad total":      (V_total, "Plasma",  "Velocidad total [m/s]"),
            "Velocidad tangencial": (V_theta, "Viridis", "V tangencial [m/s]"),
            "Velocidad vertical":   (V_z,     "Cividis", "V vertical [m/s]"),
            "Radio":                (r,       "Turbo",   "Radio desde el eje [m]"),
        }
        c_data, colorscale, c_label = color_map[color_mode]

        fig = go.Figure()
        fig.add_trace(go.Scatter3d(
            x=x, y=y, z=z, mode="markers",
            marker=dict(size=1.8, color=c_data, colorscale=colorscale, opacity=0.85,
                        colorbar=colorbar(c_label, len=0.7, x=1.02)),
            name="Parcelas de aire", customdata=c_data,
            hovertemplate="x:%{x:.0f}m  y:%{y:.0f}m  z:%{z:.0f}m<br>%{customdata:.1f}<extra></extra>",
        ))
        fig.add_trace(go.Scatter3d(
            x=[0, 0], y=[0, 0], z=[0, max_height], mode="lines",
            line=dict(color="rgba(74,240,255,0.7)", width=3),
            name="Eje del vórtice", hoverinfo="skip"))
        phi = np.linspace(0, 2 * np.pi, 120)
        fig.add_trace(go.Scatter3d(
            x=R_c * np.cos(phi), y=R_c * np.sin(phi), z=np.zeros(120), mode="lines",
            line=dict(color="rgba(255,107,53,0.8)", width=2, dash="dot"),
            name=f"Radio del core ({R_c} m)", hoverinfo="skip"))
        fig.update_layout(
            **BASE_LAYOUT, margin=dict(l=0, r=60, t=30, b=0), height=620,
            legend=dict(**LEGEND_STYLE, x=0.01, y=0.99),
            scene=dict(**SCENE, camera=dict(eye=dict(x=1.6, y=1.6, z=0.8), up=dict(x=0, y=0, z=1))))
        st.plotly_chart(fig, width="stretch", config=PLOT_CFG)


# ══════════════════════════════════════════════════════════════════════════════════
# TAB 2 — ANIMACIÓN
# ══════════════════════════════════════════════════════════════════════════════════
with tab2:
    dt_anim = dt_animacion(R_c, max_wind)
    nota_cap = (f" · {ANIM_MAX_PARTICLES:,} de {n_particles:,} partículas por rendimiento"
                if n_particles > ANIM_MAX_PARTICLES else "")
    nota(f"Cada frame avanza {dt_anim:.2f} s de tiempo simulado "
         f"({n_frames * dt_anim:.0f} s en total) · Giro horario, como los tornados ciclónicos "
         f"del hemisferio sur · Presioná REPRODUCIR{nota_cap}")
    st.markdown("<br>", unsafe_allow_html=True)

    with st.spinner(f"Generando {n_frames} frames..."):
        anim_frames = build_animation_frames(
            R_c, max_wind, updraft_strength, inflow_angle, n_particles, max_height, n_frames)

    px0, py0, pz0, spd0 = anim_frames[0]
    vcap = float(max_wind) * 1.1
    lim = 3.1 * R_c

    fig_a = go.Figure(
        data=[
            go.Scatter3d(x=px0, y=py0, z=pz0, mode="markers",
                         marker=dict(size=1.6, color=spd0, colorscale="Plasma",
                                     cmin=0, cmax=vcap, opacity=0.88,
                                     colorbar=colorbar("Velocidad [m/s]", len=0.65, x=1.02)),
                         name="Parcelas de aire", hoverinfo="skip"),
            go.Scatter3d(x=[0, 0], y=[0, 0], z=[0, max_height], mode="lines",
                         line=dict(color="rgba(74,240,255,0.6)", width=3),
                         name="Eje del vórtice", hoverinfo="skip"),
            go.Scatter3d(x=R_c * np.cos(phi), y=R_c * np.sin(phi), z=np.zeros(120),
                         mode="lines", line=dict(color="rgba(255,107,53,0.7)", width=2, dash="dot"),
                         name=f"Core ({R_c} m)", hoverinfo="skip"),
        ],
        frames=[
            go.Frame(data=[go.Scatter3d(x=fx, y=fy, z=fz, mode="markers",
                                        marker=dict(size=1.6, color=fs, colorscale="Plasma",
                                                    cmin=0, cmax=vcap, opacity=0.88))],
                     traces=[0], name=str(i))
            for i, (fx, fy, fz, fs) in enumerate(anim_frames)
        ],
    )
    # Ejes fijos: sin esto Plotly reescala la escena en cada frame y la imagen "respira"
    escena_anim = dict(**SCENE, camera=dict(eye=dict(x=1.7, y=1.7, z=0.7), up=dict(x=0, y=0, z=1)))
    escena_anim["xaxis"] = dict(**axis_style("X [m]"), range=[-lim, lim])
    escena_anim["yaxis"] = dict(**axis_style("Y [m]"), range=[-lim, lim])
    escena_anim["zaxis"] = dict(**axis_style("Altura [m]"), range=[0, max_height])
    fig_a.update_layout(
        **BASE_LAYOUT, margin=dict(l=0, r=60, t=30, b=60), height=700,
        legend=dict(**LEGEND_STYLE, x=0.01, y=0.99), scene=escena_anim,
        updatemenus=[dict(
            type="buttons", showactive=False, y=-0.05, x=0.5, xanchor="center",
            bgcolor="#0d1525", bordercolor="#1a2a4a",
            font=dict(family="Orbitron", color="#4af0ff", size=11),
            buttons=[
                dict(label="  ▶ REPRODUCIR", method="animate",
                     args=[None, {"frame": {"duration": anim_speed, "redraw": True},
                                  "fromcurrent": True, "transition": {"duration": 0},
                                  "mode": "immediate"}]),
                dict(label="  ⏸ PAUSA", method="animate",
                     args=[[None], {"frame": {"duration": 0, "redraw": False},
                                    "mode": "immediate", "transition": {"duration": 0}}]),
            ])],
        sliders=[dict(
            active=0,
            currentvalue=dict(prefix="Frame: ",
                              font=dict(family="Share Tech Mono", color="#4af0ff", size=11)),
            pad=dict(t=10, b=10, l=20, r=20),
            bgcolor="#0d1525", bordercolor="#1a2a4a", tickcolor="#1a2a4a",
            font=dict(family="Share Tech Mono", color="#4a6a8a", size=8),
            steps=[dict(args=[[str(i)], {"frame": {"duration": 0, "redraw": True},
                                         "mode": "immediate", "transition": {"duration": 0}}],
                        label=str(i) if i % 5 == 0 else "", method="animate")
                   for i in range(n_frames)])],
    )
    st.plotly_chart(fig_a, width="stretch", config=PLOT_CFG)


# ══════════════════════════════════════════════════════════════════════════════════
# TAB 3 — PERFILES FÍSICOS
# ══════════════════════════════════════════════════════════════════════════════════
with tab3:
    st.markdown("### PERFIL RADIAL DE VELOCIDAD TANGENCIAL — Curva de Rankine")
    nota("Cómo cambia la velocidad tangencial V_θ con la distancia al eje. "
         "El pico está exactamente en r = R_c.")

    r_arr = np.linspace(0, 3.5 * R_c, 600)
    vt_arr = rankine_vtheta(r_arr, R_c, max_wind)
    r_sr = np.linspace(0, 3.5 * sr["R_c"], 600)
    vt_sr = rankine_vtheta(r_sr, sr["R_c"], sr["max_wind"])
    y_top = max(max_wind, sr["max_wind"]) * 1.25

    fig_r = go.Figure()
    # Bandas Fujita: solo las que entran en el rango visible
    for i, f in enumerate(FUJITA):
        if f["v_min"] >= y_top:
            continue
        y1 = FUJITA[i + 1]["v_min"] if i + 1 < len(FUJITA) else y_top
        fig_r.add_hrect(y0=f["v_min"], y1=min(y1, y_top),
                        fillcolor=f["color"], opacity=0.07, line_width=0,
                        annotation_text=f["cat"], annotation_position="right",
                        annotation_font=dict(family="Orbitron", color=f["color"], size=10))
    fig_r.add_trace(go.Scatter(
        x=r_arr, y=vt_arr, mode="lines", line=dict(color="#4af0ff", width=2.5),
        name=f"Config actual (R_c={R_c} m, V={max_wind} m/s)",
        hovertemplate="r=%{x:.0f} m<br>V_θ=%{y:.1f} m/s<extra></extra>"))
    fig_r.add_trace(go.Scatter(
        x=r_sr, y=vt_sr, mode="lines", line=dict(color="#fbbf24", width=2, dash="dash"),
        name="Santa Rosa del Monday F1 (preset)",
        hovertemplate="r=%{x:.0f} m<br>V_θ=%{y:.1f} m/s<extra></extra>"))
    fig_r.add_vline(x=R_c, line=dict(color="#4af0ff", width=1, dash="dot"),
                    annotation_text=f"R_c = {R_c} m", annotation_position="top right",
                    annotation_font=dict(family="Share Tech Mono", color="#4af0ff", size=11))
    fig_r.update_layout(
        **BASE_LAYOUT, height=380, margin=dict(l=20, r=80, t=30, b=20), legend=LEGEND_STYLE,
        xaxis=axis_2d("Radio desde el eje [m]"),
        yaxis=dict(**axis_2d("Velocidad tangencial V_θ [m/s]"), range=[0, y_top]))
    st.plotly_chart(fig_r, width="stretch", config=PLOT_CFG_MIN)

    st.markdown("---")
    st.markdown("### PERFIL DE PRESIÓN — Balance ciclostrófico")
    nota("Para que el aire gire en círculo, la presión tiene que bajar hacia el centro "
         "(dp/dr = ρ·v²/r). Integrando esa ecuación sobre el perfil de Rankine sale la curva exacta. "
         "La mitad de la caída ocurre fuera del core y la otra mitad adentro.")

    dp_arr = rankine_presion_deficit(r_arr, R_c, max_wind) / 100.0
    dp_sr_arr = rankine_presion_deficit(r_sr, sr["R_c"], sr["max_wind"]) / 100.0

    fig_p = go.Figure()
    fig_p.add_trace(go.Scatter(
        x=r_arr, y=-dp_arr, mode="lines", line=dict(color="#ff6b35", width=2.5),
        fill="tozeroy", fillcolor="rgba(255,107,53,0.08)",
        name=f"Config actual (Δp centro = −{dp_central_hpa:.1f} hPa)",
        hovertemplate="r=%{x:.0f} m<br>Δp=%{y:.1f} hPa<extra></extra>"))
    fig_p.add_trace(go.Scatter(
        x=r_sr, y=-dp_sr_arr, mode="lines", line=dict(color="#fbbf24", width=2, dash="dash"),
        name=f"Santa Rosa F1 (Δp centro = −{RHO_AIRE*sr['max_wind']**2/100:.1f} hPa)",
        hovertemplate="r=%{x:.0f} m<br>Δp=%{y:.1f} hPa<extra></extra>"))
    fig_p.add_vline(x=R_c, line=dict(color="#4af0ff", width=1, dash="dot"),
                    annotation_text=f"R_c = {R_c} m",
                    annotation_font=dict(family="Share Tech Mono", color="#4af0ff", size=11))
    fig_p.update_layout(
        **BASE_LAYOUT, height=360, margin=dict(l=20, r=40, t=30, b=20), legend=LEGEND_STYLE,
        xaxis=axis_2d("Radio desde el eje [m]"),
        yaxis=axis_2d("Presión respecto al ambiente [hPa]"))
    st.plotly_chart(fig_p, width="stretch", config=PLOT_CFG_MIN)
    nota("El vórtice de Rankine ideal sobreestima Δp en tornados violentos porque ignora la fricción "
         "y la turbulencia. La mayor caída medida dentro de un tornado con instrumentos en el suelo "
         "es de unos 100 hPa (F4 de Manchester, Dakota del Sur, 2003). "
         "Para F0–F2 la aproximación es razonable.", color="#2a4a6a", size="0.75rem")

    st.markdown("---")
    st.markdown("### PERFIL VERTICAL DE UPDRAFT")
    nota("Velocidad vertical V_z según la altura. En este modelo crece linealmente hacia arriba; "
         "es un perfil prescrito, no un resultado.")

    z_arr = np.linspace(0, max_height, 200)
    perfil_z = 0.5 + 0.5 * z_arr / max_height
    fig_z = go.Figure()
    fig_z.add_trace(go.Scatter(
        x=updraft_strength * perfil_z, y=z_arr, mode="lines",
        line=dict(color="#4af0ff", width=2.5), name="En el eje (r = 0)",
        hovertemplate="V_z=%{x:.1f} m/s<br>z=%{y:.0f} m<extra></extra>"))
    fig_z.add_trace(go.Scatter(
        x=updraft_strength * np.exp(-0.5) * perfil_z, y=z_arr, mode="lines",
        line=dict(color="#7b5fff", width=2, dash="dash"), name=f"En la pared del core (r = {R_c} m)",
        hovertemplate="V_z=%{x:.1f} m/s<br>z=%{y:.0f} m<extra></extra>"))
    fig_z.update_layout(
        **BASE_LAYOUT, height=340, margin=dict(l=20, r=40, t=30, b=20), legend=LEGEND_STYLE,
        xaxis=dict(**axis_2d("Velocidad vertical V_z [m/s]"), rangemode="tozero"),
        yaxis=axis_2d("Altura [m]"))
    st.plotly_chart(fig_z, width="stretch", config=PLOT_CFG_MIN)


# ══════════════════════════════════════════════════════════════════════════════════
# TAB 4 — VISTA SUPERIOR
# ══════════════════════════════════════════════════════════════════════════════════
with tab4:
    st.markdown("### CORTE TRANSVERSAL — Vista desde arriba")
    nota("Proyección XY de las partículas. Las líneas verdes son las líneas de flujo a nivel del suelo: "
         "el aire entra en espiral y se enrolla sobre la pared del core, donde gira hacia arriba. "
         "Color = velocidad total.")

    fig_top = go.Figure()
    fig_top.add_trace(go.Scatter(
        x=x, y=y, mode="markers",
        marker=dict(size=2.5, color=V_total, colorscale="Plasma", opacity=0.7,
                    colorbar=colorbar("Velocidad [m/s]")),
        name="Parcelas de aire", hoverinfo="skip"))
    for i, (sx, sy) in enumerate(compute_streamlines(R_c, inflow_angle)):
        fig_top.add_trace(go.Scatter(
            x=sx, y=sy, mode="lines", line=dict(color="rgba(110,231,183,0.6)", width=1.5),
            name="Líneas de flujo (inflow)", legendgroup="flujo",
            showlegend=(i == 0), hoverinfo="skip"))
    phi_c = np.linspace(0, 2 * np.pi, 200)
    fig_top.add_trace(go.Scatter(
        x=R_c * np.cos(phi_c), y=R_c * np.sin(phi_c), mode="lines",
        line=dict(color="rgba(255,107,53,0.9)", width=2, dash="dot"),
        name=f"Radio del core ({R_c} m)", hoverinfo="skip"))
    fig_top.add_trace(go.Scatter(
        x=2 * R_c * np.cos(phi_c), y=2 * R_c * np.sin(phi_c), mode="lines",
        line=dict(color="rgba(74,240,255,0.3)", width=1, dash="dot"),
        name=f"2× radio del core ({2*R_c} m)", hoverinfo="skip"))
    fig_top.add_trace(go.Scatter(
        x=[0], y=[0], mode="markers",
        marker=dict(size=10, color="#4af0ff", symbol="circle-open", line=dict(width=2)),
        name="Eje del vórtice", hoverinfo="skip"))
    fig_top.update_layout(
        **BASE_LAYOUT, height=600, margin=dict(l=20, r=80, t=30, b=20),
        legend=dict(**LEGEND_STYLE, x=0.01, y=0.99),
        xaxis=dict(**axis_2d("X [m]"), scaleanchor="y", scaleratio=1),
        yaxis=axis_2d("Y [m]"))
    st.plotly_chart(fig_top, width="stretch", config=PLOT_CFG)

    st.markdown("---")
    zonas = [
        ("#ff6b35", "rgba(255,107,53,0.1)", "ZONA CORE", f"r &lt; {R_c} m",
         f"Rotación sólida: la velocidad crece linealmente hasta {max_wind} m/s en el borde. "
         f"Ahí está la presión más baja."),
        ("#7b5fff", "rgba(123,95,255,0.1)", "PARED DEL VÓRTICE", f"r ≈ {R_c}–{2*R_c} m",
         f"Vientos máximos y mayor daño. A {2*R_c} m el viento ya cayó a {max_wind/2:.0f} m/s."),
        ("#4af0ff", "rgba(74,240,255,0.07)", "ZONA EXTERIOR", f"r &gt; {2*R_c} m",
         "Flujo irrotacional: la velocidad decae como 1/r. El aire entra en espiral hacia el core."),
    ]
    for col, (color, bg, titulo, rango, desc) in zip(st.columns(3), zonas):
        col.markdown(
            f"<div style='background:{bg};border:1px solid {color}66;border-radius:8px;"
            f"padding:10px;{MONO};font-size:0.8rem;color:#8ab4d8'>"
            f"<b style='color:{color}'>{titulo}</b><br>{rango}<br>{desc}</div>",
            unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════════════════════════
# TAB 5 — RASTREADOR DE PARTÍCULA
# ══════════════════════════════════════════════════════════════════════════════════
with tab5:
    st.markdown("### TRAYECTORIA DE UNA PARTÍCULA")
    nota("Soltá una partícula a nivel del suelo y seguila. Si arranca fuera del core, entra en espiral "
         "hasta la pared y recién ahí empieza a subir. Si arranca adentro, sube girando a radio constante.")
    st.markdown("<br>", unsafe_allow_html=True)

    cc1, cc2, cc3 = st.columns(3)
    track_r = cc1.slider("Radio inicial [m]", 10, 3 * R_c, min(100, 3 * R_c), 10,
                         help="Distancia inicial al eje del vórtice.")
    track_theta = cc2.slider("Ángulo inicial [°]", 0, 355, 45, 5, help="Posición angular de partida.")
    track_t = cc3.slider("Tiempo simulado [s]", 10, 300, 90, 10,
                         help="La simulación corta antes si la partícula sale por la cima.")

    tx, ty, tz, tv, tt, giro = compute_trajectory(
        R_c, max_wind, updraft_strength, inflow_angle, max_height, track_r, track_theta, track_t)

    fig_tr = go.Figure()
    fig_tr.add_trace(go.Scatter3d(
        x=x[::4], y=y[::4], z=z[::4], mode="markers",
        marker=dict(size=1.2, color="#1a2a4a", opacity=0.3),
        name="Campo de fondo", hoverinfo="skip"))
    fig_tr.add_trace(go.Scatter3d(
        x=tx, y=ty, z=tz, mode="lines",
        line=dict(width=5, color=tt, colorscale=[[0, "#fbbf24"], [0.5, "#ff6b35"], [1, "#7b5fff"]]),
        name="Trayectoria", customdata=tt,
        hovertemplate="t=%{customdata:.1f} s<br>x:%{x:.0f}m y:%{y:.0f}m z:%{z:.0f}m<extra></extra>"))
    fig_tr.add_trace(go.Scatter3d(
        x=[tx[0]], y=[ty[0]], z=[tz[0]], mode="markers",
        marker=dict(size=7, color="#6ee7b7", symbol="circle"), name="Inicio"))
    fig_tr.add_trace(go.Scatter3d(
        x=[tx[-1]], y=[ty[-1]], z=[tz[-1]], mode="markers",
        marker=dict(size=6, color="#ef4444", symbol="x"), name="Fin"))
    fig_tr.add_trace(go.Scatter3d(
        x=[0, 0], y=[0, 0], z=[0, max_height], mode="lines",
        line=dict(color="rgba(74,240,255,0.5)", width=2),
        name="Eje del vórtice", hoverinfo="skip"))
    fig_tr.update_layout(
        **BASE_LAYOUT, margin=dict(l=0, r=40, t=30, b=0), height=580,
        legend=dict(**LEGEND_STYLE, x=0.01, y=0.99),
        scene=dict(**SCENE, camera=dict(eye=dict(x=1.5, y=1.5, z=0.9), up=dict(x=0, y=0, z=1))))
    st.plotly_chart(fig_tr, width="stretch", config=PLOT_CFG)

    st.markdown("---")
    s1, s2, s3, s4, s5 = st.columns(5)
    s1.metric("Tiempo de vuelo", f"{tt[-1]:.0f} s")
    s2.metric("Altura alcanzada", f"{tz[-1]:.0f} m")
    s3.metric("Velocidad máxima", f"{tv.max():.1f} m/s" if len(tv) else "—")
    s4.metric("Distancia recorrida",
              f"{np.sum(np.sqrt(np.diff(tx)**2 + np.diff(ty)**2 + np.diff(tz)**2)):,.0f} m")
    s5.metric("Vueltas al eje", f"{giro / (2*np.pi):.1f}")
    if tz[-1] < 0.05 * max_height:
        nota("Esta partícula casi no subió: lejos del eje el updraft es muy débil. "
             "Probá un radio inicial menor o más tiempo.", color="#fbbf24")


# ══════════════════════════════════════════════════════════════════════════════════
# TAB 6 — CALIBRACIÓN CON DATOS DEL PROTOTIPO
# ══════════════════════════════════════════════════════════════════════════════════
with tab6:
    st.markdown("### CALIBRACIÓN CON EL PROTOTIPO FÍSICO")
    nota("Cargá mediciones del anemómetro en la cámara de acrílico (distancia al eje y velocidad) "
         "y la app ajusta el perfil de Rankine que mejor las explica. Así se compara el modelo "
         "con el vórtice real del laboratorio.")
    st.markdown("<br>", unsafe_allow_html=True)

    EJEMPLO = pd.DataFrame({
        "r [cm]":  [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 8.0, 10.0, 12.0, 14.0],
        "v [m/s]": [0.9, 1.5, 2.5, 3.0, 2.7, 2.2, 1.5, 1.4, 1.0, 0.9],
    })

    col_datos, col_fit = st.columns([1, 2])
    with col_datos:
        archivo = st.file_uploader("CSV con dos columnas: r [cm], v [m/s]", type=["csv"])
        datos, es_ejemplo = EJEMPLO, True
        if archivo is not None:
            try:
                leido = pd.read_csv(archivo, sep=None, engine="python")
                leido = leido.apply(pd.to_numeric, errors="coerce").dropna(axis=1, how="all")
                datos = leido.iloc[:, :2].copy()
                datos.columns = ["r [cm]", "v [m/s]"]
                es_ejemplo = False
            except Exception as e:
                st.error(f"No pude leer el CSV: {e}")
        if es_ejemplo:
            nota("Estos son DATOS DE EJEMPLO inventados para mostrar cómo funciona. "
                 "Reemplazalos por tus mediciones (podés editar la tabla o subir un CSV).",
                 color="#fbbf24", size="0.78rem")
        datos = st.data_editor(datos, num_rows="dynamic", width="stretch", hide_index=True,
                               key=f"editor_{'ej' if es_ejemplo else archivo.name}")

    with col_fit:
        limpio = datos.apply(pd.to_numeric, errors="coerce").dropna()
        limpio = limpio[(limpio.iloc[:, 0] > 0) & (limpio.iloc[:, 1] >= 0)]
        if len(limpio) < 4 or limpio.iloc[:, 0].nunique() < 3:
            st.warning("Hacen falta al menos 4 mediciones en 3 radios distintos para ajustar.")
        else:
            r_m = limpio.iloc[:, 0].to_numpy()
            v_m = limpio.iloc[:, 1].to_numpy()
            rc_fit, v_fit, rmse, r2, en_borde = ajustar_rankine(r_m, v_m)

            r_plot = np.linspace(0, r_m.max() * 1.25, 400)
            fig_c = go.Figure()
            fig_c.add_trace(go.Scatter(
                x=r_plot, y=rankine_vtheta(r_plot, rc_fit, v_fit), mode="lines",
                line=dict(color="#4af0ff", width=2.5), name="Rankine ajustado"))
            fig_c.add_trace(go.Scatter(
                x=r_m, y=v_m, mode="markers",
                marker=dict(size=9, color="#ff6b35", line=dict(color="#ffffff", width=1)),
                name="Mediciones" + (" (ejemplo)" if es_ejemplo else "")))
            fig_c.add_vline(x=rc_fit, line=dict(color="#4af0ff", width=1, dash="dot"),
                            annotation_text=f"R_c = {rc_fit:.1f} cm",
                            annotation_font=dict(family="Share Tech Mono", color="#4af0ff", size=11))
            fig_c.update_layout(
                **BASE_LAYOUT, height=380, margin=dict(l=20, r=20, t=30, b=20), legend=LEGEND_STYLE,
                xaxis=axis_2d("Distancia al eje r [cm]"),
                yaxis=dict(**axis_2d("Velocidad tangencial [m/s]"), rangemode="tozero"))
            st.plotly_chart(fig_c, width="stretch", config=PLOT_CFG_MIN)

            m1, m2, m3, m4 = st.columns(4)
            m1.metric("R_c ajustado", f"{rc_fit:.1f} cm")
            m2.metric("V_max ajustado", f"{v_fit:.2f} m/s")
            m3.metric("R²", f"{r2:.3f}", help="1 = el modelo explica toda la variación de los datos.")
            m4.metric("Error RMSE", f"{rmse:.2f} m/s",
                      help="Diferencia típica entre el modelo y cada medición.")
            m5, m6, m7, _ = st.columns(4)
            m5.metric("Giro del core", f"{v_fit / (rc_fit/100) / (2*np.pi) * 60:,.0f} rpm")
            m6.metric("Δp central", f"{RHO_AIRE * v_fit**2:.1f} Pa",
                      help="Caída de presión que predice el modelo en el eje (ρ·V²max).")
            m7.metric("Circulación Γ", f"{2*np.pi*(rc_fit/100)*v_fit:.2f} m²/s")

            if en_borde:
                st.warning("El R_c ajustado cayó en el borde de tus mediciones, así que no está bien "
                           "determinado. Faltan puntos del otro lado del pico: medí más cerca del eje "
                           "o más lejos.")
            nota("El ajuste barre R_c y, para cada uno, calcula el V_max óptimo por mínimos cuadrados. "
                 "Un R² bajo no es un fracaso: dice cuánto se aparta el vórtice real del ideal "
                 "(fricción con las paredes, turbulencia, el propio anemómetro perturbando el flujo).",
                 color="#2a4a6a", size="0.75rem")


# ══════════════════════════════════════════════════════════════════════════════════
# TAB 7 — ACERCA DE
# ══════════════════════════════════════════════════════════════════════════════════
with tab7:

    def card(titulo, icono, color, contenido):
        st.markdown(
            f"<div style='background:rgba(255,255,255,0.03);border:1px solid {color}44;"
            f"border-left:4px solid {color};border-radius:10px;padding:18px 22px;margin-bottom:16px;'>"
            f"<div style='font-family:Orbitron,monospace;font-size:1rem;font-weight:700;"
            f"color:{color};margin-bottom:10px'>{icono} {titulo}</div>"
            f"<div style='{MONO};font-size:0.85rem;color:#c8d8f0;line-height:1.7'>{contenido}</div>"
            f"</div>", unsafe_allow_html=True)

    st.markdown(
        f"<div style='background:linear-gradient(135deg,rgba(74,240,255,0.08) 0%,rgba(123,95,255,0.08) 100%);"
        f"border:1px solid rgba(74,240,255,0.2);border-radius:14px;padding:28px 32px;"
        f"margin-bottom:24px;text-align:center;'>"
        f"<div style='font-family:Orbitron,monospace;font-size:1.8rem;font-weight:900;"
        f"background:linear-gradient(135deg,#4af0ff,#7b5fff,#ff6b35);-webkit-background-clip:text;"
        f"-webkit-text-fill-color:transparent;background-clip:text;margin-bottom:10px'>"
        f"🌪️ TWISTEX — SIMULADOR DE TORNADOS</div>"
        f"<div style='{MONO};font-size:0.9rem;color:#8ab4d8'>"
        f"Proyecto Científico · SIL 2026 · Basado en el tornado F1 de Santa Rosa del Monday, "
        f"Paraguay (diciembre de 2025)</div></div>", unsafe_allow_html=True)

    card("¿QUÉ ES ESTA APP?", "🤔", "#4af0ff",
         """Una <b style='color:#4af0ff'>simulación computacional interactiva</b> de un tornado,
         desarrollada como proyecto científico escolar. Es la mitad computacional de un proyecto
         con dos partes: un simulador físico de vórtices (cámara de acrílico, ventiladores y
         sensores con Arduino) y este modelo en Python.<br><br>
         Todo lo que ves (las partículas, los gráficos, los números) se calcula en el momento con
         fórmulas de mecánica de fluidos. Cambiá los parámetros del panel lateral y el vórtice
         se recalcula.""")

    card("¿DE DÓNDE VIENE LA IDEA?", "💡", "#fbbf24",
         """El <b style='color:#fbbf24'>21 de diciembre de 2025</b> un tornado golpeó una zona rural
         de <b style='color:#fbbf24'>Santa Rosa del Monday, Alto Paraná</b>. Al día siguiente la
         Dirección de Meteorología e Hidrología lo confirmó como F1, con ráfagas de más de 130 km/h.
         Es uno de los tornados mejor documentados de los últimos años en Paraguay.<br><br>
         Paraguay está dentro del <b>corredor de tornados de Sudamérica</b>, considerada la segunda
         región más activa del mundo después de Estados Unidos, y no cuenta con radares capaces de
         detectar tornados en formación. De ahí la pregunta:
         <i>¿podemos modelar matemáticamente cómo funciona un tornado como ese?</i><br><br>
         El botón <b style='color:#ff6b35'>⚡ Preset Santa Rosa del Monday</b> carga parámetros
         compatibles con ese evento.""")

    card("¿CÓMO FUNCIONA LA SIMULACIÓN?", "⚙️", "#7b5fff",
         """La base es el <b style='color:#7b5fff'>vórtice de Rankine</b>, el modelo idealizado más
         simple de un vórtice y el punto de partida habitual para describir tornados. Tiene dos zonas:<br><br>
         &nbsp;&nbsp;🔴 <b>Core</b>: el aire rota como un sólido rígido, más rápido cuanto más lejos del eje.<br>
         &nbsp;&nbsp;🔵 <b>Exterior</b>: el viento se debilita con la distancia, siguiendo la ley 1/r.<br><br>
         A eso se suman tres piezas. El <b>inflow</b>: aire que entra en espiral cerca del suelo y se
         frena en la pared del core. El <b>updraft</b>: la corriente vertical, más fuerte en el eje.
         Y el <b>perfil de presión</b>, que sale de exigir que la presión sostenga el giro
         (balance ciclostrófico, dp/dr = ρ·v²/r).<br><br>
         El vórtice gira en sentido horario visto desde arriba, como la mayoría de los tornados del
         hemisferio sur.""")

    st.markdown(
        "<div style='font-family:Orbitron,monospace;font-size:1rem;font-weight:700;"
        "color:#4af0ff;margin:8px 0 14px 0'>📂 ¿QUÉ HACE CADA PESTAÑA?</div>",
        unsafe_allow_html=True)

    tabs_info = [
        ("📡 VISTA 3D", "#4af0ff", "El campo de viento en 3D. Rotá, hacé zoom y cambiá qué variable colorea las partículas. A la derecha, la escala Fujita y dónde cae tu configuración."),
        ("▶ ANIMACIÓN", "#7b5fff", "Las partículas se mueven siguiendo el campo de velocidades: giran, entran hacia la pared del core y suben."),
        ("📊 PERFILES FÍSICOS", "#fbbf24", "La curva de Rankine, el perfil de presión y el perfil vertical del updraft, comparados con el preset de Santa Rosa."),
        ("🗺️ VISTA SUPERIOR", "#6ee7b7", "El vórtice visto desde arriba, con las líneas de flujo del inflow y las tres zonas: core, pared y exterior."),
        ("🎯 RASTREADOR", "#ff6b35", "Elegí dónde soltar una partícula y seguí su recorrido. Muestra cuánto tarda en subir y cuántas vueltas da."),
        ("🧪 CALIBRACIÓN", "#4af0ff", "Ajusta el modelo de Rankine a las mediciones del anemómetro del prototipo físico y dice qué tan bien las explica."),
    ]
    for nombre, color, desc in tabs_info:
        st.markdown(
            f"<div style='display:flex;align-items:flex-start;gap:14px;background:rgba(255,255,255,0.02);"
            f"border:1px solid {color}33;border-radius:8px;padding:12px 16px;margin-bottom:10px;'>"
            f"<div style='font-family:Orbitron,monospace;font-size:0.85rem;font-weight:700;"
            f"color:{color};min-width:190px;padding-top:2px'>{nombre}</div>"
            f"<div style='{MONO};font-size:0.83rem;color:#c8d8f0;line-height:1.6'>{desc}</div>"
            f"</div>", unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)
    card("¿QUÉ SIGNIFICAN LAS MÉTRICAS?", "📐", "#6ee7b7",
         """<b style='color:#6ee7b7'>Caída de presión (Δp)</b>. El centro del vórtice tiene menos
         presión que el aire de afuera: Δp = ρ·V²max. Un F1 da entre 13 y 30 hPa; un F5 supera los
         170 hPa según este modelo ideal.<br><br>
         <b style='color:#6ee7b7'>¿Qué rompe las casas?</b> Sobre todo el viento y los objetos que
         arrastra. La idea de que las casas "explotan" por la baja presión es un mito: las viviendas
         no son herméticas y la presión se iguala rápido. Los techos se levantan porque el viento que
         pasa por encima genera sustentación, como en el ala de un avión. Un viento de 40 m/s ejerce
         una presión dinámica de ½ρV² ≈ 980 Pa, del orden de 10 toneladas sobre un techo de 100 m².<br><br>
         <b style='color:#6ee7b7'>Energía cinética</b>. La energía de rotación del vórtice, integrando
         ½ρv² hasta 3 veces el radio del core y en toda la altura simulada. El equivalente en TNT es
         solo para dimensionar.<br><br>
         <b style='color:#6ee7b7'>Circulación (Γ)</b>. Γ = 2π·R_c·V_max. Resume cuánto giro tiene el
         vórtice en un solo número y permite comparar vórtices de tamaños distintos, por ejemplo
         el del laboratorio con uno real.""")

    card("¿CON QUÉ ESTÁ HECHO?", "🛠️", "#ff6b35",
         """Programado en <b style='color:#ff6b35'>Python</b>:<br><br>
         &nbsp;&nbsp;🔢 <b>NumPy</b> para los cálculos del modelo, vectorizados.<br>
         &nbsp;&nbsp;📊 <b>Plotly</b> para los gráficos 3D interactivos.<br>
         &nbsp;&nbsp;🌐 <b>Streamlit</b> para convertir el código en esta página web.<br>
         &nbsp;&nbsp;🧮 <b>pandas</b> para leer las mediciones del prototipo.""")

    card("¿QUÉ NO PUEDE HACER ESTA SIMULACIÓN?", "⚠️", "#ef4444",
         """❌ <b>No predice</b> cuándo ni dónde va a ocurrir un tornado.<br>
         ❌ <b>No simula la formación</b> del tornado ni su disipación: es un vórtice ya formado y
         estacionario. Eso requeriría resolver las ecuaciones de Navier-Stokes.<br>
         ❌ <b>Es un modelo cinemático</b>: el inflow y el updraft son perfiles elegidos a mano, no
         salen de las ecuaciones, y no conservan la masa de forma exacta.<br>
         ❌ <b>No incluye</b> terreno, humedad, temperatura ni fricción con el suelo.<br>
         ❌ Del tornado de Santa Rosa solo se conocen la categoría y el rango de ráfagas. El radio del
         core, el updraft y la altura del preset son <b>supuestos</b>.<br><br>
         ✅ Lo que sí hace: representar la <b>estructura de velocidades</b> y el <b>campo de presión</b>
         de un vórtice ideal con soluciones analíticas que se pueden verificar a mano, y contrastar
         ese modelo con mediciones reales del prototipo.""")

    st.markdown(
        f"<div style='text-align:center;margin-top:30px;padding:20px;border-top:1px solid #1a2a4a;"
        f"{MONO};font-size:0.8rem;color:#2a4a6a;'>"
        f"Twistex · Proyecto Científico · Intercolegial SIL 2026 · Paraguay<br>"
        f"Modelo: vórtice combinado de Rankine + balance ciclostrófico · "
        f"Python + NumPy + Plotly + Streamlit</div>", unsafe_allow_html=True)
