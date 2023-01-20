import json
import requests
import pandas as pd
import plotly.express as px
from dash import Dash, html, dcc
from dash.dependencies import Input, Output
import numpy as np
import sqlite3
from datetime import datetime

pd.options.mode.use_inf_as_na = True

init_loc = dict(
    lat = 52.69039,
    lon = 13.17309
)

def __DEBUG__(msg):
    dbtime = datetime.now().strftime("%H:%M:%S")
    with open("log.txt", "a") as f:
        f.write(f"\n{dbtime} -- {msg}")



def get_or_extend_df(lat, lon, data=None, radius=1000, gslimit=500):
    def get_pagelist_around_location(lat, lon, radius=10000, gslimit=500):
        url = "https://de.wikipedia.org/w/api.php"
        query_params = {
            "action": "query",
            "format": "json",
            "list": "geosearch",
            "formatversion": "2",
            "gscoord": f"{str(lat)}|{str(lon)}",
            "gsradius": str(radius),
            "gslimit": str(gslimit) # results capped at 500 anyway for anon users
        }
        response = requests.get(url, params = query_params)
        response_dict = json.loads(response.text)
        out = pd.json_normalize(response_dict["query"]["geosearch"])
        out = out[ ["pageid", "title", "lat", "lon"] ]
        __DEBUG__(f"[get_pagelist] queried around ({np.round(lat,5)},{np.round(lon,5)}).")
        __DEBUG__(f"               received {len(out)} articles, {len(response.text)} bytes.")
        return( out.set_index("pageid") )
    
    def get_viewcounts(ids, days=30):
        
        def query_views(ids=ids, days=days):
            url = "https://de.wikipedia.org/w/api.php"
            page_id_str = "|".join(map(str, ids[0:50]))
            query_params = {
                "action": "query",
                "format": "json",
                "prop": "pageviews",
                "pvipdays": str(days),
                "pageids": page_id_str,
                "formatversion": "2"
            }
            response = requests.get(url, params = query_params)
            response_dict = json.loads(response.text)
            __DEBUG__(f"[query_views] queried {len(ids)} ids; received {len(response.text)} bytes.")
            response_df = pd.json_normalize(response_dict["query"]["pages"])
            views = response_df.iloc[:,0:3]
            views["views"] = response_df.filter(regex="pageviews").sum(axis=1)
            views.set_index("pageid", inplace=True)
            return(views["views"])

        def shorten(ls, chunksize=50):
            if len(ls) >= chunksize:
                return( ls[50:len(ls)] )
            else:
                return([])
            
        page_views = query_views(ids[0:50])
        ids = shorten(ids)

        while len(ids) > 0:
            chunk = query_views(ids)
            page_views = pd.concat( [page_views, chunk], axis=0 )
            ids = shorten(ids)

        return(page_views)
    
    
    if data is None: # start new df
        out = get_pagelist_around_location(lat, lon, radius)
        out = out.join(get_viewcounts(out.index))
        return(out)
    new_pagelist = get_pagelist_around_location(lat, lon, radius=radius, gslimit=gslimit)
    new_pagelist_filtered = new_pagelist.loc[ new_pagelist.index.difference(data.index) ]
    if len(new_pagelist_filtered) == 0:
        __DEBUG__("[add_to_df] relocated but found no new articles.")
        return(data)
    else:
        new_data = new_pagelist_filtered.join(get_viewcounts(new_pagelist_filtered.index))
        out = pd.concat([data, new_data])
        __DEBUG__(f"[add_to_df] found {len(new_data)} new articles.")
        __DEBUG__(f"            df_master now has {len(out)} entries.")
    return(out)



def opacity(selected):
    if selected:
        return 1.
    else:
        return .4



def histogram_df(data, column="log_views", bins=20):
    data_zeroless = data.loc[data.views > 0]
    max_log_views = np.max(data_zeroless.log_views)
    counts, boundaries = np.histogram(data_zeroless[column], bins=bins)
    bincenters = 0.5 * (boundaries[:-1] + boundaries[1:])
    binlefts = boundaries[:-1]
    binrights = boundaries[1:]
    scaleleft = binlefts / max_log_views
    scaleright = binrights / max_log_views
    
    out = pd.DataFrame({
      "binleft": binlefts,
      "binright": binrights,
      "bincenter": bincenters,
      "scaleleft": scaleleft,
      "scaleright": scaleright,
      "count": counts,
      "selected": True })
    return(out)



def filter_by_hist(data, hist_df):
    conn = sqlite3.connect(":memory:")
    hist_df.to_sql("hist", conn, index = False)
    data.to_sql("data", conn, index = False)
    query = """select title, lat, lon, views, log_views
               from data, hist
               where data.log_views between hist.binleft and hist.binright
               and hist.selected = True
            """
    out = pd.read_sql_query(query, conn)
    return(out)



__DEBUG__("\n=====================")

df = None

colorscale = [
    (.00, "#0187c2"),
    (.46, "#5837ff"),
    (.58, "#8f50dc"),
    (.75, "#b162ae"),
    (.84, "#ff7674"),
    (.95, "#ffaf72"),
    (1.0, "#fff96b")
]
dash_bgcolor = "rgba(100,100,100, .8)"

current_location = init_loc

app = Dash(__name__)

