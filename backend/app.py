from flask import Flask, jsonify
from flask_cors import CORS
from routes.navigation_routes import navigation_bp

app = Flask(__name__)
CORS(app)

app.register_blueprint(navigation_bp)


@app.route("/")
def home():
    return jsonify({
        "message": "Backend is running 🚀"
    })


if __name__ == "__main__":
    app.run(debug=True)