import json
from pathlib import Path
from shiny import App, ui, reactive, render

# Load routes GeoJSON once at startup
DATA_PATH = Path(__file__).parent / "data" / "routes_lines.geojson"
with open(DATA_PATH, "r", encoding="utf-8") as f:
    ROUTES_GEOJSON = json.load(f)

# Extract sorted unique route names and trip counts
route_counts = {}
for feat in ROUTES_GEOJSON.get("features", []):
    r = feat["properties"].get("route", "Unknown")
    route_counts[r] = route_counts.get(r, 0) + 1

PREFERRED_ORDER = [
    "City Loop",
    "Mt Eden Loop",
    "Epsom",
    "Parnell Loop",
    "Tamaki Drive Loop",
    "Ponsonby Loop",
    "Orakei Loop",
    "Northwestern Cycleway"
]

ROUTE_NAMES = [r for r in PREFERRED_ORDER if r in route_counts] + [
    r for r in sorted(route_counts.keys()) if r not in PREFERRED_ORDER
]

# 8 high-contrast colors designed to pop over both street maps and warm NO2 overlays
PALETTE = [
    "#00b4d8",  # Electric Cyan
    "#2563eb",  # Cobalt Blue
    "#059669",  # Emerald Green
    "#7c3aed",  # Royal Violet
    "#e11d48",  # Crimson Rose
    "#0d9488",  # Deep Teal
    "#4f46e5",  # Indigo
    "#d97706",  # Amber Gold
]
ROUTE_COLORS = {r: PALETTE[i % len(PALETTE)] for i, r in enumerate(ROUTE_NAMES)}

# Build MapLibre match expression: ["match", ["get", "route"], r1, c1, r2, c2, ..., default]
COLOR_MATCH_EXPR = ["match", ["get", "route"]]
for r, c in ROUTE_COLORS.items():
    COLOR_MATCH_EXPR.extend([r, c])
COLOR_MATCH_EXPR.append("#64748b")

