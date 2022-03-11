#!/usr/bin/python3
import cgi
import io
import os
import sys
import random
from collections import namedtuple
from PIL import Image, ImageFont, ImageDraw


def generate_tats(letters):
    filename = "knuckles.png"
    im = Image.open(filename)
    fillcolor = "#004000"
    shadowcolor = "white"
    draw = ImageDraw.Draw(im)
    fontpath = "xband-ro.ttf"

    # Calculate point size ratio
    font = ImageFont.truetype(fontpath, 10)
    ascent, descent = font.getmetrics()
    (width, baseline), (offset_x, offset_y) = font.font.getsize("YW")
    height = ascent - offset_y
    pixels_per_point = height / 10

    # Letters and positions
    letters = letters.replace(" ", "")[:8]
    if len(letters) < 8:
        letters += " " * (8 - len(letters))
    positions = [
        (33, 130),
        (85, 114),
        (144,101),
        (217,87),
        (366,88),
        (435,96),
        (509,112),
        (568,123),
    ]


    for letter, pos in zip(letters, positions):
        height = 40
        pointsize = int(height / pixels_per_point)
        font = ImageFont.truetype(fontpath, pointsize)
        x = pos[0]
        y = pos[1]

        # thicker border
        #draw.text((x-1, y-1), letter, font=font, fill=shadowcolor)
        #draw.text((x+1, y-1), letter, font=font, fill=shadowcolor)
        #draw.text((x-1, y+1), letter, font=font, fill=shadowcolor)
        #draw.text((x+1, y+1), letter, font=font, fill=shadowcolor)

        # now draw the text over it
        draw.text((x, y), letter, font=font, fill=fillcolor)

    #im.save("out.png")
    buf = io.BytesIO()
    im.save(buf, 'PNG', **im.info)
    return buf.getvalue()

if __name__ == '__main__':
    query_string = os.environ['QUERY_STRING']
    query_string_params = cgi.parse_qs(query_string)
    letters = query_string_params.get("t", ["KNUK TATS"])[0]
    sys.stdout.buffer.write(b"Content-Type: image/png\r\n\r\n")
    im.save(sys.stdout.buffer, 'PNG', **im.info)
    sys.stdout.buffer.write(generate_tats(letters))

