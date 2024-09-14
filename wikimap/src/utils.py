import requests
import json
import re
from textwrap import shorten

import numpy as np
import pandas as pd
import plotly.express as px
from plotly.graph_objects import Figure
from dash import html

from ..config import url, current_language
from .i18n import translate as t
from .language_context import language_context


colorscale = [
    (0.00, "#0187c2"),
    (0.46, "#5837ff"),
    (0.58, "#8f50dc"),
    (0.75, "#b162ae"),
    (0.84, "#ff7674"),
    (0.95, "#ffaf72"),
    (1.0, "#fff96b"),
]


def get_pagelist_around_location(
    lat, lon, radius=10000, gslimit=500, url=url
) -> pd.DataFrame:
    """
    From a coordinate pair, get all pages located around it.
    Result shape: df[["pageid", "title", "lat", "lon"]]
    """
    query_params = dict(
        action="query",
        format="json",
        list="geosearch",
        formatversion="2",
        gscoord=f"{str(lat)}|{str(lon)}",
        gsradius=str(radius),
        gslimit=str(gslimit),
    )

    response = requests.get(url, params=query_params)
    response_dict = json.loads(response.text)
    pagelist = pd.json_normalize(response_dict["query"]["geosearch"])
    pagelist = pagelist[["pageid", "title", "lat", "lon"]]

    return pagelist.set_index("pageid")


def api_request(ids, days, url=url):

    page_id_str = "|".join(map(str, ids[0:50]))

    query_params = {
        "action": "query",
        "format": "json",
        "prop": "pageviews",
        "pvipdays": str(days),
        "pageids": page_id_str,
        "formatversion": "2",
    }
    response = requests.get(url, params=query_params)
    response_dict = json.loads(response.text)
    response_df = pd.json_normalize(response_dict["query"]["pages"])

    # shape of df: col 0-2 identifies page, 30 more cols are daily views

    views = response_df.iloc[:, 0:3]

    # sum all daily columns:
    views["views"] = response_df.filter(regex="pageviews").sum(axis=1)
    views.set_index("pageid", inplace=True)

    return views["views"]


def _shorten(ls, chunksize=50):
    if len(ls) >= chunksize:
        return ls[50 : len(ls)]
    else:
        return []


def query_viewcounts(ids, days=30):
    """
    Split API requests into chunks of 50 page IDs.
    [TODO: why?]
    :return: df[["pageid", "title", "views"]]
    """
    page_views = api_request(ids[0:50], days=days)
    ids = _shorten(ids)

    while len(ids) > 0:
        chunk = api_request(ids, days=days)
        page_views = pd.concat([page_views, chunk], axis=0)
        ids = _shorten(ids)

    return page_views


def get_or_extend_df(known_data, lat, lon, radius=10000, gslimit=500):

    if known_data is None:  # start new df
        pagelist = get_pagelist_around_location(lat, lon, radius)
        viewdata = pagelist.join(query_viewcounts(pagelist.index))
        viewdata["log_views"] = list(
            map(lambda x: 0 if x == 0 else np.log2(x), viewdata.views)
        )

        return viewdata

    # add new articles:
    new_pagelist = get_pagelist_around_location(
        lat, lon, radius=radius, gslimit=gslimit
    )

    # don't query viewcount for known pages:
    new_pagelist_filtered = new_pagelist.loc[
        new_pagelist.index.difference(known_data.index)
    ]
    if len(new_pagelist_filtered) == 0:
        return known_data

    else:
        new_data = new_pagelist_filtered.join(
            query_viewcounts(new_pagelist_filtered.index)
        )
        new_data["log_views"] = list(
            map(lambda x: 0 if x == 0 else np.log2(x), new_data.views)
        )
        viewdata = pd.concat([known_data, new_data])

    return viewdata


