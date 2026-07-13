# graficos.py
import plotly.graph_objects as go
from plotly.subplots import make_subplots


def crear_grafico_clima(df):
    """
    Recibe un DataFrame con columnas:
      - fecha  (datetime o str con formato YYYY-MM-DD)
      - tmax   (temperatura máxima)
      - tmin   (temperatura mínima)
      - tmed   (temperatura media)
      - prec   (precipitación en mm)

    Devuelve el HTML del gráfico listo para embeber en Jinja2.
    """
    fig = make_subplots(
        rows=2, cols=1,
        subplot_titles=("🌡️ Temperatura (°C)", "🌧️ Precipitación (mm)"),
        vertical_spacing=0.12,
        shared_xaxes=True   # Las dos gráficas comparten el eje X (fechas)
    )

    # ── Fila 1: Temperaturas ──────────────────────────────────────
    fig.add_trace(
        go.Scatter(
            x=df["fecha"], y=df["tmax"],
            name="T. máxima",
            mode="lines",
            line=dict(color="#EF4444", width=2),
            hovertemplate="%{x|%d %b %Y}<br>Tmax: <b>%{y:.1f} °C</b><extra></extra>"
        ),
        row=1, col=1
    )
    fig.add_trace(
        go.Scatter(
            x=df["fecha"], y=df["tmin"],
            name="T. mínima",
            mode="lines",
            line=dict(color="#3B82F6", width=2),
            fill="tonexty",           # Rellena la banda entre Tmax y Tmin
            fillcolor="rgba(59,130,246,0.10)",
            hovertemplate="%{x|%d %b %Y}<br>Tmin: <b>%{y:.1f} °C</b><extra></extra>"
        ),
        row=1, col=1
    )
    fig.add_trace(
        go.Scatter(
            x=df["fecha"], y=df["tmed"],
            name="T. media",
            mode="lines+markers",
            line=dict(color="#F59E0B", width=2, dash="dot"),
            marker=dict(size=4),
            hovertemplate="%{x|%d %b %Y}<br>Tmed: <b>%{y:.1f} °C</b><extra></extra>"
        ),
        row=1, col=1
    )

    # ── Fila 2: Precipitación ─────────────────────────────────────
    fig.add_trace(
        go.Bar(
            x=df["fecha"], y=df["prec"],
            name="Precipitación",
            marker_color="#0059C9",
            opacity=0.8,
            hovertemplate="%{x|%d %b %Y}<br>Prec: <b>%{y:.1f} mm</b><extra></extra>"
        ),
        row=2, col=1
    )

    # ── Selector y slider de fechas ───────────────────────────────
    fig.update_layout(
        height=550,
        template="plotly_white",
        legend=dict(orientation="h", y=1.08, x=0.5, xanchor="center"),
        margin=dict(t=80, b=40, l=60, r=20),
        hovermode="x unified",   # Muestra todos los valores al pasar el ratón
        xaxis=dict(
            rangeselector=dict(
                buttons=[
                    dict(count=7,  label="7 días", step="day",   stepmode="backward"),
                    dict(count=14, label="14 días", step="day",   stepmode="backward"),
                    dict(count=1,  label="1 mes",  step="month", stepmode="backward"),
                    dict(count=3,  label="3 meses", step="month", stepmode="backward"),
                    dict(step="all", label="Todo"),
                ],
                bgcolor="#F9FAFB",
                activecolor="#0059C9",
                font=dict(color="#191A1F"),
            ),
            rangeslider=dict(visible=True, thickness=0.06),
            type="date",
        )
    )

    # El HTML resultante se puede pegar directamente en Jinja2
    return fig.to_html(full_html=False, include_plotlyjs="cdn")
