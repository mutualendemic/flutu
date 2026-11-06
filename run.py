import os

from dotenv import load_dotenv

load_dotenv()

try:
    from gevent import monkey
except ModuleNotFoundError:
    monkey = None

if monkey is not None:
    monkey.patch_all()

from app import create_app
from app.chat.sockets import socketio


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8000"))
    # The development server is local-only. Production containers use Gunicorn.
    socketio.run(app, host="127.0.0.1", port=port, debug=False, allow_unsafe_werkzeug=True)
