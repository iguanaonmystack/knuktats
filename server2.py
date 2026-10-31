import os
import re
import sys
import glob
import time
import json
import copy
import random
import logging
import operator
import datetime
import collections
import urllib.request, urllib.parse

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
import nltk.corpus
dictionary = set(nltk.corpus.words.words())

import knuxtats
import button
import adventure
import config_local

chatlog = open('chatlog.txt', 'a')

dungeonsfx = 'html/dungeonsfx/'

badwords = set()
if os.path.exists('badwords.txt'):
    with open('badwords.txt') as badwordsf:
        for line in badwordsf:
            line = line.strip().lower()
            if line:
                badwords.add(line)

pastwotds = set()
if os.path.exists('wotd_history.txt'):
    with open('wotd_history.txt') as pastwotdsf:
        for line in pastwotdsf:
            line = line.strip().lower()
            if line:
                pastwotds.add(line)

wronglayer_count = 0
if os.path.exists('wronglayer.txt'):
    with open('wronglayer.txt', 'r') as layerf:
        for line in layerf:
            wronglayer_count = int(line.strip())

hotdentist_count = 0
if os.path.exists('hotdentist.txt'):
    with open('hotdentist.txt', 'r') as layerf:
        for line in layerf:
            hotdentist_count = int(line.strip())

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
    """Return msg (sometimes altered) if words are suitable (and desirable) for knuk tats.

    msg - a line of chat (str)
    """
    if msg.startswith('kapell3Knuk'):
        msg = msg[len('kapell3Knuk'):]
    if msg.endswith('kapell3Tats'):
        msg = msg[:-len('kapell3Tats')]
    msg = msg.strip()
    words = msg.split(" ")
    if len(words) != 2:
        return None
    if len(words[0]) != 4 or len(words[1]) != 4:
        return None
    for word in words:
        if not word.isalnum():
            return None
    return msg # temporary thing to generate some accidental tats
    # Can't just check word.isupper() because '1234'.isupper() is false
    for letter in words[0] + words[1]:
        if letter.islower():
            return None
    return msg

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
        self.faust = None # faust in chat

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
        self.logger.debug(l)

    def signedOn(self):
        """Called when bot has succesfully signed on to server."""
        self.sendLine("CAP REQ :twitch.tv/membership twitch.tv/tags twitch.tv/commands")
        self.join(self.factory.channel)

    def joined(self, channel):
        """This will get called when the bot joins the channel."""
        self.logger.debug("joined %s" % self.factory.channel)
        self.msg(channel, "< Welcome to Dungeon {}. Today there are {} rooms.".format(repr(adventure.game.random_seed), len(adventure.game.rooms)))
        #reactor.callLater(1000, self.on_etsy_reminder, self.factory.channel)

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
    command_QUIT.hidden = True

    def command_EXIT(self, user, channel, msg, args, cmd, tags):
        return self.command_QUIT(user, channel, msg, args, cmd, tags)
    command_EXIT.hidden = True

    def command_FAUST(self, user, channel, msg, args, cmd, tags):
        if not self.faust:
            self.factory.knuxfactory.broadcast("FAUST: Faust.webm")
            self.msg(channel, "< Oh now you've done it! {} is Faust in chat!".format(user))
            self.faust = user
        else:
            self.msg(channel, "< {} is Faust in chat for today".format(user))
    command_FAUST.hidden = True

    def command_SMILE(self, user, channel, msg, args, cmd, tags):
        self.factory.knuxfactory.broadcast("FAUST: smile-with-your-eyes.mp4")
        self.msg(channel, "< I heard people like it when you smile with your eyes".format(user))

    def command_HORNY(self, user, channel, msg, args, cmd, tags):
        user = args[1] if len(args) > 1 else user

        rand = random.random()
        print('random', rand)
        if rand < 1:
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

    def command_POINT(self, user, channel, msg, args, cmd, tags):
        if len(args) < 3:
            self.msg(channel, "< !point usage: !point to_whom and a reason")
            return
        recipient = args[1]
        if recipient.startswith("@"):
            recipient = recipient[1:]
        recipient = recipient.lower()
        reason = " ".join(args[2:])
        if user.lower() == recipient:
            self.msg(channel, "< You cannot award points to yourself. Unless you're Jack the one time he broke it.")
            return
        self.msg(channel, "< {} gave a point to {}, adding '{}'".format(user, recipient, reason))
        dbpool.runQuery("INSERT INTO points (user, recipient, reason) values (?, ?, ?)", (user, recipient, reason)).addCallback(self.on_point_add_query)

    def on_point_add_query(self, result):
        print("points result", result)

    def command_POINTS(self, user, channel, msg, args, cmd, tags):
        dbpool.runQuery("SELECT ?, user, recipient, reason FROM points", (channel,)).addCallback(self.on_points_query)

    def on_points_query(self, result):
        print("points result", result)
        recipients = collections.defaultdict(lambda: 0)
        winner = None
        for (channel, user, recipient, reason) in result:
            recipients[recipient] += 1
        for recipient, count in sorted(recipients.items(), key=operator.itemgetter(1), reverse=True):
            if not winner:
                winner = recipient
            self.msg(channel, "{} points: {}".format(count, recipient))
        if winner:
            self.msg(channel, "< Congratulations to {} for being *ever* so popular".format(winner))
        else:
            self.msg(channel, "< Nobody has any points. How disappointing. !point to award a point.")

    def command_KNUKTATS(self, user, channel, msg, args, cmd, tags):
        self.msg(channel, "< Any two words on their own in an all-caps message will generate you some KNUK TATS")

    def command_PRONOUNS(self, user, channel, msg, args, cmd, tags):
        self.msg(channel, "< My in-video chat displays pronouns next to usernames if the user has set their pronouns using this site https://pronouns.alejo.io/")

    def command_SO(self, user, channel, msg, args, cmd, tags):
        pass # Nightbot currently handles this

    def command_SOCIALS(self, user, channel, msg, args, cmd, tags):
        self.msg(channel, "< Stick @kapellosaur@stctp.zone into mastodon's search box or find me here https://speedlines.stctp.zone/@kapellosaur ; I'm also on these: https://tumblr.com/kapellosaur ; https://instagram.com/kapellosaur ; https://cara.app/kapellosaur")

    def command_ETSY(self, user, channel, msg, args, cmd, tags):
        self.msg(channel, "< Hey my art's for sale. Did you see? https://kapellosaur.etsy.com")
    command_STORE = command_ETSY

    def command_LURK(self, user, channel, msg, args, cmd, tags):
        self.msg(channel, "< You are now lurking, unseen, in the shadows")

    def command_UNLURK(self, user, channel, msg, args, cmd, tags):
        self.msg(channel, "< The prodigal child returns")

    def command_BACK(self, user, channel, msg, args, cmd, tags):
        self.msg(channel, "< The prodigal child returns")
    command_BACK.hidden = True

    def command_WOTD(self, user, channel, msg, args, cmd, tags):
        guess = args[1] if len(args) > 1 else None
        if guess:
            self.msg(channel, "< This is not the place to guess the word of the day")
        elif not self.wotd:
            self.msg(channel, "< The word of the day hasn't been discovered yet. Keep trying and you might find it")
        else:
            self.msg(channel, "< The word of the day is {}".format(self.wotd))
        return True

    def command_WRONGLAYER(self, user, channel, msg, args, cmd, tags):
        global wronglayer_count
        wronglayer_count += 1
        with open('wronglayer.txt', 'w') as layerf:
            layerf.write(str(wronglayer_count))
        self.msg(channel, "< The keeper has drawn on the wrong layer {} times now. How careless of her.".format(wronglayer_count))
    command_LAYER = command_WRONGLAYER

    def command_HOTDENTIST(self, user, channel, msg, args, cmd, tags):
        global hotdentist_count
        hotdentist_count += 1
        with open('hotdentist.txt', 'w') as layerf:
            layerf.write(str(hotdentist_count))
        self.msg(channel, "< Jack just can't stop thinking about his hot dentist, I must announce for the {} time.".format(ordinal(hotdentist_count)))
    command_DENTIST = command_HOTDENTIST

    def command_TONGUE(self, user, channel, msg, args, cmd, tags):
        self.msg(channel, "< Keeper, stop chewing your damn tongue.")

    def command_MORG(self, user, channel, msg, args, cmd, tags):
        audio = choose_audio('horny')
        self.factory.knuxfactory.broadcast("DUNGEON MASTER: " + audio)
        self.msg(channel, "< Check out MagicalMorg on bsky, https://speedlines.stctp.zone/@Morg on mastodon, or if you're feeling a bit spicy, NaughtyMorg on bsky, masto, and furaffinity.")
    command_MORG.hidden = True

    def command_ADS(self, user, channel, msg, args, cmd, tags):
        self.msg(channel, "< Three minutes of adverts? Every hour? FOREVER?!")

    def command_WHY(self, user, channel, msg, args, cmd, tags):
        audio = choose_audio('why-no')
        self.factory.knuxfactory.broadcast("SFX: " + audio)

    def command_NO(self, user, channel, msg, args, cmd, tags):
        return self.command_WHY(user, channel, msg, args, cmd, tags)
    command_NO.hidden = True

    def command_GOODWORK(self, user, channel, msg, args, cmd, tags):
        audio = choose_audio('accidents')
        self.factory.knuxfactory.broadcast("SFX: " + audio)

    def command_OMM(self, user, channel, msg, args, cmd, tags):
        audio = choose_audio('omm')
        self.factory.knuxfactory.broadcast("SFX: " + audio)

    def command_BUY(self, user, channel, msg, args, cmd, tags):
        audio = choose_audio('buy-full')
        self.factory.knuxfactory.broadcast("SFX: " + audio)

    def command_FART(self, user, channel, msg, args, cmd, tags):
        self.msg(channel, "< Over to you, keeper.")

    def on_etsy_reminder(self, channel):
        self.msg(channel, f"< Keeper, did you remember to hawk the kapellostore yet?")

    def on_reminder_time_done(self, user, channel, msg, args, cmd, tags):
        self.msg(channel, f"< reminder for @{user}: " + ' '.join(args[2:]))

    def command_REMINDER(self, user, channel, msg, args, cmd, tags):
        time = args[1] if len(args) > 1 else None
        time_seconds = 0
        if time:
            if time.endswith('s'):
                try:
                    time_seconds = float(time[:-1])
                except ValueError:
                    pass
            elif time.endswith('m'):
                try:
                    time_seconds = float(time[:-1]) * 60
                except ValueError:
                    pass
            elif time.endswith('h'):
                try:
                    time_seconds = float(time[:-1]) * 60 * 60
                except ValueError:
                    pass
        if time_seconds and len(args) > 2:
            reactor.callLater(time_seconds, self.on_reminder_time_done, user, channel, msg, args, cmd, tags)
            self.msg(channel, "< okay, no promises though.")
        else:
            self.msg(channel, "< reminder usage: TIME[s|m|h] reminder message")

    def command_DUNGEON(self, user, channel, msg, args, cmd, tags):
        print("DUNGEON command", args)
        args = args[1:]
        if not args:
            self.msg(channel, "< dungeon usage: !dungeon cmd [params]. recommended start: !d look")
            return
        try:
            player = adventure.game.player(user)
            print(player)
        except adventure.NoPlayerError:
            def reply(msg): # unused until I get kapellodon sorted out
                #time.sleep(1)
                return self.msg(user, msg)
            def reply_all(msg):
                #time.sleep(1)
                return self.msg(channel, msg)
            player = adventure.game.add_player(user, reply_all, reply_all)
            print('new player', player)
        finally:
            print('sending player cmd', args, player)
            player.cmd(args)

    command_D = command_DUNGEON

    def command_COMMANDS(self, user, channel, msg, args, cmd, tags):
        commands = set()
        for methodname in dir(self):
            if getattr(getattr(self, methodname), 'hidden', None):
                continue
            if methodname.startswith('command_'):
                commands.add(methodname[len('command_'):])
        self.msg(channel, "< commands: " + " ".join('!' + command.lower() for command in commands))

    def privmsg(self, user, channel, msg):
        """This will get called when the bot receives a message."""
        user = user.split('!', 1)[0]
        self.logger.debug("<%s> %s" % (user, msg))
        print("%s <%s> %s" % (datetime.datetime.now().strftime('%Y%m%d %H:%M:%S'), user, msg), file=chatlog)
        
        # Check to see if they're sending a private message
        if channel == self.nickname:
            return

        # commands
        if msg.startswith('!'):
            if self.command(user, channel, msg, self.tags):
                return

        # Otherwise check to see if it is a message is KNUK TATS
        if tat_msg := should_tat(msg):
            self.logger.debug("<%s> %s" % (self.nickname, msg))
            self.logger.debug("tat msg: %r" % (tat_msg,))
            #self.msg(channel, "KNUK TATS")
            self.factory.knuxfactory.broadcast("KNUK TATS: " + tat_msg)

        self.privmsg_action_common(user, channel, msg)

        # Cheer audio
        bits = False
        for tag, value in self.tags:
            if tag == 'bits':
                bits = True
                break
        if bits:
            audio = choose_audio('need-treasury')
            self.factory.knuxfactory.broadcast("DUNGEON MASTER: " + audio)

    def alterCollidedNick(self, nickname):
        return nickname+'_'

    def action(self, user, channel, msg):
        """This will get called when the bot sees someone do an action."""
        user = user.split('!', 1)[0]
        self.logger.debug("* %s %s" % (user, msg))
        print("%s * %s %s" % (datetime.datetime.now().strftime('%Y%m%d %H:%M:%S'), user, msg), file=chatlog)
        self.privmsg_action_common(user, channel, msg)

    def privmsg_action_common(self, user, channel, msg):
        """Common things we want to process on both regular messages and /me actions"""

        for word, audio_prefix, dm in (
            ('chicken', 'chicken', True),
            ('birds', 'birds', False),
            ('well done', 'accidents', False),
            ('good work', 'accidents', False),
            ('buy', 'buy', False),
            ('bought', 'buy', False),
            ('shop', 'buy', False),
            ('never mind', 'never-mind', False),
            ('what\'s wrong', 'whats-wrong', False),
            ('roommate', 'roommate', False),
            ('housemate', 'roommate', False),
            ('flatmate', 'roommate', False),
            ('roomy', 'roommate', False),
            ('roomie', 'roommate', False),
            ('performance', 'performance-perfect', False),
            ('perfect', 'performance-perfect', False),
            ('nowhere', 'nowhere-to-go', False),
            ('pretty nice', 'pretty-nice', False),
            ('mormon', 'mormon-jesus', False),
            ('jesus', 'mormon-jesus', False),
        ):
            # whether the DM is saying it or if it's just a sound clip
            prefix = 'DUNGEON MASTER: ' if dm else 'SFX: '
            # chicken audio
            if word in msg.lower():
                print('{} mentioned', word)
                now = datetime.datetime.now()
                diff = (now - self.timeouts.get(word, datetime.datetime.fromordinal(1)))
                if diff / datetime.timedelta(seconds=1) > 60:
                    audio = choose_audio(audio_prefix)
                    print('picked audio', audio)
                    self.factory.knuxfactory.broadcast(prefix + audio)
                else:
                    print('... but not more than a minute ago')

        # Welcome audio for first-of-the-session chatters
        if user != "kapellodon" and user != "kapellosaur" and user != "nightbot" and user not in self.seen_users:
            print('finding audio for new joiner ' + user)
            self.seen_users.add(user)
            audio = choose_audio(user, 'new-chatter')
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
                elif wordlow in pastwotds:
                    continue
                elif wordlow not in dictionary:
                    # the dictionary contains some capitalised proper nouns but we don't want those anyway
                    continue
                elif user in ("kapellodon", "nightbot"):
                    # This is here rather than earlier to make sure the words still get added to the list
                    continue
                # eligible word:
                elif random.random() < 0.004:
                    # Congratulate the user on picking the word of the day
                    print('random success')
                    self.wotd = word
                    congrats = True
                    self.msg(channel, "< {} has found the word of the day: '{}'".format(user, self.wotd))
                    with open('wotd_history.txt', 'a') as pastwotdsf:
                        print(word, file=pastwotdsf)
                self.words.add(wordlow)

        if self.wotd and not congrats:
            if re.search(r'\b' + re.escape(self.wotd) + r'\b', msg, re.I):
                self.msg(channel, "< {} said the word of the day: '{}'".format(user, self.wotd))

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

        print(line)
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
        print("NOTICE", prefix,params,tags)
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

