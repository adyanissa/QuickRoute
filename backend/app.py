from flask import Flask, jsonify
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

places = [
    {"id": 1, "name": "Entrance"},
    {"id": 2, "name": "Hall"},
    {"id": 3, "name": "Stairs"},
    {"id": 4, "name": "Room 101"}
]

@app.route("/")
def home():
    return jsonify({"message": "Backend is running 🚀"})

@app.route("/places")
def get_places():
    return jsonify(places)

# route API
@app.route("/route/<start>/<end>")
def get_route(start, end):

    route = [
        start,
        "Hall",
        "Stairs",
        end
    ]

    return jsonify({
        "start": start,
        "end": end,
        "path": route
    })

if __name__ == "__main__":
    app.run(debug=True)