def get_article_preview(pageid, url=url) -> html.P:
    """
    From a pageid, return a dash.html.P element containing the first couple of sentences of the article
    behind the pageid, retrieved from Wikipedia.
    """
    language_context.set_language(current_language)

    query_params = {
        "action": "query",
        "format": "json",
        "prop": "pageimages|cirrusdoc",
        "pageids": str(pageid),
        "formatversion": "2",
        "cdincludes": "all",
    }

    response = requests.get(url, params=query_params)
    response_dict = json.loads(response.text)
    pagetext = (
        response_dict.get("query")
        .get("pages")[0]
        .get("cirrusdoc")[0]
        .get("source")
        .get("text")
    )

    abstract = shorten(pagetext, 500)

    # the title
    title = response_dict.get("query").get("pages")[0].get("title")

    article_url = url.replace("w/api.php", "wiki/") + title
    article_hyperlink = html.A(href=article_url, children=t("zum Artikel"))

    article_preview = [html.P(abstract), article_hyperlink]

    # does the response give an image to the article?
    wiki_image_link = response_dict.get("query").get("pages")[0].get("pageimage")

    # if image exists, request and include it; else ignore:
    if wiki_image_link is not None:
        image_query_params = {
            "action": "query",
            "format": "json",
            "prop": "imageinfo",
            "iiprop": "url",
            "titles": "Datei:" + wiki_image_link,
            "formatversion": "2",
        }

        img_response = requests.get(url, params=image_query_params)

        print(img_response.text)

        try:
            img_url = (
                json.loads(img_response.text)
                .get("query")
                .get("pages")[0]
                .get("imageinfo")[0]
                .get("url")
            )
        except:
            img_url = ""

        article_preview.insert(
            0,
            html.Img(
                src=img_url,
                style={
                    "width": "80%",
                    "marginLeft": "auto",
                    "marginRight": "auto",
                    "display": "block",
                },
            ),
        )

    return article_preview


def get_map(
    point_collection_df,
    location,
    view_range,
):
    # filter to the view range:
    plot_df = (
        point_collection_df.query(
            "log_views >= @view_range[0] &" "log_views <= @view_range[1]"
        )
        .reset_index()
        .rename({"index": "pageid"}, axis=1)
    )

    # keep zero-view articles visible, bump point size to 1:
    plot_df["dotsize"] = plot_df.views.replace(0, 1)

    # align colorscale to the range of known view numbers:
    global_max_views = max(point_collection_df.log_views)

    fig = px.scatter_mapbox(
        plot_df,
        lat="lat",
        lon="lon",
        color="log_views",
        color_continuous_scale=colorscale,
        range_color=(0, global_max_views),
        size="dotsize",
        hover_name="title",
        hover_data=["views"],
        mapbox_style="carto-darkmatter",
        center={"lat": location["lat"], "lon": location["lon"]},
        zoom=15,
    )

    fig.update_layout(margin=dict(t=0, r=0, b=0, l=0), coloraxis_showscale=False)
    fig.update_traces(
        marker_sizemode="area",
        marker_sizeref=5,
        marker_sizemin=3,
        customdata=np.stack([plot_df.title, plot_df.views, plot_df.pageid]).transpose(),
    )

    fig["data"][0]["hovertemplate"] = (
        "<b>%{customdata[0]}</b><br><br>"
        "Aufrufe in den letzten 30 Tagen: %{customdata[1]}<extra></extra>"
    )

    # sort of keep zoom/position when data change:
    fig["layout"]["uirevision"] = "something"

    return fig


def render_histogram(viewdata, bins=20, view_range=()) -> Figure:
    """
    Bin view data and plot as histogram.

    :para viewdata: df, the df with known points
    :para bins: int, number of bins to display
    :para view_range: tuple(int,int), range of bars displayed opaque
    """
    data_zeroless = viewdata.loc[viewdata.views > 0]

    # bin the log view counts for the histogram:
    counts, boundaries = np.histogram(data_zeroless["log_views"], bins=bins)

    # from 'boundaries', get what is important for plotting:
    bincenters = 0.5 * (boundaries[:-1] + boundaries[1:])
    binlefts = boundaries[:-1]
    binrights = boundaries[1:]

    hist_df = pd.DataFrame(
        {
            "binleft": binlefts,
            "binright": binrights,
            "bincenter": bincenters,
            "count": counts,
            "selected": True,  # updated below
        }
    )

    # column marking opaque bars:
    selected = (hist_df.binleft >= view_range[0]) & (hist_df.binright <= view_range[1])
    # translate to opacity values:
    opacitymap = [1.0 if s else 0.4 for s in selected]

    fig = px.bar(
        hist_df,
        x="bincenter",
        y="count",
        color="bincenter",
        color_continuous_scale=colorscale,
        opacity=opacitymap,
        template="plotly_dark",
        height=150,
    )

    fig.update_layout(
        margin=dict(t=0, r=0, b=0, l=0),
        xaxis=dict(title=None, tickvals=[]),
        yaxis=dict(title=None, tickvals=[]),
        coloraxis_showscale=False,
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
        bargap=0,
    )

    hist_hover = pd.DataFrame(
        [np.round(np.exp2(hist_df.binleft), 0), np.round(np.exp2(hist_df.binright), 0)]
    ).transpose()
    fig.update_traces(
        marker_line_width=0,
        customdata=hist_hover,
        hovertemplate="%{customdata[0]}-%{customdata[1]} Aufrufe: %{y} versch. Orte",
    )

    return fig
