from flask import Flask, render_template
from flask_socketio import SocketIO, emit, send, join_room, leave_room

secret_key = "resources/secret_key.bin"

app = Flask(__name__)
app.config['SECRET_KEY'] = secret_key
socketio = SocketIO(app, cors_allowed_origins="*")

app.debug = True


@socketio.on("newChatMessage")
def handleMsg(msg):
    print("new messages", msg)
    emit("newChatMessage", msg, room=msg['room'])


@socketio.on('join')
def on_join(data):
    opponentName = data['opponentName']
    room = data['opponentId']
    print('join', opponentName, room)
    join_room(room)
    send(opponentName + ' has entered the room.', room=room)


@socketio.on('leave')
def on_leave(data):
    opponentName = data['opponentName']
    room = data['opponentId']
    leave_room(room)
    send(opponentName + ' has left the room.', room=room)


if __name__ == "__main__":
    socketio.run(app, host="0.0.0.0")
