from gevent import monkey

monkey.patch_all()

from app import create_app
from app.chat.sockets import socketio


app = create_app()


if __name__ == "__main__":
    # The development server is local-only. Production containers use Gunicorn.
    socketio.run(app, host="127.0.0.1", port=8000, debug=False)
