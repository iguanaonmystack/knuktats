import os
import re
import sys
import glob
import time
import random
import logging
import datetime

logging.basicConfig(level=logging.DEBUG)

from twisted.python import log
from twisted.internet import reactor
from twisted.web.server import Site
from twisted.web.static import Data
from twisted.web.static import File
from twisted.enterprise import adbapi
from twisted.web.resource import Resource
dbpool = adbapi.ConnectionPool("sqlite3", 'knux.sqlite', check_same_thread=False)

from autobahn.twisted.websocket import WebSocketServerFactory, \
    WebSocketServerProtocol

from autobahn.twisted.resource import WebSocketResource

from twisted.words.protocols import irc
from twisted.internet import protocol, ssl

import nltk.tokenize

import knuxtats
import button
import config_local

dungeonsfx = 'html/dungeonsfx/'

badwords = set()
if os.path.exists('badwords.txt'):
    badwordsf = open('badwords.txt')
    for line in badwordsf:
        line = line.strip().lower()
        badwords.add(line)

def ordinal(n):
    """Black magic from https://stackoverflow.com/a/20007730"""
    if 11 <= (n % 100) <= 13:
        suffix = 'th'
    else:
        suffix = ['th', 'st', 'nd', 'rd', 'th'][min(n % 10, 4)]
    return str(n) + suffix

def parsemsg(s):
    """Modification of twisted.words.protocols.irc.parsemsg to account for (enough) IRCv3.

    Breaks a message from an IRC server into its prefix, command, and
    arguments.

    @param s: The message to break.
    @type s: L{bytes}

    @return: A tuple of (prefix, command, args).
    @rtype: L{tuple}
    """
    prefix = ""
    trailing = []
    tags = []
    if not s:
        raise irc.IRCBadMessage("Empty line.")

    if s[0:1] == '@':
        # IRCv3 tags
        tags, s = s[1:].split(' ', 1)
        if tags:
            tags = list(tags.split(';'))
        else:
            tags = []
        tags = [tuple(t.split('=', 1)) for t in tags]
        # TODO - unescape values, maybe parse key
        # https://ircv3.net/specs/extensions/message-tags#format
    if s[0:1] == ":":
        prefix, s = s[1:].split(" ", 1)
    if s.find(" :") != -1:
        s, trailing = s.split(" :", 1)
        args = s.split()
        args.append(trailing)
    else:
        args = s.split()
    command = args.pop(0)
    return prefix, command, args, tags


def should_tat(msg):
    """Return True if words are suitable (and desirable) for knuk tats.

    msg - a line of chat (str)
    """
    words = msg.split(" ")
    if len(words) != 2:
        return False
    if len(words[0]) != 4 or len(words[1]) != 4:
        return False
    for word in words:
        if not word.isalnum():
            return False
    return True # temporary thing to generate some accidental tats
    # Can't just check word.isupper() because '1234'.isupper() is false
    for letter in words[0] + words[1]:
        if letter.islower():
            return False
    return True

