"""Twisted stuff for Button serial"""

from twisted.internet.serialport import SerialPort
from twisted.protocols.basic import LineReceiver
from twisted.internet.protocol import Protocol
import serial

class ButtonProtocol(LineReceiver):
    delimiter = b'\n'

    def __init__(self, knuxfactory):
        super().__init__()
        self.knuxfactory = knuxfactory

    # CALLBACKS

    def connectionMade(self):
        print('serial port connected')

    def lineReceived(self, line: bytes):
        line = line.decode()
        print('line received', line)
        self.knuxfactory.broadcast('BUTTON: button')
        self.flash()

    # CUSTOM FUNCTIONS

    def flash(self):
        line = "FLASH"
        print('sending line', line)
        self.sendLine(line.encode())


def setup(reactor, knuxfactory):
    proto = ButtonProtocol(knuxfactory)
    button = None
    try:
        button = SerialPort(proto, '/dev/ttyACM1', reactor, baudrate=115200)
    except serial.serialutil.SerialException:
        print("No button found")
    return button

