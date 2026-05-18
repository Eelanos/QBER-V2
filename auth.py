"""
auth.py — Qber Portal Login System (Flask)
==========================================
Uses Flask's before_request hook — runs before EVERY request,
server-side, no frontend involvement.

SETUP in app.py:
  1. from auth import setup_auth
  2. setup_auth(app)   <- call this after app = Flask(__name__)
  Done. No decorators needed on any route.
"""
import os
from dotenv import load_dotenv

load_dotenv()
from flask import session, redirect, url_for, request, render_template

# ──────────────────────────────────────────────
# CREDENTIALS — change these
# ──────────────────────────────────────────────
USERS = {
    os.getenv("ADMIN_USERNAME"): os.getenv("ADMIN_PASSWORD"),
    os.getenv("VIEWER_USERNAME"): os.getenv("VIEWER_PASSWORD"),
}

# Paths that skip the auth check
PUBLIC_PATHS    = {"/login", "/logout"}
PUBLIC_PREFIXES = ("/static",)


def setup_auth(app):
    """
    Call this right after app = Flask(__name__) in your app.py.
    Registers the before_request auth check + login/logout routes.
    """

    # Auth check — runs before EVERY request
    @app.before_request
    def check_auth():
        path = request.path

        # Let public paths through
        if path in PUBLIC_PATHS or any(path.startswith(p) for p in PUBLIC_PREFIXES):
            return None  # None = continue normally

        # Not logged in -> redirect to login, request goes no further
        if not session.get("user"):
            return redirect(url_for("login_page"))
        session.modified = True  #  resets the 3hr timer on every click

        # Logged in -> continue to route handler
        return None

    # Login page (GET)
    @app.route("/login", methods=["GET"])
    def login_page():
        if session.get("user"):
            return redirect("/")
        return render_template("login.html")

    # Login form submit (POST)
    @app.route("/login", methods=["POST"])
    def login_submit():
        username = request.form.get("username", "").strip().lower()
        password = request.form.get("password", "")

        if USERS.get(username) == password:
            session["user"] = username
            session.permanent = True
            return redirect("/")

        # Wrong credentials — show error message
        return render_template("login.html", error="Incorrect username or password. Please try again.")

    # Logout
    @app.route("/logout")
    def logout():
        session.clear()
        return redirect(url_for("login_page"))