app.layout = html.Div([

    # Map background
    html.Div(
        style = {
            "width": "100%",
            "height": "100vh"
        },
        children = [
            dcc.Graph(id="map")
        ]),

    # get_articles button at the top left
    html.Div(
        style = {
            "position": "fixed",
            "left": "15px",
            "top": "15px",
        },
        children = [
            html.Button('df speichern',
                        id = 'button',
                        n_clicks = 0)
        ]
    ),

    # sidebar right
    html.Div(
        id = "sidebar",
        style = {
            "position": "fixed",
            "width": "20%",
            "right": "0px",
            "top": "15px",
            "marginRight": "30px",
            "color": "white"
        },
        children = [
            html.Div(
                id = "hist-plot",
                style = {
                    "backgroundColor": dash_bgcolor,
                    "padding": "15px 15px 15px 15px",
                    "borderRadius": "5px",
                    "marginTop": "15px"
                },
                children = [
                    dcc.Graph(id = "histogram"),
                    dcc.RangeSlider(id = "slider",
                        min = 0,
                        max = 1,
                        step = .01,
                        value = [0, 1],
                        marks = {"0": "",
                                 "1": ""},
                        tooltip={"placement": "bottom",
                                 "always_visible": True })
                    ]
            ),

            html.Div([
                html.P(id = "displayA")],
                style = {
                    "backgroundColor": dash_bgcolor,
                    "padding": "15px 15px 15px 15px",
                    "borderRadius": "5px",
                    "marginTop": "15px"                    
                }),

            html.Div([
                html.P(id = "displayB")],
                style = {
                    "backgroundColor": dash_bgcolor,
                    "padding": "15px 15px 15px 15px",
                    "borderRadius": "5px",
                    "marginTop": "15px"
               })
        ])
])

@app.callback(
    Output("map", "figure"),
    Output("histogram", "figure"),
    Output("displayA", "children"),
    Output("displayB", "children"),
    [Input('slider', 'value')],
    Input("map", "relayoutData"),
    Input("map", "clickData"),
    Input("button", "n_clicks"), 
)
def update_app(slider, relayout, click, n_clicks):
    
    global df

    if relayout != None and relayout != {"autosize": True}:
        current_location["lat"] = relayout.get("mapbox.center").get("lat")
        current_location["lon"] = relayout.get("mapbox.center").get("lon")
    
    upperdisplay = f"{click}"

    # update article data:
    df = get_or_extend_df(lat = current_location["lat"],
                          lon = current_location["lon"],
                          data = df,
                          radius = 10000)
    
    df["log_views"] = list(map(lambda x: 0 if x == 0 else np.log2(x), df.views))
    hist_df = histogram_df(df)
    
    lowerdisplay = f"{click}"

    # update histogram dataframe:
    lower, upper = slider
    hist_df.selected = (hist_df.scaleleft >= lower) & (hist_df.scaleright <= upper)
    
    # render histogram:
    hist = px.bar(hist_df,
        x = "bincenter",
        y = "count",
        color = "bincenter",
        color_continuous_scale = colorscale,
        opacity = list(map(opacity, hist_df.selected)),
        template = "plotly_dark",
        height = 150
    )
    hist.update_layout(
        margin = dict(t=0, r=0, b=0, l=0),
        xaxis = dict(
            title = None,
            tickvals = []
        ),
        yaxis = dict(
            title = None,
            tickvals = []
        ),
        coloraxis_showscale=False,
        plot_bgcolor = "rgba(0,0,0,0)",
        paper_bgcolor = "rgba(0,0,0,0)",
        bargap = 0
    )
    hist_hover = pd.DataFrame( [np.round(np.exp2(hist_df.binleft), 0),
                                np.round(np.exp2(hist_df.binright), 0)] ).transpose()
    hist.update_traces(
        marker_line_width = 0,
        customdata = hist_hover,
        hovertemplate = "%{customdata[0]}-%{customdata[1]} Aufrufe: %{y} versch. Orte"
    )



    # Map
    ### update data
    plot_df = filter_by_hist(df, hist_df)
    ### rendering:
    fig = px.scatter_mapbox(plot_df,
                            lat = "lat",
                            lon = "lon",
                            color = "log_views",
                            color_continuous_scale = colorscale,
                            range_color = (0, max(df.log_views)),
                            size = "views",
                            hover_name = "title",
                            hover_data = ["views"],
                            mapbox_style="carto-darkmatter",
                            center={"lat": current_location["lat"], 
                                    "lon": current_location["lon"]},
                            zoom = 18)
    fig.update_layout(margin = dict(t=0, r=0, b=0, l=0),
                      coloraxis_showscale=False,
                      uirevision = "Hurz"
                      )
    fig.update_traces(marker_sizemode = "area",
                      marker_sizeref = 5,
                      marker_sizemin = 3,
                      customdata = np.stack([plot_df.title, plot_df.views]).transpose()
                      )
    #fig.update_geos(fitbounds = False)
    fig["data"][0]["hovertemplate"] = "<b>%{customdata[0]}</b><br><br>Aufrufe in den letzten 30 Tagen: %{customdata[1]}<extra></extra>"
    fig['layout']['uirevision'] = 'something' # sort of keep zoom/position on data changes
    
    __DEBUG__("[-main-] map and hist redrawn.")
    
    if n_clicks == 1:
        df.to_csv("df.csv")
    
    
    return fig, hist, upperdisplay, lowerdisplay


if __name__ == '__main__':
    app.run_server(host = "0.0.0.0",
                   debug = True)