# ----- Twitch authentication nonsense -----

def setup_twitch_refresh_token_loop():
    now = datetime.datetime.now()
    if now > config_local.token_data['expires_time']:
        # already expired.
        timeout = 0
    else:
        timeout = (config_local.token_data['expires_time'] - now).seconds
    print('twitch timeout in %s seconds' % timeout)
    reactor.callLater(timeout, refresh_twitch_token)

def refresh_twitch_token():
    # TODO - this duplicates most of the code from the --token handling, refactor.
    payload = urllib.parse.urlencode([
        ('client_id', config_local.client_id),
        ('client_secret', config_local.client_secret),
        ('grant_type', 'refresh_token'),
        ('refresh_token', config_local.token_data['refresh_token']),
    ]).encode('utf-8')
    resp = urllib.request.urlopen('https://id.twitch.tv/oauth2/token', data=payload)
    data = resp.read()
    # {
    #  "access_token": "1ssjqsqfy6bads1ws7m03gras79zfr",
    #  "expires_in": 15583,
    #  "refresh_token": "eyJfMzUtNDU0OC4MWYwLTQ5MDY5ODY4NGNlMSJ9%asdfasdf=",
    #  "scope": [ "channel:read:subscriptions", "channel:manage:polls" ],
    #  "token_type": "bearer"
    #}
    data = json.loads(data.decode('utf-8'))
    expires_time = (datetime.datetime.now() - datetime.timedelta(seconds=10) + datetime.timedelta(seconds=data['expires_in']))
    data['expires_time'] = expires_time
    config_local.token_data = data

    data = copy.copy(data)
    data['expires_time'] = data['expires_time'].isoformat()
    with open('token.json', 'w') as f:
        json.dump(data, f)

    setup_twitch_refresh_token_loop()

