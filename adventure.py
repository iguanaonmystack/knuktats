"""A little text-based adventure, as a treat"""

import types
import random

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

@dataclass
class Object:
    name: str
    description: str

@dataclass
class Exit:
    requirement: Optional[Object] = None
    locked: bool = True
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
    game: TypeAlias = 'Adventure'

class NoPlayerError(Exception):
    """Raised if there is no active player for the user who is trying to play."""

@dataclass
class Player:
    name: str # twitch username
    location: Room
    reply: types.FunctionType
    reply_all: types.FunctionType
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

    def cmd_LOOK(self, cmd, args):
        exits = ', '.join([ex.name for ex in self.location.exits.keys()])
        players = ', '.join([player.name for player in self.game.players.values() if player.location == self.location and player != self])
        self.reply("< You are in {}. {}. Exits are {}.".format(self.location.name, self.location.description, exits))
        if players:
            self.reply("< Oh, look. {} is here.".format(players))


def fractal_room_gen(parent_room, divider, threshold=1, depth=0):
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
            existing_neighbour.exits[direction.opposite()] = Exit(destination=room)
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
            new_rooms.append(room)
            room.exits[direction.opposite()] = Exit(destination=parent_room)
            parent_room.exits[direction] = Exit(destination=room)

        print(' ' * depth, room)
        threshold /= divider

    # generate children for this generation of rooms at the end rather than as-we-go
    # (traditionally recursive), which leads to a (still skewed, but) less linear map.
    for room in new_rooms:
        fractal_room_gen(room, divider, threshold=threshold, depth=depth+1)

class Adventure:
    def __init__(self):
        self.rooms : dict[(GridPos, GridPos), Room] = dict()
        self.start_room: Room = None
        self.players: dict[str, Player] = dict()

    def random(self):
        self.start_room = Room(0, 0, name="the Grand Hall", id=0, description="The starting room", game=self)
        self.rooms[(0, 0)] = self.start_room
        fractal_room_gen(self.start_room, 1.1)

    def add_player(self, username, reply_func, reply_all_func):
        player = Player(username, self.start_room, reply_func, reply_all_func, self)
        self.players[username] = player
        player.reply('< You have entered the dungeon')

    def player(self, username):
        """Get player"""
        if username not in self.players:
            raise NoPlayerError()
        return self.players[username]

game = Adventure()
game.random()
