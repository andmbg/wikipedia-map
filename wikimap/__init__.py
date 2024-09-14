import json
import requests
import pandas as pd
import plotly.express as px
from dash import Dash, html, dcc
from dash.dependencies import Input, Output, State
import numpy as np
import re

from .src.utils import render_histogram, get_or_extend_df, get_map, get_article_preview
from .src.i18n import translate as t
from .src.language_context import language_context
from .config import current_language


def init_dashboard(
    flask_app, route, init_location={"lat": 52.516389, "lon": 13.377778}
):

    language_context.set_language(current_language)

    app = Dash(
        __name__,
        server=flask_app,
        routes_pathname_prefix=route,
    )

    dash_bgcolor = "rgba(100,100,100, .8)"

    # initialize the app with a first location and view:
    point_collection_df = get_or_extend_df(
        known_data=None,
        lat=init_location["lat"],
        lon=init_location["lon"],
    )

    app.layout = html.Div(
        [
            dcc.Store(
                id="known_entries",
                data=point_collection_df.to_dict("records"),
            ),
            dcc.Store(id="location", data=init_location),
            # Map background
            html.Div(
                style={
                    "width": "100vw",
                    "height": "100vh",
                },
                children=[dcc.Graph(id="map", style={"height": "100%"})],
            ),
            # sidebar right
            html.Div(
                id="sidebar",
                style={
                    "position": "fixed",
                    "width": "20%",
                    "right": "0px",
                    "top": "15px",
                    "marginRight": "30px",
                    "color": "white",
                },
                children=[
                    html.Div(
                        id="hist-plot",
                        style={
                            "backgroundColor": dash_bgcolor,
                            "padding": "15px 15px 15px 15px",
                            "borderRadius": "5px",
                            "marginTop": "15px",
                        },
                        children=[
                            dcc.Graph(id="histogram"),
                            dcc.RangeSlider(
                                id="slider",
                                min=0,
                                max=1,
                                step=0.01,
                                value=[0, 1],
                                marks={"0": "", "1": ""},
                            ),
                        ],
                    ),
                    html.Div(
                        [
                            html.P(
                                t("""Diese Karte zeigt alle Artikel der deutschsprachigen
Wikipedia, die mit Geodaten verbunden sind und in dieser Gegend verortet sind.
Farbe und Größe entsprechen der Zahl der Aufrufe in den letzten 30 Tagen.
Klicken Sie auf einen Punkt, um eine Artikelvorschau zu sehen. Das Histogramm
oben rechts zeigt die Verteilung der Aufrufstatistik für alle aktuell
angezeigten Artikel und erlaubt das Filtern nach Häufigkeit der Aufrufe.""")
                            ),
                            html.P(
                                t("""Die API der Wikipedia ist in der Bandbreite
beschränkt und erlaubt nur den Abruf von Artikeln im Umkreis von 10 km oder
maximal 500 Artikel pro Aufruf. Der Button oben führt zur englischsprachigen
Version.""")
                            ),
                        ],
                        style={
                            "backgroundColor": dash_bgcolor,
                            "padding": "15px 15px 15px 15px",
                            "borderRadius": "5px",
                            "marginTop": "15px",
                            "max-height": "50vh",
                            "overflow-y": "scroll",
                        },
                        id="preview",
                    ),
                ],
            ),
        ]
    )

    init_callbacks(app)

    return app.server


def init_callbacks(app):

    @app.callback(
        Output("preview", "children"),  # the preview panel
        Input("map", "clickData"),  # which dot was last clicked
        prevent_initial_call=True,
    )
    def update_preview(
        click_data,
    ):
        """
        Article preview panel: updates upon click on a point on the map.
        """
        pageid = click_data["points"][0]["customdata"][2]
        article_preview = get_article_preview(pageid)

        return article_preview

    @app.callback(
        Output("map", "figure"),  # the map
        Output("histogram", "figure"),  # the view number hist plot
        Output("known_entries", "data"),  # updated known points
        Input("slider", "value"),
        Input("map", "relayoutData"),
        State("known_entries", "data"),  # currently known points
        State("location", "data"),
    )
    def update_app(
        slider_std,  # list: [float, float]; range 0..1
        relayout,
        points_json_pre,
        location,
    ):

        if relayout is not None and relayout != {"autosize": True}:
            location["lat"] = relayout.get("mapbox.center").get("lat")
            location["lon"] = relayout.get("mapbox.center").get("lon")

        # translate known data from JSON:
        points_df_pre = pd.DataFrame(points_json_pre)

        # add new points to df, update histogram data and filtering:
        points_df_post = get_or_extend_df(
            known_data=points_df_pre,
            lat=location["lat"],
            lon=location["lon"],
        )

        # absolute view numbers from standardized slider values:
        view_range = tuple(
            map(lambda x: x * np.max(points_df_post.log_views), slider_std)
        )

        # render the map:
        fig = get_map(
            points_df_post,
            location,
            view_range=view_range,
        )

        # render the log view counts histogram:
        hist = render_histogram(
            points_df_post,
            bins=20,
            view_range=view_range,
        )

        # translate df back to json for the Store:
        points_json_post = points_df_post.to_dict("records")

        return fig, hist, points_json_post