class TwitchRedirectURI(Resource):
    isLeaf = True
    def __init__(self, state, *args, **kw):
        super().__init__(*args, **kw)
        self.state = state

    def render_GET(self, request):
        print(request.args)
        # {b'code': [b'i0dsz8y77d7iujgfzwx1f4sevhxugi'], b'scope': [b'user:read:chat user:write:chat user:bot'], b'state': [b'jgiewgjiewjoiew']}
        auth_code = request.args[b'code'][0]
        assert self.state == request.args[b'state'][0].decode()

        payload = urllib.parse.urlencode([
            ('client_id', config_local.client_id),
            ('client_secret', config_local.client_secret),
            ('code', auth_code),
            ('grant_type', 'authorization_code'),
            ('redirect_uri', 'http://localhost:9000/twitchredirect'),
        ]).encode('utf-8')
        resp = urllib.request.urlopen('https://id.twitch.tv/oauth2/token', data=payload)
        data = resp.read()
        print("*********")
        print(data) # b'{"access_token":"fjejewio","expires_in":15651,"refresh_token":"fegewjio","scope":["chat:edit","chat:read","user:bot","user:read:chat","user:write:chat"],"token_type":"bearer"}\n'
        print('set irc_password to oauth:{access_token}')
        print("*********")
        data = json.loads(data.decode('utf-8'))
        expires_time = (datetime.datetime.now() - datetime.timedelta(seconds=10) + datetime.timedelta(seconds=data['expires_in'])).isoformat()
        data['expires_time'] = expires_time
        with open('token.json', 'w') as f:
            json.dump(data, f)

        return ("Expires %s" % expires_time).encode('utf-8')