app_ui = ui.page_fillable(
    ui.tags.head(
        ui.tags.link(
            rel="stylesheet",
            href="https://unpkg.com/maplibre-gl@4.7.1/dist/maplibre-gl.css",
        ),
        ui.tags.script(
            src="https://unpkg.com/maplibre-gl@4.7.1/dist/maplibre-gl.js"
        ),
        ui.tags.style(
            """
            body, html { margin: 0; padding: 0; height: 100%; font-family: system-ui, -apple-system, sans-serif; }
            #map { width: 100%; height: 100%; min-height: 550px; border-radius: 8px; }
            .legend-item {
                display: flex; align-items: center; justify-content: space-between;
                padding: 6px 8px; border-radius: 6px; cursor: pointer;
                font-size: 13px; transition: background 0.15s;
            }
            .legend-item:hover { background: #f1f5f9; }
            .legend-swatch {
                width: 18px; height: 5px; border-radius: 3px;
                margin-right: 8px; flex-shrink: 0;
            }
            .maplibregl-popup-content {
                font-family: system-ui, sans-serif; font-size: 13px; padding: 8px 12px;
            }
            """
        ),
    ),
    ui.layout_sidebar(
        ui.sidebar(
            ui.h4("Auckland Cycling Routes", style="margin-top:0; font-weight:700;"),
            ui.p(
                "Semi-transparent trip trajectories stack by overlap intensity—darker, brighter strokes indicate frequently travelled roads.",
                style="font-size: 12.5px; color: #475569; margin-bottom: 12px;",
            ),
            ui.input_select(
                "selected_route",
                "Filter Route Corridor",
                choices={"ALL": f"All Routes ({len(ROUTES_GEOJSON['features'])} trips)"}
                | {r: f"{r} ({route_counts[r]})" for r in ROUTE_NAMES},
                selected="ALL",
            ),
            ui.hr(style="margin: 12px 0;"),
            ui.div(
                ui.strong("Route Corridors", style="font-size: 12px; text-transform: uppercase; color: #64748b;"),
                ui.div(
                    *[
                        ui.div(
                            ui.div(
                                ui.span(
                                    class_="legend-swatch",
                                    style=f"background-color: {ROUTE_COLORS[r]};",
                                ),
                                ui.span(r),
                                style="display:flex; align-items:center;",
                            ),
                            ui.span(
                                f"{route_counts[r]}",
                                style="color:#64748b; font-size:12px; font-weight:600;",
                            ),
                            class_="legend-item",
                            onclick=f"Shiny.setInputValue('selected_route', {json.dumps(r)}, {{priority: 'event'}});",
                            onmouseenter=f"window.highlightRoute && window.highlightRoute({json.dumps(r)});",
                            onmouseleave="window.highlightRoute && window.highlightRoute(null);",
                        )
                        for r in ROUTE_NAMES
                    ],
                    style="margin-top: 6px;",
                ),
            ),
            ui.hr(style="margin: 12px 0;"),
            ui.output_ui("route_summary"),
            width=310,
        ),
        ui.div(id="map"),
        ui.tags.script(
            f"""
            const routesData = {json.dumps(ROUTES_GEOJSON)};
            const colorExpr = {json.dumps(COLOR_MATCH_EXPR)};

            const map = new maplibregl.Map({{
                container: 'map',
                style: 'https://basemaps.cartocdn.com/gl/positron-gl-style/style.json',
                center: [174.768, -36.855],
                zoom: 12.2
            }});

            map.addControl(new maplibregl.NavigationControl(), 'top-right');

            let currentSelected = 'ALL';

            map.on('load', () => {{
                map.addSource('routes', {{
                    type: 'geojson',
                    data: routesData
                }});

                map.addLayer({{
                    id: 'routes-lines',
                    type: 'line',
                    source: 'routes',
                    layout: {{
                        'line-join': 'round',
                        'line-cap': 'round'
                    }},
                    paint: {{
                        'line-color': colorExpr,
                        'line-width': [
                            'interpolate', ['linear'], ['zoom'],
                            10, 2.0,
                            13, 3.5,
                            16, 6.0
                        ],
                        'line-opacity': 0.25
                    }}
                }});

                // Fit map bounds to all routes
                const bounds = new maplibregl.LngLatBounds();
                routesData.features.forEach(f => {{
                    f.geometry.coordinates.forEach(coord => bounds.extend(coord));
                }});
                if (!bounds.isEmpty()) {{
                    map.fitBounds(bounds, {{ padding: 45, maxZoom: 14 }});
                }}

                // Hover tooltip & cursor
                const popup = new maplibregl.Popup({{ closeButton: false, closeOnClick: false }});

                map.on('mousemove', 'routes-lines', (e) => {{
                    map.getCanvas().style.cursor = 'pointer';
                    if (e.features && e.features.length > 0) {{
                        const props = e.features[0].properties;
                        popup
                            .setLngLat(e.lngLat)
                            .setHTML(`<strong>${{props.route}}</strong><br><span style="color:#64748b">Trip: ${{props.trip_id}}</span>`)
                            .addTo(map);
                    }}
                }});

                map.on('mouseleave', 'routes-lines', () => {{
                    map.getCanvas().style.cursor = '';
                    popup.remove();
                }});

                // Click a corridor on the map to filter to that route
                map.on('click', 'routes-lines', (e) => {{
                    if (e.features && e.features.length > 0) {{
                        const clickedRoute = e.features[0].properties.route;
                        Shiny.setInputValue('selected_route', clickedRoute, {{ priority: 'event' }});
                    }}
                }});
            }});

            // Spotlight on legend hover
            window.highlightRoute = function(routeName) {{
                if (!map.getLayer('routes-lines') || currentSelected !== 'ALL') return;
                if (!routeName) {{
                    map.setPaintProperty('routes-lines', 'line-opacity', 0.25);
                }} else {{
                    map.setPaintProperty('routes-lines', 'line-opacity', [
                        'case',
                        ['==', ['get', 'route'], routeName], 0.55,
                        0.05
                    ]);
                }}
            }};

            // Filter layer when Shiny dropdown or legend updates
            Shiny.addCustomMessageHandler('filter_route', function(msg) {{
                currentSelected = msg.route;
                if (!map.getLayer('routes-lines')) return;

                if (msg.route === 'ALL') {{
                    map.setFilter('routes-lines', null);
                    map.setPaintProperty('routes-lines', 'line-opacity', 0.25);
                }} else {{
                    map.setFilter('routes-lines', ['==', ['get', 'route'], msg.route]);
                    map.setPaintProperty('routes-lines', 'line-opacity', 0.35);
                }}
            }});
            """
        ),
    ),
)


def server(input, output, session):
    @reactive.effect
    async def _sync_route_filter():
        route_val = input.selected_route()
        await session.send_custom_message("filter_route", {"route": route_val})

    @render.ui
    def route_summary():
        r = input.selected_route()
        if r == "ALL":
            return ui.div(
                ui.strong("Viewing All Routes"),
                ui.p(
                    f"{len(ROUTE_NAMES)} corridors · {len(ROUTES_GEOJSON['features'])} total rides. Click any corridor on the map or legend to isolate it.",
                    style="font-size: 12px; color: #475569; margin-top: 4px;",
                ),
            )
        return ui.div(
            ui.strong(r, style=f"color: {ROUTE_COLORS.get(r, '#0f172a')};"),
            ui.p(
                f"Showing {route_counts.get(r, 0)} recorded rides along this corridor.",
                style="font-size: 12px; color: #475569; margin-top: 4px; margin-bottom: 8px;",
            ),
            ui.input_action_button(
                "reset_route",
                "Show All Routes",
                class_="btn-sm btn-outline-secondary w-100",
            ),
        )

    @reactive.effect
    @reactive.event(input.reset_route)
    def _reset():
        ui.update_select("selected_route", selected="ALL")


app = App(app_ui, server)