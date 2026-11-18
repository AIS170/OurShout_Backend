import os
from flask import Flask, jsonify
from flask_cors import CORS
from database import init_db
from src.auth.routes import auth_bp
from src.shoutouts.routes import shoutouts_bp

def create_app():
    app = Flask(__name__)
    
    # Configure CORS for local development
    CORS(app, resources={r"/api/*": {"origins": "*"}})

    # Register API Blueprints
    app.register_blueprint(auth_bp)
    app.register_blueprint(shoutouts_bp)

    @app.route("/health", methods=["GET"])
    def health():
        return jsonify({"status": "healthy", "service": "OurShout API"}), 200

    @app.errorhandler(404)
    def not_found(e):
        return jsonify({
            "error": {
                "code": "NOT_FOUND",
                "message": "The requested endpoint was not found."
            }
        }), 404

    @app.errorhandler(500)
    def internal_error(e):
        return jsonify({
            "error": {
                "code": "INTERNAL_ERROR",
                "message": "An internal server error occurred."
            }
        }), 500

    return app

app = create_app()

if __name__ == "__main__":
    init_db()
    port = int(os.getenv("PORT", 3001))
    print(f"Starting OurShout API on http://localhost:{port}")
    app.run(host="0.0.0.0", port=port, debug=True)
