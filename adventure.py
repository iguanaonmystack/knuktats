"""A little text-based adventure, as a treat"""

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

@dataclass
class Player:
    name: str # twitch username
    location: Room

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
            while name is None or name in taken_names:
                adj = random.choice(adjectives)
                an = 'an' if adj[0] in 'aeiouL' else 'a'
                name = ' '.join((random.choice(('the', an)), adj, random.choice(room_nouns)))
            room = Room(xpos, ypos, name=name, id=len(parent_room.game.rooms),
                        description=f"You're in a room",
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
        self.players = list()

    def random(self):
        room = Room(0, 0, name="Grand Hall", id=0, description="You're in a room", game=self)
        self.rooms[(0, 0)] = room
        fractal_room_gen(room, 1.1)

game = Adventure()
game.random()
