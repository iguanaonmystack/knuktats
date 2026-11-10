"""A little text-based adventure, as a treat"""

import types
import random as _random

from enum import Enum
from dataclasses import dataclass, field
from typing import Optional, TypeAlias

N = 1
S = -1
E = 1
W = -1
GridPos = int

adjectives = ['cursed', 'beautiful', 'loathsome', 'wild', 'ornate', 'dark', 'bright', 'catalysing', 'L-shaped']
room_nouns = ['library', 'aboretum', 'chamber', 'room', 'breakfast nook', 'throne room', 'latrine', 'cellar', 'sentry room', 'hall']

class Direction(Enum):
    NORTH = (0, N)
    SOUTH = (0, S)
    EAST = (E, 0)
    WEST = (W, 0)

    def opposite(self):
        if self.name == 'NORTH':
            return self.SOUTH
        elif self.name == 'SOUTH':
            return self.NORTH
        elif self.name == 'EAST':
            return self.WEST
        elif self.name == 'WEST':
            return self.EAST

@dataclass(frozen=True)
class Object:
    name: str
    description: str
    definite: bool = False # whether to use the definite article
    pauldron: bool = False # whether this is the winning item

    def with_article(self):
        if self.definite:
            return 'the ' + self.name
        article = 'a '
        if self.name[0] in 'aeiou':
            article = 'an '
        return article + self.name

@dataclass
class Exit:
    requirement: Optional[Object] = None
    locked: bool = False
    destination: TypeAlias = 'Room'

@dataclass
class Room:
    """You are in a room."""
    x: GridPos
    y: GridPos
    id: int
    name: str
    description: str
    exits: dict[Direction, Exit] = field(default_factory=dict, repr=False)
    items: set[Object] = field(default_factory=set, repr=False)
    game: TypeAlias = 'Adventure'

class NoPlayerError(Exception):
    """Raised if there is no active player for the user who is trying to play."""

@dataclass
class Player:
    name: str # twitch username
    location: Room
    reply: types.FunctionType
    reply_all: types.FunctionType
    inventory: set[Object] = field(default_factory=set)
    game: TypeAlias = 'Adventure'

    def cmd(self, args):
        "Command parser"
        cmd = args[0].upper()
        fn = None
        try:
            fn = getattr(self, 'cmd_' + cmd)
        except AttributeError:
            self.reply("< what is '{}'?".format(cmd))
        if fn:
            return fn(args[0], args[1:])

    def cmd_QUIT(self, cmd, args):
        self.reply("< you may not quit")

    def _find_item(self, args, include_inventory=False):
        print('looking for', args)
        maybe_article = args[0]
        if maybe_article in ('the', 'a', 'an', 'ye'):
            args = args[1:]
        if not args:
            self.reply("< " + maybe_article + " WHAT?")
        name = ' '.join(args).lower()
        item = None
        for item in self.location.items:
            if item.name.lower() == name:
                return item
        if include_inventory:
            for item in self.inventory:
                if item.name.lower() == name:
                    return item
        return None

    def cmd_INSPECT(self, cmd, args):
        if not args:
            self.reply("< What am I supposed to be looking at?")
        item = self._find_item(args, include_inventory=True)
        if item:
            self.reply("< " + item.description + '.')
            return
        self.reply("< You see no such thing here.")

    def cmd_GET(self, cmd, args):
        print('cmd_GET', cmd, args)
        if not args:
            self.reply("< While I appreciate your enthusiasm, you do need to name the item to get")
        item = self._find_item(args)
        if not item:
            if ' '.join(args) == 'ye flask':
                self.reply("< You can't get ye flask")
            else:
                self.reply("< You see no such thing here.")
            return
        self.location.items.remove(item)
        self.inventory.add(item)
        self.reply_all("< {} has found {}".format(self.name, item.with_article()))
        self.reply("< It's yours now.")
        if item.pauldron:
            self.reply_all("< {} has found {}. Congratulations, {}. You may award yourself the title of Liege, Lady, or Lord of the Dungeon. For today, at least.".format(self.name, item.name, self.name))
    cmd_G = cmd_GET

    def cmd_INVENTORY(self, cmd, args):
        items = ", ".join(item.with_article() for item in self.inventory)
        self.reply("< On your person you find " + items)
    cmd_I = cmd_INVENTORY

    def cmd_LOOK(self, cmd, args):
        print('cmd_LOOK', cmd, args)
        if args:
            return self.cmd_INSPECT(cmd, args)
        exits = ', '.join([ex.name for ex in self.location.exits.keys()])
        players = ', '.join([player.name for player in self.game.players.values() if player.location == self.location and player != self])
        items = ', '.join(item.with_article() for item in self.location.items)
        self.reply("< You ({}) are in {}. {}. Exits are {}.".format(self.name, self.location.name, self.location.description, exits))
        if self.location.items:
            self.reply("< There is {} here".format(items))
        if players:
            self.reply("< Oh, look. {} is here too.".format(players))
    cmd_L = cmd_LOOK
 
    def cmd_NORTH(self, cmd, args):
        if Direction.NORTH in self.location.exits:
            return self._attempt_move(self.location.exits[Direction.NORTH])
        self.reply("< There is no exit in that direction.")
    cmd_N = cmd_NORTH

    def cmd_SOUTH(self, cmd, args):
        if Direction.SOUTH in self.location.exits:
            return self._attempt_move(self.location.exits[Direction.SOUTH])
        self.reply("< There is no exit in that direction.")
    cmd_S = cmd_SOUTH

    def cmd_EAST(self, cmd, args):
        if Direction.EAST in self.location.exits:
            return self._attempt_move(self.location.exits[Direction.EAST])
        self.reply("< There is no exit in that direction.")
    cmd_E = cmd_EAST

    def cmd_WEST(self, cmd, args):
        if Direction.WEST in self.location.exits:
            return self._attempt_move(self.location.exits[Direction.WEST])
        self.reply("< There is no exit in that direction.")
    cmd_W = cmd_WEST

    def _attempt_move(self, exit_):
        if exit_.requirement:
            pass # TODO - check requirement object is in our inventory; unlock the door if so
        if exit_.locked:
            self.reply("< This exit is locked; you need {}".format(exit_.requirement.name))
            return
        self.location = exit_.destination
        self.cmd_LOOK('look', [])
       


