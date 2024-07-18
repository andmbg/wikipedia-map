from flask import Flask
from . import init_dashboard


app = Flask(__name__, instance_relative_config=False)
app = init_dashboard(app, route="/")
app.run(host="0.0.0.0", port=8080, debug=True, load_dotenv=False)
