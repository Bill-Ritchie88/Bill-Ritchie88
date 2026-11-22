"""Tiny, intentionally vulnerable social app for local bug-hunting practice.

Runs only on 127.0.0.1. Uses the Python standard library only.
DO NOT deploy this anywhere – the bugs are deliberate.
"""
import html
import json
import secrets
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse

USERS = {
    1: {"name": "alice", "password": "alice123", "email": "alice@example.test", "bio": "Hi, I'm Alice"},
    2: {"name": "bob", "password": "bob456", "email": "bob@example.test", "bio": "Bob here"},
    3: {"name": "carol", "password": "carol789", "email": "carol@example.test", "bio": "Carol's page"},
}
POSTS = {
    101: {"owner": 1, "text": "Alice's public post", "privacy": "public"},
    102: {"owner": 2, "text": "Bob's PRIVATE diary: my bank PIN hint is 'fluffy'", "privacy": "only_me"},
    103: {"owner": 3, "text": "Carol's friends-only post", "privacy": "friends"},
    104: {"owner": 2, "text": "Bob's public post", "privacy": "public"},
}
FRIENDS = {1: {2}, 2: {1}, 3: set()}
SESSIONS = {}  # token -> user_id
RESET_TOKENS = {}  # user_id -> token


def can_view(viewer, post):
    if post["privacy"] == "public" or post["owner"] == viewer:
        return True
    if post["privacy"] == "friends":
        return viewer in FRIENDS.get(post["owner"], set())
    return False


class Handler(BaseHTTPRequestHandler):
    def user(self):
        c = SimpleCookie(self.headers.get("Cookie", ""))
        tok = c.get("session")
        return SESSIONS.get(tok.value) if tok else None

    def send(self, body, status=200, ctype="text/html", headers=None):
        data = body.encode()
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def form(self):
        n = int(self.headers.get("Content-Length", 0))
        return {k: v[0] for k, v in parse_qs(self.rfile.read(n).decode()).items()}

    def page(self, title, inner):
        return f"<html><head><title>{title}</title></head><body><h1>{title}</h1>{inner}</body></html>"

    def do_GET(self):
        url = urlparse(self.path)
        q = {k: v[0] for k, v in parse_qs(url.query).items()}
        uid = self.user()

        if url.path == "/":
            if not uid:
                return self.send(self.page("MiniSocial", """
<form method=post action=/login>user <input name=user> pass <input name=password type=password>
<button>Log in</button></form><p><a href=/forgot>Forgot password?</a></p>"""))
            me = USERS[uid]
            feed = "".join(
                f"<li><a href=/post?id={pid}>post {pid}</a> by {USERS[p['owner']]['name']}: {html.escape(p['text'])}</li>"
                for pid, p in POSTS.items() if can_view(uid, p))
            return self.send(self.page(f"Welcome {me['name']}", f"""
<p>Your profile: <a href=/profile?id={uid}>view</a> | <a href=/api/user?id={uid}>API</a></p>
<form method=post action=/bio>Bio <input name=bio><input type=hidden name=id value={uid}><button>Save</button></form>
<h2>Feed</h2><ul>{feed}</ul>"""))

        if url.path == "/post":
            if not uid:
                return self.send("login required", 401)
            post = POSTS.get(int(q.get("id", 0)))
            if not post or not can_view(uid, post):
                return self.send("Not found or not allowed", 404)
            return self.send(self.page("Post", html.escape(post["text"])))

        if url.path == "/api/post":
            # BUG 1: API endpoint forgets the privacy check the web page has.
            if not uid:
                return self.send('{"error":"login"}', 401, "application/json")
            post = POSTS.get(int(q.get("id", 0)))
            return self.send(json.dumps(post or {}), ctype="application/json")

        if url.path == "/api/user":
            # BUG 2: returns any user's private email to any logged-in user.
            if not uid:
                return self.send('{"error":"login"}', 401, "application/json")
            u = USERS.get(int(q.get("id", 0)), {})
            return self.send(json.dumps({k: v for k, v in u.items() if k != "password"}), ctype="application/json")

        if url.path == "/profile":
            u = USERS.get(int(q.get("id", 0)))
            if not u:
                return self.send("no such user", 404)
            # BUG 3: bio rendered without escaping (stored XSS).
            return self.send(self.page(f"{u['name']}'s profile", f"<p>{u['bio']}</p>"))

        if url.path == "/forgot":
            return self.send(self.page("Reset password", """
<form method=post action=/forgot>username <input name=user><button>Send reset link</button></form>"""))

        if url.path == "/reset":
            return self.send(self.page("Choose new password", f"""
<form method=post action=/reset><input type=hidden name=id value="{html.escape(q.get('id',''))}">
<input type=hidden name=token value="{html.escape(q.get('token',''))}">
new password <input name=password><button>Set</button></form>"""))

        self.send("not found", 404)

    def do_POST(self):
        url = urlparse(self.path)
        f = self.form()
        uid = self.user()

        if url.path == "/login":
            for i, u in USERS.items():
                if u["name"] == f.get("user") and u["password"] == f.get("password"):
                    tok = secrets.token_hex(16)
                    SESSIONS[tok] = i
                    return self.send("", 302, headers={"Set-Cookie": f"session={tok}; HttpOnly", "Location": "/"})
            return self.send("bad login", 403)

        if url.path == "/bio":
            if not uid:
                return self.send("login required", 401)
            # BUG 4: trusts the hidden 'id' field, so you can edit anyone's bio (IDOR).
            target = int(f.get("id", uid))
            USERS[target]["bio"] = f.get("bio", "")
            return self.send("", 302, headers={"Location": "/"})

        if url.path == "/forgot":
            for i, u in USERS.items():
                if u["name"] == f.get("user"):
                    RESET_TOKENS[i] = secrets.token_hex(8)
                    print(f"[email to {u['email']}] reset link: /reset?id={i}&token={RESET_TOKENS[i]}")
            return self.send("If that user exists, a link was emailed (check the server console).")

        if url.path == "/reset":
            # BUG 5: checks the token exists for *some* user, not for the user in 'id'.
            if f.get("token") in RESET_TOKENS.values():
                USERS[int(f.get("id", 0))]["password"] = f.get("password", "")
                return self.send("Password changed.")
            return self.send("invalid token", 403)

        self.send("not found", 404)


if __name__ == "__main__":
    print("MiniSocial practice lab on http://127.0.0.1:8000  (Ctrl+C to stop)")
    HTTPServer(("127.0.0.1", 8000), Handler).serve_forever()