def choose_audio(prefix, fallback_prefix=None):
    """Pick an audio file to tell the dungeon master to play.

    Returns the filename, with extension but without the directory, or None
    if no appropriate audio was found.
    """
    audios = glob.glob(dungeonsfx + prefix + '-?.ogg')
    if not audios:
        if not fallback_prefix:
            return None
        audios = glob.glob(dungeonsfx + fallback_prefix + '-?.ogg')
    
    if not audios:
        return None

    return random.choice(audios).rsplit(os.sep, 1)[1]


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

        self.seen_users = set()
        self.timeouts = {}
        self.words = set() # which have been ordered in Python for a while now
        self.wotd = None # word of the day

        self.logger = logging.getLogger('irc')
        self.logger.debug("[connected at %s]" % 
                        time.asctime(time.localtime(time.time())))
        dbpool.runQuery("SELECT * from users").addCallback(self.initial_query)

    def connectionLost(self, reason):
        irc.IRCClient.connectionLost(self, reason)
        self.logger.debug("[disconnected at %s]" % 
                        time.asctime(time.localtime(time.time())))

    # callbacks for events

    def initial_query(self, l):
        print(l)

    def signedOn(self):
        """Called when bot has succesfully signed on to server."""
        self.sendLine("CAP REQ :twitch.tv/membership twitch.tv/tags twitch.tv/commands")
        self.join(self.factory.channel)

    def joined(self, channel):
        """This will get called when the bot joins the channel."""
        self.logger.debug("joined %s" % self.factory.channel)

    def command(self, user, channel, msg, tags):
        """Handle a twitch-style !command.

        Return true if other message handling after this should be skipped."""
        print("msg:", msg)
        args = [arg for arg in msg.split() if arg]
        cmd = args[0][1:].upper()
        print('args, cmd:', args, cmd)
        fn = None
        try:
            fn = getattr(self, 'command_' + cmd)
        except AttributeError:
            self.msg(channel, "unknown command: {}".format(cmd))
        if fn:
            return fn(user, channel, msg, args, cmd, tags)
        if msg == '!button':
            # only here for debug
            self.factory.knuxfactory.broadcast("BUTTON: button")

    def command_QUIT(self, user, channel, msg, args, cmd, tags):
        self.msg(channel, "< you may not quit")

    def command_EXIT(self, user, channel, msg, args, cmd, tags):
        return self.command_QUIT(user, channel, msg, args, cmd, tags)

    def command_HORNY(self, user, channel, msg, args, cmd, tags):
        user = args[1] if len(args) > 1 else user

        rand = random.random()
        print('random', rand)
        if rand < 0.2:
            # Upsert the user into the database with incremented horny
            dbpool.runQuery("INSERT INTO users (user, horny) values (?, 1) ON CONFLICT(user) DO UPDATE SET horny = horny + 1 RETURNING ?, user, horny", (user, channel)).addCallback(self.on_horny_query)
        else:
            self.msg(channel, "< {} is reportedly horny".format(user))
            audio = choose_audio('horny')
            self.factory.knuxfactory.broadcast("DUNGEON MASTER: " + audio)

    def on_horny_query(self, result):
        print('horny result', result) # [('kapellosaur', 4)]
        for channel, user, horny in result:
            self.msg(channel, "< {} has acquired a new mistress, the {} of many".format(user, ordinal(horny)))
            if horny >= 5:
                audio = choose_audio('excess-mistresses')
            else:
                audio = choose_audio('new-mistress')
            self.factory.knuxfactory.broadcast("DUNGEON MASTER: " + audio)

    def command_KNUKTATS(self, user, channel, msg, args, cmd, tags):
        self.msg(channel, "< Any two words on their own in an all-caps message will generate you some KNUK TATS")

    def command_PRONOUNS(self, user, channel, msg, args, cmd, tags):
        self.msg(channel, "< My in-video chat displays pronouns next to usernames if the user has set their pronouns using this site https://pronouns.alejo.io/")

    def command_SO(self, user, channel, msg, args, cmd, tags):
        pass # Nightbot currently handles this

    def command_SOCIALS(self, user, channel, msg, args, cmd, tags):
        self.msg(channel, "< Stick @kapellosaur@stctp.zone into mastodon's search box or find me here https://speedlines.stctp.zone/@kapellosaur ; I'm also on these: https://tumblr.com/kapellosaur ; https://instagram.com/kapellosaur ; https://cara.app/kapellosaur")

    def command_LURK(self, user, channel, msg, args, cmd, tags):
        self.msg(channel, "< You are now lurking, unseen, in the shadows")

    def command_UNLURK(self, user, channel, msg, args, cmd, tags):
        self.msg(channel, "< The prodigal child returns")

    def command_BACK(self, user, channel, msg, args, cmd, tags):
        self.msg(channel, "< The prodigal child returns")

    def command_WOTD(self, user, channel, msg, args, cmd, tags):
        guess = args[1] if len(args) > 1 else None
        if guess:
            self.msg(channel, "< this is not the place to guess the word of the day")
        elif not self.wotd:
            self.msg(channel, "< The word of the day hasn't been discovered yet. Keep trying and you might find it")
        else:
            self.msg(channel, "< The word of the day is {}".format(self.wotd))
        return True

    def command_COMMANDS(self, user, channel, msg, args, cmd, tags):
        commands = set()
        for methodname in dir(self):
            if methodname.startswith('command_'):
                commands.add(methodname[len('command_'):])
        self.msg(channel, "< commands: " + " ".join('!' + command.lower() for command in commands))

    def privmsg(self, user, channel, msg):
        """This will get called when the bot receives a message."""
        user = user.split('!', 1)[0]
        self.logger.debug("<%s> %s" % (user, msg))
        
        # Check to see if they're sending a private message
        if channel == self.nickname:
            return

        # commands
        if msg.startswith('!'):
            if self.command(user, channel, msg, self.tags):
                return

        # Otherwise check to see if it is a message is KNUK TATS
        if should_tat(msg):
            self.logger.debug("<%s> %s" % (self.nickname, msg))
            #self.msg(channel, "KNUK TATS")
            self.factory.knuxfactory.broadcast("KNUK TATS: " + msg)

        # chicken audio
        if "chicken" in msg.lower():
            print('chicken mentioned')
            now = datetime.datetime.now()
            diff = (now - self.timeouts.get('chicken', datetime.datetime.fromordinal(1)))
            if diff / datetime.timedelta(seconds=1) > 60:
                audio = choose_audio('chicken')
                print('picked audio', audio)
                self.factory.knuxfactory.broadcast("DUNGEON MASTER: " + audio)
            else:
                print('... but not more than a minute ago')

        # Welcome audio for first-of-the-session chatters
        if user != "kapellosaur" and user != "nightbot" and user not in self.seen_users:
            print('finding audio for new joiner ' + user)
            self.seen_users.add(user)
            audio = choose_audio(user, 'new-chatter')
            self.factory.knuxfactory.broadcast("DUNGEON MASTER: " + audio)

        # Cheer audio
        bits = False
        for tag, value in self.tags:
            if tag == 'bits':
                bits = True
                break
        if bits:
            audio = choose_audio('need-treasury')
            self.factory.knuxfactory.broadcast("DUNGEON MASTER: " + audio)

        # Word of the day
        # each word has a 1/250 chance of being the word of the day
        congrats = False
        if not self.wotd:
            for word in nltk.tokenize.word_tokenize(msg):
                wordlow = word.lower()
                if not word.isalpha():
                    continue
                elif wordlow in badwords:
                    continue
                elif wordlow in self.words:
                    continue
                elif user in ("kapellosaur", "nightbot"):
                    continue
                # eligible word
                elif random.random() < 0.004:
                    # Congratulate the user on picking the word of the day
                    print('random success')
                    self.wotd = word
                    congrats = True
                    self.msg(channel, "< {} has found the word of the day: '{}'".format(user, self.wotd))
                self.words.add(wordlow)

        if self.wotd and not congrats:
            if re.search(r'\b' + re.escape(self.wotd) + r'\b', msg, re.I):
                self.msg(channel, "< {} said the word of the day".format(user))

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

    def irc_unknown(self, prefix, command, params):
        # We actually just want to route all the unknown ones to commands too.
        # OBVIOUSLY not safe but let's assume twitch is well behaved and we're
        # not being MITM'd.
        print('unknown', prefix, command, params, self.tags)
        if hasattr(self, 'twitch_' + command):
            getattr(self, 'twitch_' + command)(prefix, params, self.tags)
    
    def lineReceived(self, line):
        """Override irc.IRCClient.lineReceived to enable our new IRCv3 parsemsg."""
        if bytes != str and isinstance(line, bytes):
            # decode bytes from transport to unicode
            line = line.decode("utf-8")

        line = irc.lowDequote(line)
        try:
            prefix, command, params, tags = parsemsg(line)
            self.tags = tags # hacky, ugh
            print("tags:", tags)
            if command in irc.numeric_to_symbolic:
                command = irc.numeric_to_symbolic[command]
            self.handleCommand(command, prefix, params)
        except irc.IRCBadMessage:
            self.badMessage(line, *sys.exc_info())

    
    def twitch_CLEARCHAT(self, prefix, params, tags):
        """A nice easy one to test by sticking /clear into the twitch chat box."""
        for tag in tags:
            if tag == 'target-user-id':
                # clearchat automatically sent for that user with a user ban (eg for spam)
                return
        self.factory.knuxfactory.broadcast("DUNGEON MASTER: " + 'unknown-event-1.ogg')

    def twitch_USERNOTICE(self, prefix, params, tags):
        """A multipurpose command for various events in the stream."""
        # See https://dev.twitch.tv/docs/chat/irc/
        badges = {} # admin, bits, broadcaster, moderator, subscriber, staff, turbo
        displayname = None
        loginname = None
        mod = False
        subscriber = False
        turbo = False
        type_ = None # sub, resub, subgift, submysterygift, giftpaidupgrade, rewardgift, anongiftpaidupgrade, raid, unraid, bitsbadgetier, sharedchatnotice
            # raid doesn't seem to be "on me raiding someone else"
            # but unraid is a cancellation of our own raid
        for tag, value in tags:
            if tag == 'badges':
                badge_values = value.split(',')
                for badge_value in badge_values:
                    name, version = badge_value.split('/', 1)
                    badges[name] = version
            elif tag == 'display-name':
                displayname = value
            elif tag == 'login':
                loginname = value
            elif tag == 'mod':
                mod = value == '1'
            elif tag == 'msg-id':
                # the type of notice:
                type_ = value
            elif tag == 'subscriber':
                subscriber = value == '1'
            elif tag == 'turbo':
                turbo = value == '1'
        username = displayname or loginname

        if type_ == 'raid':
            audio = choose_audio('raid')
            self.factory.knuxfactory.broadcast("DUNGEON MASTER: " + audio)
        elif 'sub' in type_:
            audio = choose_audio('drink-flowing-casino')
            self.factory.knuxfactory.broadcast("DUNGEON MASTER: " + audio)



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

