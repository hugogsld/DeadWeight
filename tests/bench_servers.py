"""Faux serveurs OpenAI-compatibles pour tester le banc sans reseau ni cle.

    echo          : renvoie le dernier message utilisateur tel quel (le candidat "est d'accord")
    fixed         : renvoie toujours le meme texte, different de la reference ("est en desaccord")
    error         : repond 500 a chaque appel
    unauthorized  : repond 401 a chaque appel (cle absente ou refusee, probleme 17)
"""
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_POST(self):
        length = int(self.headers.get('Content-Length', 0))
        body = json.loads(self.rfile.read(length) or b'{}')
        self.server.received.append(body)
        behavior = self.server.behavior
        if behavior == 'error':
            self._send(500, {'error': {'message': 'boom'}})
            return
        if behavior == 'unauthorized':
            self._send(401, {'error': {'message': 'Incorrect API key provided'}})
            return
        if behavior == 'fixed':
            content = self.server.fixed_answer
        else:  # echo
            content = next((m.get('content', '') for m in reversed(body.get('messages', []))
                           if m.get('role') == 'user'), '')
        self._send(200, {
            'id': 'chatcmpl-fake', 'choices': [{'message': {'role': 'assistant', 'content': content}}],
            'usage': {'prompt_tokens': 10, 'completion_tokens': 3},
        })

    def _send(self, status, payload):
        data = json.dumps(payload).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.end_headers()
        self.wfile.write(data)


class FakeCandidateServer:
    """behavior : 'echo' | 'fixed' | 'error' | 'unauthorized'."""

    def __init__(self, behavior='echo', fixed_answer='AUTRE_REPONSE'):
        self.httpd = ThreadingHTTPServer(('127.0.0.1', 0), _Handler)
        self.httpd.behavior = behavior
        self.httpd.fixed_answer = fixed_answer
        self.httpd.received = []  # corps des requetes recues, dans l'ordre (bench.reasoning : extra body)
        self.base_url = f'http://127.0.0.1:{self.httpd.server_address[1]}/v1'
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    @property
    def received(self):
        return self.httpd.received

    def stop(self):
        self.httpd.shutdown()
        self.httpd.server_close()
