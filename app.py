import os
from flask import Flask, jsonify, send_from_directory
from flask_cors import CORS
from database import init_db
from src.auth.routes import auth_bp
from src.shoutouts.routes import shoutouts_bp
from src.admin.routes import admin_bp
from src.leaderboard.routes import leaderboard_bp
from src.reports.routes import reports_bp
from src.auctions.routes import auctions_bp

def create_app():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    static_dir = os.path.join(base_dir, "static")
    avatars_dir = os.path.join(static_dir, "avatars")
    os.makedirs(avatars_dir, exist_ok=True)

    app = Flask(__name__, static_folder="static", static_url_path="/static")
    
    # Configure CORS for local development and media assets
    CORS(app, resources={
        r"/api/*": {"origins": "*"},
        r"/static/*": {"origins": "*"}
    })

    # Register API Blueprints
    app.register_blueprint(auth_bp)
    app.register_blueprint(shoutouts_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(leaderboard_bp)
    app.register_blueprint(reports_bp)
    app.register_blueprint(auctions_bp)

    @app.route("/static/avatars/<path:filename>", methods=["GET"])
    def serve_avatar(filename):
        return send_from_directory(avatars_dir, filename)

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