# ------ Method for OBS to call out to ---------

class OBSResourcePage(Resource):
    isLeaf = True
    def __init__(self, knuxfactory, *args, **kw):
        self.knuxfactory = knuxfactory
        super().__init__(*args, **kw)

    def render_GET(self, request):
        print(request.args)
        text = request.args.get(b'e', [b'unknown'])[0].decode()
        self.knuxfactory.broadcast("DUNGEON MASTER: " + 'unknown-event-1.ogg')
        return b'OK'


# ------ Wiring ----------

if __name__ == '__main__':

    log.startLogging(sys.stdout)

    knuxfactory = KnuxWebSocketServerFactory()
    knuxfactory.protocol = BroadcastServerProtocol
    knuxfactory.startFactory()  # when wrapped as a Twisted Web resource, start the underlying factory manually
    resource1 = WebSocketResource(knuxfactory)
    resource2 = KnukTatsPage()
    resource3 = OBSResourcePage(knuxfactory)

    ircfactory = KnuxIRCBotFactory(knuxfactory)
    ircfactory.startFactory()

    # Establish a directory to serve static files from
    root = File(b"html")

    # and our WebSocket servers under different paths .. (note that
    # Twisted uses bytes for URIs)
    root.putChild(b"echo1", resource1)
    root.putChild(b"knux", resource2)
    root.putChild(b"obs", resource3)

    # both under one Twisted Web Site
    site = Site(root)

    # Set up the reactor
    reactor.listenTCP(9000, site)
    reactor.connectSSL('irc.chat.twitch.tv', 6697, ircfactory, ssl.ClientContextFactory())
    button = button.setup(reactor, knuxfactory)

    reactor.addSystemEventTrigger('before', 'shutdown', lambda: dbpool.close())

    reactor.run()