def fractal_room_gen(parent_room, divider, random, threshold=1, depth=0, rooms=None):
    print(' ' * depth + 'parent room:', parent_room)
    new_rooms = []
    while random.random() < threshold:
        remaining_directions = list(set(Direction) - set(parent_room.exits))
        if not remaining_directions:
            break
        direction = random.choice(remaining_directions)
        xpos = direction.value[0] + parent_room.x
        ypos = direction.value[1] + parent_room.y

        if existing_neighbour := parent_room.game.rooms.get((xpos, ypos)):
            # connect the two rooms
            print(' '* depth, f"Connect existing room {existing_neighbour} at {xpos}, {ypos}")
            room = existing_neighbour
            existing_neighbour.exits[direction.opposite()] = Exit(destination=parent_room)
        else:
            name = None
            taken_names = [room.name for room in parent_room.game.rooms.values()]
            # TODO - what if there are more rooms than possible combinations?
            while name is None or name in taken_names:
                adj = random.choice(adjectives)
                an = 'an' if adj[0] in 'aeiouL' else 'a'
                name = ' '.join((random.choice(('the', an)), adj, random.choice(room_nouns)))
            room = Room(xpos, ypos, name=name, id=len(parent_room.game.rooms),
                        description=f"It sure is a location on this map",
                        game=parent_room.game)
            room.game.rooms[(xpos, ypos)] = room
            if rooms is not None:
                rooms.append(room)
            new_rooms.append(room)
            room.exits[direction.opposite()] = Exit(destination=parent_room)
            parent_room.exits[direction] = Exit(destination=room)

        print(' ' * depth, room)
        threshold /= divider

    # generate children for this generation of rooms at the end rather than as-we-go
    # (traditionally recursive), which leads to a (still skewed, but) less linear map.
    for room in new_rooms:
        fractal_room_gen(room, divider, random, threshold=threshold, depth=depth+1, rooms=rooms)

class Adventure:
    def __init__(self, random_seed=None):
        self.rooms : dict[(GridPos, GridPos), Room] = dict()
        self.start_room: Room = None
        self.players: dict[str, Player] = dict()
        if random_seed is None:
            random_seed = _random.randint(1, 100000)
        self.random_seed = random_seed
        print("Random seed for Adventure is", random_seed)
        self._random = _random.Random(random_seed)

    def random(self):
        self.start_room = Room(0, 0, name="the Grand Hall", id=0, description="The starting room", game=self)
        self.rooms[(0, 0)] = self.start_room
        
        # Generate the map
        rooms = []
        fractal_room_gen(self.start_room, 1.17, random=self._random, rooms=rooms)

        # Generate the pauldron
        pauldron = Object(name="Idocrase Pauldron", description="whosoever shoulders this pauldron shoulders the weight of the world", definite=True, pauldron=True)
        rooms[-1].items.add(pauldron)
        print("pauldron is in room {}".format(rooms[-1]))

    def add_player(self, username, reply_func, reply_all_func):
        player = Player(username, self.start_room, reply_func, reply_all_func, game=self)
        # use module random rather than map-generator random:
        item = Object(**_random.choice([
            dict(name='ball of lint', description='Fluff and dead skin'),
            dict(name='spare button', description='You don\'t recall what this was for'),
            dict(name='rusty nail', description="I'm sure that'll be useful for something"),
            dict(name='handkerchief', description="Used"),
        ]))
        player.inventory.add(item)
        self.players[username] = player
        player.reply('< You have entered the dungeon')
        return player

    def player(self, username):
        """Get player"""
        if username not in self.players:
            raise NoPlayerError()
        return self.players[username]

game = Adventure()
game.random()


if __name__ == "__main__":
    for loc, room in game.rooms.items():
        print(loc, room)
        for direction, exit_ in room.exits.items():
            print(direction.value, exit_)
            assert room.x + direction.value[0] == exit_.destination.x
            assert room.y + direction.value[1] == exit_.destination.y