# ------ Wiring ----------

if __name__ == '__main__':
    log.startLogging(sys.stdout)

    if len(sys.argv) > 1:
        if sys.argv[1] == '--token':
            # payload = urllib.parse.urlencode([
            #     ('client_id', config_local.client_id),
            #     ('client_secret', config_local.client_secret),
            #     ('grant_type', 'client_credentials'),
            # ]).encode('utf-8')
            # resp = urllib.request.urlopen('https://id.twitch.tv/oauth2/token', data=payload)
            # data = resp.read()
            # print(data)
            # print('set irc_password to oauth:{access_token}')

            auth_url = 'https://id.twitch.tv/oauth2/authorize?'
            state = 'jgiewgjiewjoiew' # TODO - generate random
            # probably want more scopes (roles) in the future:
            # https://dev.twitch.tv/docs/authentication/scopes/
            parameters = urllib.parse.urlencode([
                ('client_id', config_local.client_id),
                ('force_verify', 'false'),
                ('redirect_uri', 'http://localhost:9000/twitchredirect'),
                ('response_type', 'code'),
                ('scope', 'user:read:chat user:write:chat user:bot chat:edit chat:read'),
                ('state', state),
            ])
            
            print("*********")
            print('go to the following URL in a browser logged in as kapelloDON:\n'
            , auth_url + parameters, '***')
            print("*********")

            resource4 = TwitchRedirectURI(state=state)
            root = File(b"html")
            root.putChild(b"twitchredirect", resource4)
            site = Site(root)
            reactor.listenTCP(9000, site)
            reactor.run()

            sys.exit()

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
    
    # Set up the twitch refresh token loop:
    setup_twitch_refresh_token_loop()

    # start the main loop:
    reactor.run()
