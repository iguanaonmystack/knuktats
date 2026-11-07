"""Websocket handling for Twitch's API"""

from __future__ import annotations

import json
import urllib.request, urllib.parse
from typing import Any

from twisted.internet import ssl
from twisted.internet.defer import Failure, Deferred
from twisted.internet.task import LoopingCall, deferLater, react
from twisted.web.websocket import WebSocketClientEndpoint, WebSocketTransport

import config_local

#from autobahn.twisted.websocket import WebSocketClientFactory
#from autobahn.twisted.websocket import WebSocketClientProtocol
#from autobahn.twisted.websocket import connectWS
#
#class MyClientProtocol(WebSocketClientProtocol):
#
#   def onOpen(self):
#      pass # self.sendMessage(u"Hello, world!".encode('utf8'))
#
#   def onMessage(self, payload, isBinary):
#      if isBinary:
#         print("Binary message received: {0} bytes".format(len(payload)))
#      else:
#         print("Text message received: {0}".format(payload.decode('utf8')))
#

class WebSocketClientDemo:
    def __init__(self):
        self.session_id = None

    @classmethod
    def buildProtocol(cls, uri: str) -> WebSocketClientDemo:
        return cls()

    def textMessageReceived(self, data: str) -> None:
        # received text: '{"metadata":{"message_id":"dc78fc56-f4f6-4d66-8359-93203432909d","message_type":"session_welcome","message_timestamp":"2026-11-03T18:35:31.128026728Z"},"payload":{"session":{"id":"AgoQN70ci1zlQmiSxpReXaQkSRIGY2VsbC1h","status":"connected","connected_at":"2026-11-03T18:35:31.124709057Z","keepalive_timeout_seconds":10,"reconnect_url":null,"recovery_url":null}}}'
        # received text: '{"metadata":{"message_id":"c149005c-39c7-4611-8cbf-bfed68a1323e","message_type":"session_keepalive","message_timestamp":"2026-11-03T18:35:41.128237801Z"},"payload":{}}'
        print(f"received text: {data!r}")
        try:
            data = json.loads(data)
        except json.JSONDecodeError:
            print("not json")
            return
        message_type = data.get('metadata', {}).get("message_type", None)
        payload = data.get("payload", {})
        print(message_type, payload)
        if message_type == 'session_welcome':
            self.session_id = payload['session']['id']
            self.register_for_notifications()

    def register_for_notifications(self):
        '''curl -X POST 'https://api.twitch.tv/helix/eventsub/subscriptions' \
                -H 'Authorization: Bearer 2gbdx6oar67tqtcmt49t3wpcgycthx' \
                -H 'Client-Id: wbmytr93xzw8zbg0p1izqyzzc5mbiz' \
                -H 'Content-Type: application/json' \
                -d '{
                  "type": "user.update",
                  "version": "1",
                  "condition": {
                    "user_id": "1234"
                  },
                  "transport": {
                    "method": "webhook",
                    "callback": "https://this-is-a-callback.com",
                    "secret":"s3cre7"
                  }
                }'''
        print('contructing notification registration payload')
        payload = {
            'type': 'channel.channel_points_custom_reward_redemption.add',
                # Must have channel:read:redemptions or channel:manage:redemptions scope.
            'version': '1',
            'condition': {
                'broadcaster_user_id': config_local.twitch_user_id
            },
            'transport': {
                'method': 'websocket',
                'session_id': self.session_id,
            }
        }
        payload = {
            'type': 'channel.chat.message',
            'version': '1',
            'condition': {
                'broadcaster_user_id': config_local.twitch_user_id,
                'user_id': config_local.bot_user_id
            },
            'transport': {
                'method': 'websocket',
                'session_id': self.session_id,
            }
        }
        req = urllib.request.Request('https://api.twitch.tv/helix/eventsub/subscriptions', data=json.dumps(payload).encode('utf-8'), method='POST', headers={
            'Authorization': 'Bearer ' + config_local.access_token,
            'Client-Id': config_local.client_id,
            'Content-Type': 'application/json',
        })
        resp = urllib.request.urlopen(req)
        data = resp.read()
        print('response from registration', data)

    def negotiationStarted(self, transport: WebSocketTransport) -> None:
        self.transport = transport

    def negotiationFinished(self) -> None:
        pass #self.transport.sendTextMessage("KNUX: helo wrld")

    def bytesMessageReceived(self, data: bytes) -> None:
        print(f"received bytes: {data!r}")

    def connectionLost(self, reason: Failure) -> None:
        print("connection lost", reason)

    def pongReceived(self, payload: bytes) -> None:
        print("pong received")



async def main(reactor: Any) -> None:
    endpoint = WebSocketClientEndpoint.new(
       reactor,
       "wss://eventsub.wss.twitch.tv/ws"
       #"ws://localhost:9000/echo1"
       #'wss://echo.websocket.org/'
       #'ws://localhost:8080/websocket-server.rpy'
    )
    print("connecting...")
    await endpoint.connect(WebSocketClientDemo)
    print("connected!")
    await Deferred() # await deferLater(reactor, 10) # exit after 10 seconds


react(main)

#if __name__ == '__main__':
#
#    import sys
#
#    from twisted.python import log
#    from twisted.internet import reactor
#    log.startLogging(sys.stdout)
#
#    factory = WebSocketClientFactory("wss://eventsub.wss.twitch.tv/ws")
#    #factory = WebSocketClientFactory("ws://localhost:9000/echo1")
#    factory.protocol = MyClientProtocol
#    
#    # ws or wss handling:
#    if factory.isSecure:
#        print('secure')
#        contextFactory = ssl.ClientContextFactory()
#    else:
#        contextFactory = None
#
#    print(factory, contextFactory, contextFactory.getContext())
#
#    connectWS(factory, contextFactory)
#    reactor.run()
