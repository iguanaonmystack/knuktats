import sys
import time
import logging
logging.basicConfig(level=logging.DEBUG)

from twisted.internet import reactor
from twisted.python import log
from twisted.web.server import Site
from twisted.web.static import Data
from twisted.web.static import File
from twisted.web.resource import Resource

from autobahn.twisted.websocket import WebSocketServerFactory, \
    WebSocketServerProtocol

from autobahn.twisted.resource import WebSocketResource

from twisted.words.protocols import irc
from twisted.internet import protocol, ssl

import knuxtats
import button
import config_local

def should_tat(msg):
    """Return True if words are suitable (and desirable) for knuk tats.

    msg - a line of chat (str)
    """
    words = msg.split(" ")
    if len(words) != 2:
        return False
    if len(words[0]) != 4 or len(words[1]) != 4:
        return False
    # Can't just check word.isupper() because '1234'.isupper() is false
    for letter in words[0] + words[1]:
        if letter.islower():
            return False
    return True


# ------ WS ----------

class BroadcastServerProtocol(WebSocketServerProtocol):

    def onOpen(self):
        self.factory.register(self)

    def onMessage(self, payload, isBinary):
        if not isBinary:
            msg = "{} from {}".format(payload.decode('utf8'), self.peer)
            self.factory.broadcast(msg)

    def connectionLost(self, reason):
        WebSocketServerProtocol.connectionLost(self, reason)
        self.factory.unregister(self)

class KnuxWebSocketServerFactory(WebSocketServerFactory):

    """
    Simple broadcast server broadcasting any message it receives to all
    currently connected clients.
    """

    def __init__(self, *args, **kw):
        WebSocketServerFactory.__init__(self, *args, **kw)
        self.clients = []
        self.tickcount = 0
        self.tick()

    def tick(self):
        self.tickcount += 1
        self.broadcast("tick %d from server" % self.tickcount)
        reactor.callLater(10, self.tick)  # ten seconds

    def register(self, client):
        if client not in self.clients:
            print("registered client {}".format(client.peer))
            self.clients.append(client)

    def unregister(self, client):
        if client in self.clients:
            print("unregistered client {}".format(client.peer))
            self.clients.remove(client)

    def broadcast(self, msg):
        print("broadcasting message '{}' ..".format(msg))
        for c in self.clients:
            c.sendMessage(msg.encode('utf8'))
            print("message sent to {}".format(c.peer))


class KnuxPreparedWebSocketServerFactory(KnuxWebSocketServerFactory):

    """
    Functionally same as above, but optimized broadcast using
    prepareMessage and sendPreparedMessage.
    """

    def broadcast(self, msg):
        print("broadcasting prepared message '{}' ..".format(msg))
        preparedMsg = self.prepareMessage(msg)
        for c in self.clients:
            c.sendPreparedMessage(preparedMsg)
            print("prepared message sent to {}".format(c.peer))


# ------ IRC ----------


class KnuxIRCBot(irc.IRCClient):
    nickname = config_local.irc_username
    password = config_local.irc_password
    
    def connectionMade(self):
        irc.IRCClient.connectionMade(self)
        self.logger = logging.getLogger('irc')
        self.logger.debug("[connected at %s]" % 
                        time.asctime(time.localtime(time.time())))

    def connectionLost(self, reason):
        irc.IRCClient.connectionLost(self, reason)
        self.logger.debug("[disconnected at %s]" % 
                        time.asctime(time.localtime(time.time())))

    # callbacks for events

    def signedOn(self):
        """Called when bot has succesfully signed on to server."""
        self.join(self.factory.channel)

    def joined(self, channel):
        """This will get called when the bot joins the channel."""
        self.logger.debug("joined %s" % self.factory.channel)

    def privmsg(self, user, channel, msg):
        """This will get called when the bot receives a message."""
        user = user.split('!', 1)[0]
        self.logger.debug("<%s> %s" % (user, msg))
        
        # Check to see if they're sending a private message
        if channel == self.nickname:
            return

        # Otherwise check to see if it is a message is KNUK TATS
        if should_tat(msg):
            self.logger.debug("<%s> %s" % (self.nickname, msg))
            #self.msg(channel, "KNUK TATS")
            self.factory.knuxfactory.broadcast("KNUK TATS: " + msg)

    def alterCollidedNick(self, nickname):
        return nickname+'_'

    def action(self, user, channel, msg):
        """This will get called when the bot sees someone do an action."""
        user = user.split('!', 1)[0]
        self.logger.debug("* %s %s" % (user, msg))

    # irc callbacks

    def irc_NICK(self, prefix, params):
        """Called when an IRC user changes their nickname."""
        old_nick = prefix.split('!')[0]
        new_nick = params[0]
        self.logger.debug("%s is now known as %s" % (old_nick, new_nick))


    # For fun, override the method that determines how a nickname is changed on
    # collisions. The default method appends an underscore.
    def alterCollidedNick(self, nickname):
        """
        Generate an altered version of a nickname that caused a collision in an
        effort to create an unused related name for subsequent registration.
        """
        return nickname + '^'


class KnuxIRCBotFactory(protocol.ClientFactory):
    """A factory for KnuxIRCBots.
    A new protocol instance will be created each time we connect to the server.
    """
    protocol = KnuxIRCBot

    def __init__(self, knuxfactory):
        self.channel = '#kapellosaur' #channel
        self.knuxfactory = knuxfactory

    def clientConnectionLost(self, connector, reason):
        """If we get disconnected, reconnect to server."""
        connector.connect()

    def clientConnectionFailed(self, connector, reason):
        print("connection failed:", reason)


# ------ Knuk tats generator resource ----------

class KnukTatsPage(Resource):
    isLeaf = True
    def render_GET(self, request):
        request.setHeader("Content-Type", "image/png")
        print(request.args)
        text = request.args.get(b't', [b'KNUK TATS'])[0].decode()
        return knuxtats.generate_tats(text)       

# ------ Wiring ----------

if __name__ == '__main__':

    log.startLogging(sys.stdout)

    knuxfactory = KnuxWebSocketServerFactory()
    knuxfactory.protocol = BroadcastServerProtocol
    knuxfactory.startFactory()  # when wrapped as a Twisted Web resource, start the underlying factory manually
    resource1 = WebSocketResource(knuxfactory)
    resource2 = KnukTatsPage()

    ircfactory = KnuxIRCBotFactory(knuxfactory)
    ircfactory.startFactory()

    # Establish a directory to serve static files from
    root = File(b"html")

    # and our WebSocket servers under different paths .. (note that
    # Twisted uses bytes for URIs)
    root.putChild(b"echo1", resource1)
    root.putChild(b"knux", resource2)

    # both under one Twisted Web Site
    site = Site(root)

    # Set up the reactor
    reactor.listenTCP(9000, site)
    reactor.connectSSL('irc.chat.twitch.tv', 6697, ircfactory, ssl.ClientContextFactory())
    button = button.setup(reactor, knuxfactory)
    print(button)

    reactor.run()
