"""
Auction routes (owner: Nathan).

For everyone signed in (the Auction Table page):
  GET  /api/auctions                 -> { items: AuctionItemDto[], balance: { earned, spent, held, available } }
                                        the caller's country; live items, then upcoming, then the last few ended
  POST /api/auctions/:id/bids        { amount } -> 201 { item: AuctionItemDto, balance }

Admin only (the "Add auction item" page):
  GET    /api/admin/auctions         -> AuctionItemDto[], every item
  POST   /api/admin/auctions         { name, description?, startingBid, startsAt, endsAt, imageBase64? } -> 201 AuctionItemDto
  DELETE /api/admin/auctions/:id     -> { id }, only while the item has no bids

startsAt / endsAt are ISO date-times (UTC). imageBase64 is a data: URL (PNG, JPG, WEBP or GIF, 5 MB).
Errors beyond the shared list: AUCTION_NOT_OPEN (409), BID_TOO_LOW (409), INSUFFICIENT_POINTS (400),
AUCTION_HAS_BIDS (409). The rules are in service.py.
"""
from flask import Blueprint, g, jsonify

from database import get_db
from src.admin.common import make_error, read_json_object
from src.auctions import service
from src.auth.middleware import require_admin, require_auth

auctions_bp = Blueprint("auctions", __name__)


@auctions_bp.errorhandler(service.AuctionError)
def handle_auction_error(error: service.AuctionError):
    return make_error(error.code, error.message, error.status_code)


@auctions_bp.route("/api/auctions", methods=["GET"])
@require_auth
def list_auctions():
    conn = get_db()
    try:
        viewer_id = g.user["employeeId"]
        return jsonify({
            "items": service.list_items(conn, viewer_id, country=g.user["country"]),
            "balance": service.balance(conn, viewer_id),
        }), 200
    finally:
        conn.close()


@auctions_bp.route("/api/auctions/<int:item_id>/bids", methods=["POST"])
@require_auth
def place_bid(item_id: int):
    body, error = read_json_object()
    if error:
        return error
    conn = get_db()
    try:
        item = service.place_bid(conn, item_id, g.user, body.get("amount"))
        return jsonify({"item": item, "balance": service.balance(conn, g.user["employeeId"])}), 201
    finally:
        conn.close()


@auctions_bp.route("/api/auctions/<int:item_id>/bids", methods=["DELETE"])
@auctions_bp.route("/api/auctions/<int:item_id>/bids/withdraw", methods=["POST"])
@require_auth
def withdraw_bid(item_id: int):
    conn = get_db()
    try:
        item = service.withdraw_bid(conn, item_id, g.user)
        return jsonify({"item": item, "balance": service.balance(conn, g.user["employeeId"])}), 200
    finally:
        conn.close()


@auctions_bp.route("/api/admin/auctions", methods=["GET"])
@require_admin
def list_admin_auctions():
    conn = get_db()
    try:
        return jsonify(service.list_items(conn, g.user["employeeId"])), 200
    finally:
        conn.close()


@auctions_bp.route("/api/admin/auctions", methods=["POST"])
@require_admin
def create_auction_item():
    body, error = read_json_object()
    if error:
        return error
    conn = get_db()
    try:
        return jsonify(service.create_item(conn, g.user, body)), 201
    finally:
        conn.close()


@auctions_bp.route("/api/admin/auctions/<int:item_id>", methods=["DELETE"])
@require_admin
def remove_auction_item(item_id: int):
    conn = get_db()
    try:
        service.remove_item(conn, g.user, item_id)
        return jsonify({"id": item_id}), 200
    finally:
        conn.close()
