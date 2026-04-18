# MIT License
#
# Copyright (c) 2026 ARC Prize Foundation
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.

import math
from collections import deque
from typing import Optional, TypedDict

import numpy as np
from arcengine import (
    ActionInput,
    ARCBaseGame,
    Camera,
    GameAction,
    Level,
    RenderableUserDisplay,
    Sprite,
)

sprites = {
    "ayrdgendzn": Sprite(
        pixels=[
            [9, 9, 9],
            [9, -1, 9],
            [-1, -1, 9],
            [-1, -1, 9],
        ],
        name="ayrdgendzn",
        visible=True,
        collidable=True,
        tags=["gljpmsnsnx"],
    ),
    "bdahvvicge": Sprite(
        pixels=[
            [-1, 5, 5, 5, -1],
            [5, -1, -1, -1, 5],
            [5, -1, -1, -1, -1],
            [5, -1, -1, -1, -1],
            [-1, 5, -1, -1, -1],
        ],
        name="bdahvvicge",
        visible=True,
        collidable=True,
        tags=["gljpmsnsnx", "sys_click"],
    ),
    "bvrpiabnip": Sprite(
        pixels=[
            [14, -1],
            [14, -1],
            [14, 14],
            [-1, 14],
            [-1, 14],
        ],
        name="bvrpiabnip",
        visible=True,
        collidable=True,
        tags=["gljpmsnsnx", "dmfgetmeus"],
    ),
    "bygbqopxpx": Sprite(
        pixels=[
            [12, 12, 12],
            [12, 12, 12],
            [12, 12, 12],
        ],
        name="bygbqopxpx",
        visible=True,
        collidable=True,
        tags=["gljpmsnsnx"],
    ),
    "bzlvolgaii": Sprite(
        pixels=[
            [-1, 8],
            [8, 8],
            [-1, 8],
        ],
        name="bzlvolgaii",
        visible=True,
        collidable=True,
        tags=["gljpmsnsnx"],
    ),
    "cbisykcsod": Sprite(
        pixels=[
            [-1, -1, -1, 12, -1, -1, -1, 12, -1, -1, -1],
            [-1, -1, 12, -1, 12, -1, 12, -1, 12, -1, -1],
            [-1, 12, 12, -1, 12, -1, 12, -1, 12, 12, -1],
            [12, -1, -1, -1, 12, -1, 12, -1, -1, -1, 12],
            [-1, 12, 12, 12, -1, -1, -1, 12, 12, 12, -1],
            [-1, -1, -1, 12, 12, -1, 12, 12, -1, -1, -1],
            [-1, 12, 12, 12, -1, -1, -1, 12, 12, 12, -1],
            [-1, -1, -1, 12, -1, -1, -1, 12, -1, -1, -1],
            [-1, 12, 12, 12, -1, -1, -1, 12, 12, 12, -1],
            [-1, -1, -1, 12, 12, -1, 12, 12, -1, -1, -1],
            [-1, 12, 12, 12, -1, -1, -1, 12, 12, 12, -1],
            [12, -1, -1, -1, 12, -1, 12, -1, -1, -1, 12],
            [-1, 12, 12, -1, 12, -1, 12, -1, 12, 12, -1],
            [-1, -1, 12, -1, 12, -1, 12, -1, 12, -1, -1],
            [-1, -1, -1, 12, -1, -1, -1, 12, -1, -1, -1],
        ],
        name="cbisykcsod",
        visible=True,
        collidable=True,
        layer=-11,
    ),
    "cqudpppobe": Sprite(
        pixels=[
            [9, 9],
            [9, 9],
            [9, 9],
        ],
        name="cqudpppobe",
        visible=True,
        collidable=True,
        tags=["gljpmsnsnx"],
    ),
    "dixkmhikii": Sprite(
        pixels=[
            [11, -1, -1, -1],
            [11, 11, 11, 11],
            [-1, -1, -1, 11],
        ],
        name="dixkmhikii",
        visible=True,
        collidable=True,
        tags=["gljpmsnsnx"],
    ),
    "dlcwjcwyoc": Sprite(
        pixels=[
            [10],
            [10],
            [10],
            [10],
            [10],
            [10],
            [10],
            [10],
            [10],
            [10],
            [10],
            [10],
            [10],
            [10],
            [10],
            [10],
            [10],
            [10],
            [10],
            [10],
            [10],
            [10],
            [10],
            [10],
            [10],
            [10],
            [10],
            [10],
            [10],
            [10],
            [10],
            [10],
            [10],
            [10],
            [10],
            [10],
            [10],
            [10],
            [10],
            [10],
            [10],
        ],
        name="dlcwjcwyoc",
        visible=True,
        collidable=True,
        tags=["edyhkfhkcf", "pwbzvhvyzx", "zxikvwjsyl"],
        layer=-5,
    ),
    "ezdsyuixsn": Sprite(
        pixels=[
            [10, 10, 10, 10, 10, 10, 10, 10, 10, 10, 10, 10, 10, 10, 10, 10, 10, 10, 10, 10, 10, 10, 10, 10, 10, 10, 10, 10, 10, 10, 10, 10, 10, 10, 10, 10, 10, 10, 10, 10, 10],
        ],
        name="ezdsyuixsn",
        visible=True,
        collidable=True,
        tags=["edyhkfhkcf", "sys_click", "ezdsyuixsn"],
        layer=-5,
    ),
    "flrtaztmgm": Sprite(
        pixels=[
            [-2, -2, -2, -2, -2, -2, -2, -2, -2, -2, -2, -2],
            [-2, -2, -2, -2, -2, -2, -2, -2, -2, -2, -2, -2],
            [-2, -2, -2, -2, -2, -2, -2, -2, -2, -2, -2, -2],
            [-2, -2, -2, -2, -2, -2, -2, -2, -2, -2, -2, -2],
            [-2, -2, -2, -2, -2, -2, -2, -2, -2, -2, -2, -2],
            [-2, -2, -2, -2, -2, -2, -2, -2, -2, -2, -2, -2],
            [-2, -2, -2, -2, -2, -2, -2, -2, -2, -2, -2, -2],
            [-2, -2, -2, -2, -2, -2, -2, -2, -2, -2, -2, -2],
            [-2, -2, -2, -2, -2, -2, -2, -2, -2, -2, -2, -2],
            [-2, -2, -2, -2, -2, -2, -2, -2, -2, -2, -2, -2],
            [-2, -2, -2, -2, -2, -2, -2, -2, -2, -2, -2, -2],
            [-2, -2, -2, -2, -2, -2, -2, -2, -2, -2, -2, -2],
        ],
        name="flrtaztmgm",
        visible=True,
        collidable=True,
        tags=["flrtaztmgm"],
    ),
    "fsiruetubh": Sprite(
        pixels=[
            [9, -1, -1],
            [9, -1, -1],
            [9, 9, 9],
        ],
        name="fsiruetubh",
        visible=True,
        collidable=True,
        tags=["gljpmsnsnx"],
    ),
    "fvjhjlhjuf": Sprite(
        pixels=[
            [8, -1],
            [8, 8],
            [8, -1],
        ],
        name="fvjhjlhjuf",
        visible=True,
        collidable=True,
        tags=["gljpmsnsnx"],
    ),
    "gpzuzhlrhg": Sprite(
        pixels=[
            [-1, 14, -1],
            [-1, 14, -1],
            [14, 14, 14],
        ],
        name="gpzuzhlrhg",
        visible=True,
        collidable=True,
        tags=["gljpmsnsnx"],
    ),
    "gvfzzaatcv": Sprite(
        pixels=[
            [-1, -1, 14, -1, -1],
            [-1, 14, -1, 14, -1],
            [14, -1, -1, -1, 14],
        ],
        name="gvfzzaatcv",
        visible=True,
        collidable=True,
        tags=["gljpmsnsnx"],
    ),
    "hfkrronohx": Sprite(
        pixels=[
            [-1, 5, -1, 5, -1],
            [5, 5, 5, 5, 5],
            [5, 5, 5, 5, 5],
            [-1, 5, -1, 5, -1],
        ],
        name="hfkrronohx",
        visible=True,
        collidable=True,
        tags=["gljpmsnsnx", "sys_click"],
    ),
    "hjulakxurp": Sprite(
        pixels=[
            [5, 5, 5, 5, 5, 5],
        ],
        name="hjulakxurp",
        visible=True,
        collidable=True,
        tags=["gljpmsnsnx"],
    ),
    "hylzmztfzg": Sprite(
        pixels=[
            [5, -1, -1, -1, 5],
            [5, 5, 5, 5, 5],
        ],
        name="hylzmztfzg",
        visible=True,
        collidable=True,
        tags=["gljpmsnsnx", "sys_click"],
    ),
    "jewbedvusb": Sprite(
        pixels=[
            [5, 5, 5, 5],
            [-1, 5, 5, -1],
        ],
        name="jewbedvusb",
        visible=True,
        collidable=True,
        tags=["gljpmsnsnx", "sys_click"],
    ),
    "jidgddyrxm": Sprite(
        pixels=[
            [5, -1, -1, -1],
            [5, -1, -1, -1],
            [5, -1, -1, -1],
            [5, 5, 5, 5],
        ],
        name="jidgddyrxm",
        visible=True,
        collidable=True,
        tags=["gljpmsnsnx", "sys_click"],
    ),
    "jsfvegkkzt": Sprite(
        pixels=[
            [-1, 5, -1, -1],
            [5, 5, 5, 5],
        ],
        name="jsfvegkkzt",
        visible=True,
        collidable=True,
        tags=["gljpmsnsnx", "sys_click"],
    ),
    "mcboadguwj": Sprite(
        pixels=[
            [5],
            [5],
            [5],
            [5],
            [5],
            [5],
        ],
        name="mcboadguwj",
        visible=True,
        collidable=True,
        tags=["gljpmsnsnx"],
    ),
    "nkambdndiv": Sprite(
        pixels=[
            [-1, -1, 11, -1, -1],
            [-1, 11, 11, 11, -1],
            [11, 11, 11, 11, 11],
        ],
        name="nkambdndiv",
        visible=True,
        collidable=True,
        tags=["gljpmsnsnx"],
    ),
    "noaqoztjku": Sprite(
        pixels=[
            [5, 5, 5, -1, -1],
            [-1, -1, 5, -1, -1],
            [-1, -1, 5, -1, -1],
            [-1, -1, 5, 5, 5],
        ],
        name="noaqoztjku",
        visible=True,
        collidable=True,
        tags=["gljpmsnsnx", "sys_click"],
    ),
    "nrgjumocvu": Sprite(
        pixels=[
            [5, 5, 5],
            [5, -1, 5],
            [-1, 5, -1],
        ],
        name="nrgjumocvu",
        visible=True,
        collidable=True,
        tags=["gljpmsnsnx"],
    ),
    "ogmsxhaplk": Sprite(
        pixels=[
            [11, 11],
            [-1, 11],
        ],
        name="ogmsxhaplk",
        visible=True,
        collidable=True,
    ),
    "ozczvjrlvj": Sprite(
        pixels=[
            [11, -1, -1, -1, -1, -1, -1, -1, -1, -1, -1, -1, 11],
            [-1, -1, -1, -1, -1, -1, -1, -1, -1, -1, -1, -1, -1],
            [11, -1, -1, -1, -1, -1, -1, -1, -1, -1, -1, -1, 11],
        ],
        name="ozczvjrlvj",
        visible=True,
        collidable=True,
    ),
    "poltvpjvmx": Sprite(
        pixels=[
            [-1, 12, -1],
            [12, 12, 12],
            [-1, 12, 12],
        ],
        name="poltvpjvmx",
        visible=True,
        collidable=True,
        tags=["gljpmsnsnx"],
    ),
    "qbnxtboqne": Sprite(
        pixels=[
            [15, -1, -1, -1],
            [15, -1, 15, 15],
            [15, 15, 15, -1],
        ],
        name="qbnxtboqne",
        visible=True,
        collidable=True,
        tags=["gljpmsnsnx"],
    ),
    "qdwjaukgpe": Sprite(
        pixels=[
            [5, 5, 5],
            [-1, -1, 5],
            [-1, -1, 5],
        ],
        name="qdwjaukgpe",
        visible=True,
        collidable=True,
        tags=["gljpmsnsnx", "sys_click"],
    ),
    "qipnjfgkkc": Sprite(
        pixels=[
            [9, 9, 9, 9, -1],
            [-1, -1, 9, 9, -1],
            [-1, -1, -1, 9, 9],
            [-1, -1, -1, 9, -1],
        ],
        name="qipnjfgkkc",
        visible=True,
        collidable=True,
        tags=["gljpmsnsnx"],
    ),
    "qmeteyzpbi": Sprite(
        pixels=[
            [9, -1, -1, -1, -1],
            [-1, 9, 9, 9, 9],
            [-1, 9, -1, -1, -1],
        ],
        name="qmeteyzpbi",
        visible=True,
        collidable=True,
        tags=["gljpmsnsnx"],
    ),
    "razhanllyi": Sprite(
        pixels=[
            [5, 5, -1, -1],
            [-1, 5, -1, 5],
            [-1, 5, 5, 5],
        ],
        name="razhanllyi",
        visible=True,
        collidable=True,
        tags=["gljpmsnsnx"],
    ),
    "rgxjiyepyh": Sprite(
        pixels=[
            [-1, -1, 11],
            [-1, 11, -1],
            [-1, 11, -1],
            [11, 11, 11],
            [-1, 11, -1],
        ],
        name="rgxjiyepyh",
        visible=True,
        collidable=True,
        tags=["gljpmsnsnx"],
    ),
    "rkowgfsvgp": Sprite(
        pixels=[
            [-1, 5, 5],
            [5, 5, -1],
            [5, -1, -1],
        ],
        name="rkowgfsvgp",
        visible=True,
        collidable=True,
        tags=["gljpmsnsnx"],
    ),
    "sezinyfuyf": Sprite(
        pixels=[
            [5, 5, 5, 5, -1],
            [-1, -1, -1, 5, -1],
            [-1, -1, -1, 5, 5],
            [-1, -1, -1, -1, 5],
            [-1, -1, 5, 5, 5],
        ],
        name="sezinyfuyf",
        visible=True,
        collidable=True,
        tags=["gljpmsnsnx", "sys_click"],
    ),
    "siwmqkomrd": Sprite(
        pixels=[
            [-1, -1, 15],
            [15, 15, 15],
            [15, -1, -1],
        ],
        name="siwmqkomrd",
        visible=True,
        collidable=True,
        tags=["gljpmsnsnx"],
    ),
    "sllpppnezc": Sprite(
        pixels=[
            [0, 0, 0, -1, -1],
            [-1, -1, 0, -1, -1],
            [-1, -1, 0, -1, -1],
            [-1, -1, 0, 0, 0],
        ],
        name="sllpppnezc",
        visible=True,
        collidable=True,
        layer=5,
    ),
    "tsjkpdckto": Sprite(
        pixels=[
            [5, 5, 5],
            [-1, -1, 5],
            [-1, -1, 5],
            [-1, -1, 5],
            [-1, -1, 5],
        ],
        name="tsjkpdckto",
        visible=True,
        collidable=True,
        tags=["gljpmsnsnx", "sys_click"],
    ),
    "ucyadwewwc": Sprite(
        pixels=[
            [5],
            [5],
            [5],
            [5],
            [5],
            [5],
        ],
        name="ucyadwewwc",
        visible=True,
        collidable=True,
        tags=["gljpmsnsnx", "sys_click"],
    ),
    "uheevkztwx": Sprite(
        pixels=[
            [15, 15, 15, -1, 15],
            [-1, -1, 15, 15, 15],
        ],
        name="uheevkztwx",
        visible=True,
        collidable=True,
        tags=["gljpmsnsnx"],
    ),
    "ujqxnvjoap": Sprite(
        pixels=[
            [5, 5, -1, -1, -1],
            [5, -1, -1, -1, -1],
            [5, 5, 5, 5, 5],
        ],
        name="ujqxnvjoap",
        visible=True,
        collidable=True,
        tags=["gljpmsnsnx", "sys_click"],
    ),
    "vrfjzqaker": Sprite(
        pixels=[
            [11],
        ],
        name="vrfjzqaker",
        visible=True,
        collidable=True,
        tags=["vrfjzqaker"],
        layer=-4,
    ),
    "wexprfkuze": Sprite(
        pixels=[
            [-1, -1, -1, 15, 15, 15, 15, 15, -1, -1, -1],
            [-1, 15, 15, 15, -1, 15, 15, 15, 15, 15, -1],
            [-1, 15, 15, 15, -1, 15, -1, 15, 15, 15, -1],
            [15, 15, 15, 15, 15, 15, -1, 15, 15, 15, 15],
            [-1, -1, 15, 15, -1, 15, -1, 15, 15, -1, -1],
            [-1, -1, -1, 15, -1, 15, 15, 15, -1, -1, -1],
            [-1, -1, -1, 15, 15, 15, 15, 15, -1, -1, -1],
        ],
        name="wexprfkuze",
        visible=False,
        collidable=True,
    ),
    "wfqvujekdi": Sprite(
        pixels=[
            [-1, -1, 12, -1],
            [12, 12, 12, -1],
            [12, 12, 12, 12],
            [12, -1, -1, -1],
        ],
        name="wfqvujekdi",
        visible=True,
        collidable=True,
        tags=["gljpmsnsnx"],
    ),
    "wroxfpaeeo": Sprite(
        pixels=[
            [8, 8, -1],
            [-1, 8, -1],
            [-1, 8, 8],
        ],
        name="wroxfpaeeo",
        visible=True,
        collidable=True,
        tags=["gljpmsnsnx", "xnpsicjqxc"],
        layer=-2,
    ),
    "wyxvlfjfoi": Sprite(
        pixels=[
            [12, 12, 12, 12],
        ],
        name="wyxvlfjfoi",
        visible=True,
        collidable=True,
        tags=["gljpmsnsnx"],
    ),
    "xjpqgyadus": Sprite(
        pixels=[
            [5, 5],
            [-1, 5],
        ],
        name="xjpqgyadus",
        visible=True,
        collidable=True,
        tags=["gljpmsnsnx", "sys_click"],
    ),
    "xusbtwzcmm": Sprite(
        pixels=[
            [-1, -1, 5],
            [-1, -1, 5],
            [-1, 5, 5],
            [-1, 5, -1],
            [5, 5, -1],
            [5, -1, -1],
            [5, -1, -1],
        ],
        name="xusbtwzcmm",
        visible=True,
        collidable=True,
        tags=["gljpmsnsnx", "sys_click"],
    ),
    "ykqcrphnko": Sprite(
        pixels=[
            [-1, 12, 12, -1],
            [-1, -1, 12, -1],
            [12, 12, 12, 12],
        ],
        name="ykqcrphnko",
        visible=True,
        collidable=True,
        tags=["gljpmsnsnx", "fmxjsieygg"],
        layer=-1,
    ),
    "zxikvwjsyl": Sprite(
        pixels=[
            [10],
            [10],
            [10],
            [10],
            [10],
            [10],
            [10],
            [10],
            [10],
            [10],
            [10],
            [10],
            [10],
            [10],
            [10],
            [10],
            [10],
            [10],
            [10],
            [10],
            [10],
            [10],
            [10],
            [10],
            [10],
            [10],
            [10],
            [10],
            [10],
            [10],
            [10],
            [10],
            [10],
            [10],
            [10],
            [10],
            [10],
            [10],
            [10],
            [10],
            [10],
        ],
        name="zxikvwjsyl",
        visible=True,
        collidable=True,
        tags=["edyhkfhkcf", "sys_click", "zxikvwjsyl"],
        layer=-5,
    ),
}
levels = [
    # Level 1
    Level(
        sprites=[
            sprites["dlcwjcwyoc"].clone().set_position(10, 0),
            sprites["qdwjaukgpe"].clone().set_position(6, 5),
            sprites["vrfjzqaker"].clone().set_position(19, 15),
            sprites["vrfjzqaker"].clone().set_position(17, 17),
            sprites["vrfjzqaker"].clone().set_position(17, 16),
            sprites["vrfjzqaker"].clone().set_position(17, 15),
            sprites["vrfjzqaker"].clone().set_position(18, 15),
        ],
        grid_size=(21, 21),
        data={
            "StepCounter": 64,
            "edyhkfhkcf": ["zxikvwjsyl", None],
        },
    ),
    # Level 2
    Level(
        sprites=[
            sprites["noaqoztjku"].clone().set_position(15, 6),
            sprites["vrfjzqaker"].clone().set_position(5, 14),
            sprites["vrfjzqaker"].clone().set_position(1, 17),
            sprites["vrfjzqaker"].clone().set_position(4, 14),
            sprites["vrfjzqaker"].clone().set_position(3, 14),
            sprites["vrfjzqaker"].clone().set_position(3, 15),
            sprites["vrfjzqaker"].clone().set_position(3, 16),
            sprites["vrfjzqaker"].clone().set_position(3, 17),
            sprites["vrfjzqaker"].clone().set_position(2, 17),
            sprites["zxikvwjsyl"].clone().set_position(12, -3),
        ],
        grid_size=(21, 21),
        data={
            "StepCounter": 64,
            "edyhkfhkcf": ["zxikvwjsyl", None],
        },
    ),
    # Level 3
    Level(
        sprites=[
            sprites["ezdsyuixsn"].clone().set_position(-5, 16),
            sprites["jewbedvusb"].clone().set_position(15, 9),
            sprites["jidgddyrxm"].clone().set_position(4, 7),
            sprites["vrfjzqaker"].clone().set_position(14, 17),
            sprites["vrfjzqaker"].clone().set_position(14, 1),
            sprites["vrfjzqaker"].clone().set_position(11, 4),
            sprites["vrfjzqaker"].clone().set_position(11, 14),
            sprites["vrfjzqaker"].clone().set_position(11, 17),
            sprites["vrfjzqaker"].clone().set_position(11, 1),
            sprites["vrfjzqaker"].clone().set_position(3, 14),
            sprites["vrfjzqaker"].clone().set_position(4, 14),
            sprites["vrfjzqaker"].clone().set_position(5, 14),
            sprites["vrfjzqaker"].clone().set_position(6, 14),
            sprites["vrfjzqaker"].clone().set_position(4, 15),
            sprites["vrfjzqaker"].clone().set_position(5, 15),
            sprites["vrfjzqaker"].clone().set_position(3, 4),
            sprites["vrfjzqaker"].clone().set_position(4, 4),
            sprites["vrfjzqaker"].clone().set_position(5, 4),
            sprites["vrfjzqaker"].clone().set_position(6, 4),
            sprites["vrfjzqaker"].clone().set_position(5, 3),
            sprites["vrfjzqaker"].clone().set_position(4, 3),
            sprites["vrfjzqaker"].clone().set_position(11, 15),
            sprites["vrfjzqaker"].clone().set_position(11, 16),
            sprites["vrfjzqaker"].clone().set_position(12, 17),
            sprites["vrfjzqaker"].clone().set_position(13, 17),
            sprites["vrfjzqaker"].clone().set_position(11, 3),
            sprites["vrfjzqaker"].clone().set_position(11, 2),
            sprites["vrfjzqaker"].clone().set_position(12, 1),
            sprites["vrfjzqaker"].clone().set_position(13, 1),
        ],
        grid_size=(21, 21),
        data={
            "StepCounter": 128,
            "edyhkfhkcf": ["zxikvwjsyl", None],
        },
    ),
    # Level 4
    Level(
        sprites=[
            sprites["ezdsyuixsn"].clone().set_position(-6, 3),
            sprites["hylzmztfzg"].clone().set_position(4, 6),
            sprites["ucyadwewwc"].clone().set_position(6, 10),
            sprites["vrfjzqaker"].clone().set_position(15, 11),
            sprites["vrfjzqaker"].clone().set_position(15, 7),
            sprites["vrfjzqaker"].clone().set_position(11, 7),
            sprites["vrfjzqaker"].clone().set_position(11, 11),
            sprites["vrfjzqaker"].clone().set_position(13, 3),
            sprites["vrfjzqaker"].clone().set_position(13, 15),
            sprites["vrfjzqaker"].clone().set_position(13, 8),
            sprites["vrfjzqaker"].clone().set_position(13, 10),
            sprites["vrfjzqaker"].clone().set_position(12, 7),
            sprites["vrfjzqaker"].clone().set_position(13, 7),
            sprites["vrfjzqaker"].clone().set_position(14, 7),
            sprites["vrfjzqaker"].clone().set_position(11, 6),
            sprites["vrfjzqaker"].clone().set_position(15, 6),
            sprites["vrfjzqaker"].clone().set_position(13, 6),
            sprites["vrfjzqaker"].clone().set_position(13, 5),
            sprites["vrfjzqaker"].clone().set_position(13, 4),
            sprites["vrfjzqaker"].clone().set_position(12, 11),
            sprites["vrfjzqaker"].clone().set_position(13, 11),
            sprites["vrfjzqaker"].clone().set_position(14, 11),
            sprites["vrfjzqaker"].clone().set_position(11, 12),
            sprites["vrfjzqaker"].clone().set_position(15, 12),
            sprites["vrfjzqaker"].clone().set_position(13, 12),
            sprites["vrfjzqaker"].clone().set_position(13, 13),
            sprites["vrfjzqaker"].clone().set_position(13, 14),
        ],
        grid_size=(21, 21),
        data={
            "StepCounter": 128,
            "edyhkfhkcf": ["zxikvwjsyl", None],
        },
    ),
    # Level 5
    Level(
        sprites=[
            sprites["ezdsyuixsn"].clone().set_position(0, 5),
            sprites["sezinyfuyf"].clone().set_position(14, 12),
            sprites["vrfjzqaker"].clone().set_position(8, 9),
            sprites["vrfjzqaker"].clone().set_position(9, 9),
            sprites["vrfjzqaker"].clone().set_position(8, 8),
            sprites["vrfjzqaker"].clone().set_position(7, 9),
            sprites["vrfjzqaker"].clone().set_position(4, 13),
            sprites["vrfjzqaker"].clone().set_position(8, 10),
            sprites["vrfjzqaker"].clone().set_position(12, 13),
            sprites["vrfjzqaker"].clone().set_position(12, 5),
            sprites["vrfjzqaker"].clone().set_position(4, 5),
            sprites["vrfjzqaker"].clone().set_position(6, 9),
            sprites["vrfjzqaker"].clone().set_position(10, 9),
            sprites["vrfjzqaker"].clone().set_position(5, 5),
            sprites["vrfjzqaker"].clone().set_position(6, 5),
            sprites["vrfjzqaker"].clone().set_position(11, 13),
            sprites["vrfjzqaker"].clone().set_position(10, 13),
            sprites["vrfjzqaker"].clone().set_position(7, 5),
            sprites["vrfjzqaker"].clone().set_position(9, 13),
            sprites["vrfjzqaker"].clone().set_position(8, 11),
            sprites["vrfjzqaker"].clone().set_position(9, 11),
            sprites["vrfjzqaker"].clone().set_position(9, 12),
            sprites["vrfjzqaker"].clone().set_position(8, 7),
            sprites["vrfjzqaker"].clone().set_position(7, 7),
            sprites["vrfjzqaker"].clone().set_position(7, 6),
            sprites["zxikvwjsyl"].clone().set_position(3, 0),
        ],
        grid_size=(21, 21),
        data={
            "StepCounter": 128,
            "edyhkfhkcf": 0,
        },
    ),
    # Level 6
    Level(
        sprites=[
            sprites["bdahvvicge"].clone().set_position(14, 3),
            sprites["ezdsyuixsn"].clone(),
            sprites["jsfvegkkzt"].clone().set_position(17, 8),
            sprites["vrfjzqaker"].clone().set_position(4, 3),
            sprites["vrfjzqaker"].clone().set_position(1, 6),
            sprites["vrfjzqaker"].clone().set_position(2, 7),
            sprites["vrfjzqaker"].clone().set_position(3, 7),
            sprites["vrfjzqaker"].clone().set_position(4, 7),
            sprites["vrfjzqaker"].clone().set_position(2, 9),
            sprites["vrfjzqaker"].clone().set_position(3, 9),
            sprites["vrfjzqaker"].clone().set_position(3, 12),
            sprites["vrfjzqaker"].clone().set_position(2, 13),
            sprites["vrfjzqaker"].clone().set_position(4, 15),
            sprites["vrfjzqaker"].clone().set_position(3, 15),
            sprites["vrfjzqaker"].clone().set_position(2, 15),
            sprites["vrfjzqaker"].clone().set_position(5, 9),
            sprites["vrfjzqaker"].clone().set_position(4, 9),
            sprites["vrfjzqaker"].clone().set_position(4, 13),
            sprites["vrfjzqaker"].clone().set_position(5, 13),
            sprites["vrfjzqaker"].clone().set_position(1, 16),
            sprites["vrfjzqaker"].clone().set_position(4, 19),
            sprites["vrfjzqaker"].clone().set_position(5, 18),
            sprites["vrfjzqaker"].clone().set_position(5, 17),
            sprites["vrfjzqaker"].clone().set_position(5, 16),
            sprites["vrfjzqaker"].clone().set_position(7, 16),
            sprites["vrfjzqaker"].clone().set_position(7, 17),
            sprites["vrfjzqaker"].clone().set_position(7, 18),
            sprites["vrfjzqaker"].clone().set_position(8, 19),
            sprites["vrfjzqaker"].clone().set_position(11, 16),
            sprites["vrfjzqaker"].clone().set_position(10, 15),
            sprites["vrfjzqaker"].clone().set_position(9, 15),
            sprites["vrfjzqaker"].clone().set_position(8, 15),
            sprites["vrfjzqaker"].clone().set_position(10, 13),
            sprites["vrfjzqaker"].clone().set_position(9, 12),
            sprites["vrfjzqaker"].clone().set_position(9, 9),
            sprites["vrfjzqaker"].clone().set_position(10, 9),
            sprites["vrfjzqaker"].clone().set_position(8, 7),
            sprites["vrfjzqaker"].clone().set_position(9, 7),
            sprites["vrfjzqaker"].clone().set_position(10, 7),
            sprites["vrfjzqaker"].clone().set_position(7, 13),
            sprites["vrfjzqaker"].clone().set_position(8, 13),
            sprites["vrfjzqaker"].clone().set_position(8, 9),
            sprites["vrfjzqaker"].clone().set_position(7, 9),
            sprites["vrfjzqaker"].clone().set_position(11, 6),
            sprites["vrfjzqaker"].clone().set_position(8, 3),
            sprites["vrfjzqaker"].clone().set_position(7, 4),
            sprites["vrfjzqaker"].clone().set_position(7, 5),
            sprites["vrfjzqaker"].clone().set_position(7, 6),
            sprites["vrfjzqaker"].clone().set_position(5, 6),
            sprites["vrfjzqaker"].clone().set_position(5, 5),
            sprites["vrfjzqaker"].clone().set_position(5, 4),
            sprites["vrfjzqaker"].clone().set_position(9, 13),
            sprites["vrfjzqaker"].clone().set_position(3, 13),
            sprites["vrfjzqaker"].clone().set_position(9, 10),
            sprites["vrfjzqaker"].clone().set_position(3, 10),
            sprites["zxikvwjsyl"].clone().set_position(7, -1),
        ],
        grid_size=(21, 21),
        data={
            "StepCounter": 320,
            "edyhkfhkcf": 0,
        },
    ),
    # Level 7
    Level(
        sprites=[
            sprites["ezdsyuixsn"].clone().set_position(0, 5),
            sprites["hfkrronohx"].clone().set_position(5, 16),
            sprites["vrfjzqaker"].clone().set_position(9, 7),
            sprites["vrfjzqaker"].clone().set_position(7, 3),
            sprites["vrfjzqaker"].clone().set_position(8, 5),
            sprites["vrfjzqaker"].clone().set_position(7, 1),
            sprites["vrfjzqaker"].clone().set_position(9, 1),
            sprites["vrfjzqaker"].clone().set_position(11, 1),
            sprites["vrfjzqaker"].clone().set_position(13, 1),
            sprites["vrfjzqaker"].clone().set_position(15, 1),
            sprites["vrfjzqaker"].clone().set_position(17, 1),
            sprites["vrfjzqaker"].clone().set_position(17, 3),
            sprites["vrfjzqaker"].clone().set_position(16, 5),
            sprites["vrfjzqaker"].clone().set_position(15, 7),
            sprites["vrfjzqaker"].clone().set_position(16, 9),
            sprites["vrfjzqaker"].clone().set_position(8, 9),
            sprites["vrfjzqaker"].clone().set_position(7, 11),
            sprites["vrfjzqaker"].clone().set_position(17, 11),
            sprites["vrfjzqaker"].clone().set_position(17, 13),
            sprites["vrfjzqaker"].clone().set_position(7, 13),
            sprites["vrfjzqaker"].clone().set_position(9, 13),
            sprites["vrfjzqaker"].clone().set_position(11, 13),
            sprites["vrfjzqaker"].clone().set_position(13, 13),
            sprites["vrfjzqaker"].clone().set_position(15, 13),
            sprites["vrfjzqaker"].clone().set_position(11, 10),
            sprites["vrfjzqaker"].clone().set_position(13, 10),
            sprites["vrfjzqaker"].clone().set_position(11, 4),
            sprites["vrfjzqaker"].clone().set_position(13, 4),
            sprites["vrfjzqaker"].clone().set_position(9, 10),
            sprites["vrfjzqaker"].clone().set_position(15, 10),
            sprites["vrfjzqaker"].clone().set_position(9, 4),
            sprites["vrfjzqaker"].clone().set_position(15, 4),
            sprites["vrfjzqaker"].clone().set_position(11, 12),
            sprites["vrfjzqaker"].clone().set_position(11, 11),
            sprites["vrfjzqaker"].clone().set_position(9, 12),
            sprites["vrfjzqaker"].clone().set_position(9, 11),
            sprites["vrfjzqaker"].clone().set_position(13, 2),
            sprites["vrfjzqaker"].clone().set_position(13, 3),
            sprites["vrfjzqaker"].clone().set_position(15, 2),
            sprites["vrfjzqaker"].clone().set_position(15, 3),
            sprites["vrfjzqaker"].clone().set_position(10, 12),
            sprites["vrfjzqaker"].clone().set_position(10, 11),
            sprites["vrfjzqaker"].clone().set_position(14, 3),
            sprites["vrfjzqaker"].clone().set_position(14, 2),
            sprites["xusbtwzcmm"].clone().set_position(17, 13),
            sprites["zxikvwjsyl"].clone().set_position(3, 0),
        ],
        grid_size=(21, 21),
        data={
            "StepCounter": 320,
            "edyhkfhkcf": 0,
        },
    ),
    # Level 8
    Level(
        sprites=[
            sprites["ezdsyuixsn"].clone().set_position(0, 5),
            sprites["tsjkpdckto"].clone().set_position(7, 7),
            sprites["ujqxnvjoap"].clone().set_position(13, 13),
            sprites["vrfjzqaker"].clone().set_position(16, 3),
            sprites["vrfjzqaker"].clone().set_position(17, 3),
            sprites["vrfjzqaker"].clone().set_position(18, 3),
            sprites["vrfjzqaker"].clone().set_position(18, 4),
            sprites["vrfjzqaker"].clone().set_position(18, 5),
            sprites["vrfjzqaker"].clone().set_position(18, 6),
            sprites["vrfjzqaker"].clone().set_position(18, 7),
            sprites["vrfjzqaker"].clone().set_position(18, 8),
            sprites["vrfjzqaker"].clone().set_position(17, 8),
            sprites["vrfjzqaker"].clone().set_position(16, 8),
            sprites["vrfjzqaker"].clone().set_position(19, 8),
            sprites["vrfjzqaker"].clone().set_position(20, 8),
            sprites["vrfjzqaker"].clone().set_position(20, 7),
            sprites["vrfjzqaker"].clone().set_position(20, 6),
            sprites["vrfjzqaker"].clone().set_position(19, 6),
            sprites["vrfjzqaker"].clone().set_position(8, 3),
            sprites["vrfjzqaker"].clone().set_position(7, 3),
            sprites["vrfjzqaker"].clone().set_position(6, 3),
            sprites["vrfjzqaker"].clone().set_position(6, 4),
            sprites["vrfjzqaker"].clone().set_position(6, 5),
            sprites["vrfjzqaker"].clone().set_position(6, 6),
            sprites["vrfjzqaker"].clone().set_position(6, 7),
            sprites["vrfjzqaker"].clone().set_position(8, 8),
            sprites["vrfjzqaker"].clone().set_position(7, 8),
            sprites["vrfjzqaker"].clone().set_position(6, 8),
            sprites["vrfjzqaker"].clone().set_position(5, 8),
            sprites["vrfjzqaker"].clone().set_position(5, 6),
            sprites["vrfjzqaker"].clone().set_position(4, 6),
            sprites["vrfjzqaker"].clone().set_position(4, 7),
            sprites["vrfjzqaker"].clone().set_position(4, 8),
            sprites["vrfjzqaker"].clone().set_position(8, 14),
            sprites["vrfjzqaker"].clone().set_position(7, 14),
            sprites["vrfjzqaker"].clone().set_position(6, 14),
            sprites["vrfjzqaker"].clone().set_position(6, 15),
            sprites["vrfjzqaker"].clone().set_position(6, 16),
            sprites["vrfjzqaker"].clone().set_position(6, 17),
            sprites["vrfjzqaker"].clone().set_position(6, 18),
            sprites["vrfjzqaker"].clone().set_position(6, 19),
            sprites["vrfjzqaker"].clone().set_position(7, 19),
            sprites["vrfjzqaker"].clone().set_position(8, 19),
            sprites["vrfjzqaker"].clone().set_position(5, 14),
            sprites["vrfjzqaker"].clone().set_position(4, 14),
            sprites["vrfjzqaker"].clone().set_position(4, 15),
            sprites["vrfjzqaker"].clone().set_position(4, 16),
            sprites["vrfjzqaker"].clone().set_position(5, 16),
            sprites["vrfjzqaker"].clone().set_position(16, 14),
            sprites["vrfjzqaker"].clone().set_position(17, 14),
            sprites["vrfjzqaker"].clone().set_position(18, 14),
            sprites["vrfjzqaker"].clone().set_position(19, 14),
            sprites["vrfjzqaker"].clone().set_position(20, 14),
            sprites["vrfjzqaker"].clone().set_position(20, 15),
            sprites["vrfjzqaker"].clone().set_position(18, 15),
            sprites["vrfjzqaker"].clone().set_position(18, 16),
            sprites["vrfjzqaker"].clone().set_position(19, 16),
            sprites["vrfjzqaker"].clone().set_position(20, 16),
            sprites["vrfjzqaker"].clone().set_position(18, 17),
            sprites["vrfjzqaker"].clone().set_position(18, 18),
            sprites["vrfjzqaker"].clone().set_position(18, 19),
            sprites["vrfjzqaker"].clone().set_position(17, 19),
            sprites["vrfjzqaker"].clone().set_position(16, 19),
            sprites["zxikvwjsyl"].clone().set_position(3, 0),
        ],
        grid_size=(21, 21),
        data={
            "StepCounter": 320,
            "edyhkfhkcf": 0,
        },
    ),
]
BACKGROUND_COLOR = 9
PADDING_COLOR = 5
kevchhhmha = -1
qxfymojgwa = 0
khaeijgkpw = 1
ymbzgqpfgw = 2
cokaikipqv = 3
qqcnwokqtb = 4
bwtkxvpmxp = 5
dsjxzfeaay = 6
babxulumwz = 7
iuqegctory = 8
utwrvgdxfn = 9
segaklzkcp = 10
dqailkzmtf = 11
rrdyedysxy = 12
dasrwajgpe = 13
usrptgpomh = 14
eqoiopyobo = 15
akedgxijnx = cokaikipqv
xwfrtwinpo = qxfymojgwa
liirwepfdj = BACKGROUND_COLOR
tuovamceti = bwtkxvpmxp
kddxpzgafq = qqcnwokqtb
euzrpaakrj = segaklzkcp


class hpnnoufcuc(RenderableUserDisplay):
    def __init__(self, oecwkhnijk: "Ar25", fefqmpmfqu: int, rfftsilxlp: int = 1):
        self.fefqmpmfqu: int = fefqmpmfqu
        self.current_steps: int = fefqmpmfqu
        self.rfftsilxlp: int = max(1, rfftsilxlp)
        self.oecwkhnijk = oecwkhnijk
        self.energy_colors: list[int] = [
            dqailkzmtf,
            rrdyedysxy,
            eqoiopyobo,
            iuqegctory,
            usrptgpomh,
        ]

    def qbypqckyqm(self, pknielutwu: int) -> None:
        self.current_steps = max(0, min(pknielutwu, self.fefqmpmfqu))

    def tihzupejat(self) -> bool:
        if self.current_steps > 0:
            self.current_steps -= 1
        return self.current_steps > 0

    def iuxztfbzql(self) -> None:
        self.current_steps = self.fefqmpmfqu

    def render_interface(self, frame: np.ndarray) -> np.ndarray:
        if self.fefqmpmfqu == 0:
            return frame
        fpfjuxlmqs: int = 64
        start_y: int = 0
        start_x: int = 63
        jwuswyyoje: int = (self.fefqmpmfqu + fpfjuxlmqs - 1) // fpfjuxlmqs
        if jwuswyyoje < 1:
            jwuswyyoje = 1
        if jwuswyyoje > len(self.energy_colors):
            jwuswyyoje = len(self.energy_colors)
        gbomrqujoq: int = fpfjuxlmqs * jwuswyyoje
        uojfddscbm: int = self.fefqmpmfqu - self.current_steps
        if uojfddscbm < 0:
            uojfddscbm = 0
        if uojfddscbm > gbomrqujoq:
            uojfddscbm = gbomrqujoq
        obauionezz: int = uojfddscbm // fpfjuxlmqs
        anejthzpxk: int = uojfddscbm % fpfjuxlmqs
        if obauionezz >= jwuswyyoje:
            obauionezz = jwuswyyoje - 1
            anejthzpxk = fpfjuxlmqs
        ocrqvjqfsf = self.energy_colors[obauionezz]
        vcoyigquau: bool = obauionezz == jwuswyyoje - 1
        for i in range(anejthzpxk, fpfjuxlmqs):
            frame[start_y + i, start_x] = ocrqvjqfsf
        if not vcoyigquau and anejthzpxk > 0:
            zphaaygjdr = self.energy_colors[obauionezz + 1]
            for i in range(anejthzpxk):
                frame[start_y + i, start_x] = zphaaygjdr
        return frame


class gdycxeziaj(RenderableUserDisplay):
    """."""

    def __init__(self, oecwkhnijk: "Ar25"):
        self.oecwkhnijk = oecwkhnijk

    def ujlfpharwy(self, vrolnlpyvl: int) -> int:
        if vrolnlpyvl == dqailkzmtf:
            return 4
        elif vrolnlpyvl == tuovamceti:
            return 3
        elif vrolnlpyvl == euzrpaakrj:
            return 3
        elif vrolnlpyvl == xwfrtwinpo:
            return 2
        elif vrolnlpyvl == liirwepfdj:
            return 1
        return 0

    def render_interface(self, frame: np.ndarray) -> np.ndarray:
        frame_height, frame_width = frame.shape
        scale = min(64 // self.oecwkhnijk.huzumkfia, 64 // self.oecwkhnijk.aqnahsxpq)
        nqsnzgwfgp = math.ceil((64 - self.oecwkhnijk.huzumkfia * scale) / 2) + 1
        qsijnilwrj = math.ceil((64 - self.oecwkhnijk.aqnahsxpq * scale) / 2) + 1
        dfmyjxsddb = self.oecwkhnijk.tfvpyidngc()
        ngewfmuylt = np.full((self.oecwkhnijk.aqnahsxpq, self.oecwkhnijk.huzumkfia), -1, dtype=int)
        for hzmlhaicav in range(self.oecwkhnijk.aqnahsxpq):
            for hawhmrorex in range(self.oecwkhnijk.huzumkfia):
                sprite = dfmyjxsddb[hzmlhaicav, hawhmrorex]
                if sprite is None:
                    continue
                kycvqcblbi = hzmlhaicav - sprite.y
                tiqvogucvv = hawhmrorex - sprite.x
                qklrsqlyzy = 0 <= tiqvogucvv < sprite.width and 0 <= kycvqcblbi < sprite.height and (sprite.pixels[kycvqcblbi, tiqvogucvv] != kevchhhmha)
                jrxgqmfjrf = sprite == self.oecwkhnijk.llludejph
                xdjxosbrhv = "pwbzvhvyzx" in sprite.tags
                folcdenxmb = None
                for uvgqszxsnw in self.oecwkhnijk.mqedygxur:
                    if uvgqszxsnw.x == hawhmrorex and uvgqszxsnw.y == hzmlhaicav:
                        folcdenxmb = uvgqszxsnw.pixels[0, 0]
                        break
                if folcdenxmb is not None:
                    kkyplokzmb = dqailkzmtf
                elif qklrsqlyzy:
                    if xdjxosbrhv:
                        kkyplokzmb = tuovamceti
                    else:
                        kkyplokzmb = xwfrtwinpo if jrxgqmfjrf else liirwepfdj
                else:
                    continue
                zgbnjdlufq = ngewfmuylt[hzmlhaicav, hawhmrorex]
                if zgbnjdlufq == -1 or self.ujlfpharwy(kkyplokzmb) > self.ujlfpharwy(zgbnjdlufq):
                    ngewfmuylt[hzmlhaicav, hawhmrorex] = kkyplokzmb
        for sprite in self.oecwkhnijk.khupblbrxc:
            jrxgqmfjrf = sprite == self.oecwkhnijk.llludejph
            xdjxosbrhv = "pwbzvhvyzx" in sprite.tags
            for i in range(sprite.pixels.shape[0]):
                for ezmsggksvd in range(sprite.pixels.shape[1]):
                    if sprite.pixels[i, ezmsggksvd] > -1:
                        hawhmrorex = sprite.x + ezmsggksvd
                        hzmlhaicav = sprite.y + i
                        folcdenxmb = None
                        for uvgqszxsnw in self.oecwkhnijk.mqedygxur:
                            if uvgqszxsnw.x == hawhmrorex and uvgqszxsnw.y == hzmlhaicav:
                                folcdenxmb = uvgqszxsnw.pixels[0, 0]
                                break
                        if folcdenxmb is not None:
                            kkyplokzmb = dqailkzmtf
                        elif xdjxosbrhv:
                            kkyplokzmb = euzrpaakrj
                        else:
                            kkyplokzmb = xwfrtwinpo if jrxgqmfjrf else liirwepfdj
                        if 0 <= hawhmrorex < dfmyjxsddb.shape[1] and 0 <= hzmlhaicav < dfmyjxsddb.shape[0]:
                            idcmwgepge = dfmyjxsddb[hzmlhaicav, hawhmrorex]
                            if idcmwgepge is not None:
                                kycvqcblbi = hzmlhaicav - idcmwgepge.y
                                tiqvogucvv = hawhmrorex - idcmwgepge.x
                                qklrsqlyzy = 0 <= tiqvogucvv < idcmwgepge.width and 0 <= kycvqcblbi < idcmwgepge.height and (idcmwgepge.pixels[kycvqcblbi, tiqvogucvv] != kevchhhmha)
                                if not qklrsqlyzy and kkyplokzmb == liirwepfdj:
                                    continue
                        map_height, map_width = ngewfmuylt.shape
                        if 0 <= hawhmrorex < map_width and 0 <= hzmlhaicav < map_height:
                            zgbnjdlufq = ngewfmuylt[hzmlhaicav, hawhmrorex]
                            if zgbnjdlufq == -1 or self.ujlfpharwy(kkyplokzmb) > self.ujlfpharwy(zgbnjdlufq):
                                ngewfmuylt[hzmlhaicav, hawhmrorex] = kkyplokzmb
        for hzmlhaicav in range(self.oecwkhnijk.aqnahsxpq):
            for hawhmrorex in range(self.oecwkhnijk.huzumkfia):
                kkyplokzmb = ngewfmuylt[hzmlhaicav, hawhmrorex]
                if kkyplokzmb == -1:
                    continue
                ryzdnnmomo = hawhmrorex * scale + nqsnzgwfgp + 1
                wfwvgmoxtx = hzmlhaicav * scale + qsijnilwrj + 1
                if scale == 5:
                    if 0 <= ryzdnnmomo < frame_width and 0 <= wfwvgmoxtx < frame_height:
                        frame[wfwvgmoxtx, ryzdnnmomo] = kkyplokzmb
                elif scale == 4:
                    for dx, dy in ((0, 0), (-1, 0), (0, -1), (-1, -1)):
                        x = ryzdnnmomo + dx
                        y = wfwvgmoxtx + dy
                        if 0 <= x < frame_width and 0 <= y < frame_height:
                            frame[y, x] = kkyplokzmb
                elif scale == 3:
                    if 0 <= ryzdnnmomo - 2 < frame_width and 0 <= wfwvgmoxtx - 2 < frame_height:
                        frame[wfwvgmoxtx - 2, ryzdnnmomo - 2] = kkyplokzmb
        return frame


class gluxplkybg(TypedDict):
    khupblbrxc: list[tuple[str, int, int]]
    migkdsjrwk: list[tuple[int, int]]


class Ar25(ARCBaseGame):
    def __init__(self) -> None:
        self.cxnxzbeld = gdycxeziaj(self)
        fefqmpmfqu = 0
        self.zdrbnrjbr = hpnnoufcuc(self, fefqmpmfqu, rfftsilxlp=len(levels))
        ehifjxsph = Camera(
            background=BACKGROUND_COLOR,
            letter_box=PADDING_COLOR,
            interfaces=[self.cxnxzbeld, self.zdrbnrjbr],
        )
        self.usukvgwle: list[gluxplkybg] = []
        super().__init__(
            game_id="ar25",
            levels=levels,
            camera=ehifjxsph,
            available_actions=[1, 2, 3, 4, 5, 6, 7],
        )

    def tfeokrxpyi(self) -> None:
        """."""
        agpgjqalgv = self.current_level.get_data("StepCounter")
        if agpgjqalgv:
            self.zdrbnrjbr.fefqmpmfqu = agpgjqalgv
            self.zdrbnrjbr.iuxztfbzql()

    def zngkctyvrs(self, sprite: Sprite, runybwgioh: Sprite) -> int:
        if "zxikvwjsyl" in runybwgioh.tags:
            zrmehuuqoy = sprite.x + self.fppvvkcaqa(sprite) // 2
            return abs(zrmehuuqoy - runybwgioh.x)
        else:
            sdtbfmcgut = sprite.y + self.znirfzpefv(sprite) // 2
            return abs(sdtbfmcgut - runybwgioh.y)

    def vlnwxwcdzf(self, sprite: Sprite) -> None:
        goyuaczygh = sprite.pixels
        dqapknfnfi = np.rot90(goyuaczygh)
        jevahxujmi = goyuaczygh.shape[1]
        qwjhvoblod = goyuaczygh.shape[0]
        gynarddzug = sprite.x + jevahxujmi // 2
        jbbgooakjc = sprite.y + qwjhvoblod // 2
        new_h, new_w = dqapknfnfi.shape
        yptggrfrgo = gynarddzug - new_w // 2
        wymrczshbz = jbbgooakjc - new_h // 2
        sprite.pixels = dqapknfnfi
        sprite.set_position(yptggrfrgo, wymrczshbz)
        sprite.set_position(yptggrfrgo, wymrczshbz)

    def ciwlvhlgil(self) -> gluxplkybg:
        """."""
        lhduxvcvxy: list[tuple[int, int]] = [(s.x, s.y) for s in self.migkdsjrwk]
        tuzvcwvwfq: list[tuple[str, int, int]] = []
        for trspysetcl in self.khupblbrxc:
            wftxejjopq = "zxikvwjsyl" if "zxikvwjsyl" in trspysetcl.tags else "ezdsyuixsn" if "ezdsyuixsn" in trspysetcl.tags else ""
            tuzvcwvwfq.append((wftxejjopq, trspysetcl.x, trspysetcl.y))
        return {"migkdsjrwk": lhduxvcvxy, "khupblbrxc": tuzvcwvwfq}

    def wmpufuwdcm(self, state: gluxplkybg) -> None:
        """."""
        for i, (x, y) in enumerate(state["migkdsjrwk"]):
            s = self.migkdsjrwk[i]
            s.set_position(x, y)
        for wftxejjopq, x, y in state["khupblbrxc"]:
            if not wftxejjopq:
                continue
            trspysetcl = next((ax for ax in self.khupblbrxc if wftxejjopq in ax.tags), None)
            if trspysetcl:
                trspysetcl.set_position(x, y)
        self.hqiorgefxt()

    def on_set_level(self, level: Level) -> None:
        self.ijwojcjri = 0
        self.tikqecuwc = False
        self.mewxgwwty: bool = False
        self.cnlzdmmso: int = 0
        self.uehyvizcj = sprites["sllpppnezc"].clone()
        self.current_level.add_sprite(self.uehyvizcj)
        self.uehyvizcj._x = 500
        self.ueryufapb = {}
        self.mllqetvjb = False
        self.llludejph: Sprite | None = None
        sngtmtozd = self.current_level.grid_size
        if sngtmtozd is not None:
            self.huzumkfia = sngtmtozd[0]
            self.aqnahsxpq = sngtmtozd[1]
        self.migkdsjrwk: list[Sprite] = self.current_level.get_sprites_by_tag("gljpmsnsnx")
        self.mqedygxur: list[Sprite] = self.current_level.get_sprites_by_tag("vrfjzqaker")
        self.vakuvqumo = sprites["flrtaztmgm"].clone()
        self.vakuvqumo._layer = 0
        self.current_level.add_sprite(self.vakuvqumo)
        self.ehoxfqdzf = sprites["flrtaztmgm"].clone()
        self.ehoxfqdzf._layer = -1
        self.current_level.add_sprite(self.ehoxfqdzf)
        self.jgzwiwsnn = sprites["flrtaztmgm"].clone()
        self.jgzwiwsnn._layer = -2
        self.current_level.add_sprite(self.jgzwiwsnn)
        self.khupblbrxc = self.current_level.get_sprites_by_tag("edyhkfhkcf")
        kefcousrdq = [trspysetcl for trspysetcl in self.khupblbrxc if "pwbzvhvyzx" not in trspysetcl.tags]
        lybxqzyjle = [rhxpwsowco for rhxpwsowco in self.migkdsjrwk if "pwbzvhvyzx" not in rhxpwsowco.tags]
        self.llludejph = kefcousrdq[0] if kefcousrdq else lybxqzyjle[0] if lybxqzyjle else None
        self.hnepuikbu = next(
            (trspysetcl for trspysetcl in self.khupblbrxc if "zxikvwjsyl" in trspysetcl.tags),
            None,
        )
        self.hitrtbsoq = next(
            (trspysetcl for trspysetcl in self.khupblbrxc if "ezdsyuixsn" in trspysetcl.tags),
            None,
        )
        for eusordagn in self.migkdsjrwk:
            if "xnpsicjqxc" in eusordagn.tags and self.hnepuikbu:
                self.ueryufapb[eusordagn] = self.zngkctyvrs(eusordagn, self.hnepuikbu)
            elif "dmfgetmeus" in eusordagn.tags and self.hitrtbsoq:
                self.ueryufapb[eusordagn] = self.zngkctyvrs(eusordagn, self.hitrtbsoq)
        self.tfeokrxpyi()
        self.hqiorgefxt()
        self.etzeptsuxx()
        self.usukvgwle = []
        self.xefwpvwoh: list[Sprite] = []
        for trspysetcl in self.khupblbrxc:
            self.xefwpvwoh.append(trspysetcl)
        for rhxpwsowco in self.migkdsjrwk:
            self.xefwpvwoh.append(rhxpwsowco)
        for niavljcgw in range(len(self.xefwpvwoh) - 1, -1, -1):
            if "pwbzvhvyzx" in self.xefwpvwoh[niavljcgw].tags:
                del self.xefwpvwoh[niavljcgw]

    def fppvvkcaqa(self, s: Sprite) -> int:
        return s.pixels.shape[1] if s.pixels.shape else 0

    def znirfzpefv(self, s: Sprite) -> int:
        return s.pixels.shape[0] if s.pixels.shape else 0

    def dgbejorvab(self, s: Sprite) -> int:
        ozxyheehir = np.unique(s.pixels[s.pixels != kevchhhmha])
        if len(ozxyheehir) == 0:
            return -1
        return int(ozxyheehir[0])

    def dpdrrqfgvm(self, xjxgkzyiuh: Sprite | None, cfafqujddu: bool = True) -> np.ndarray:
        vxzwenyfbf = np.full((self.aqnahsxpq, self.huzumkfia), -1, dtype=int)
        if not cfafqujddu:
            for sprite in self.current_level._sprites:
                if sprite == xjxgkzyiuh or ("gljpmsnsnx" not in sprite.tags and "border" not in sprite.tags):
                    continue
                nqnagkqeqy, crzzncewfw = sprite.pixels.shape
                for dtbpphzyfe in range(nqnagkqeqy):
                    for rbpwwdlqqb in range(crzzncewfw):
                        pmydxcmxwv = sprite.pixels[dtbpphzyfe, rbpwwdlqqb]
                        if pmydxcmxwv != kevchhhmha:
                            hawhmrorex = sprite.x + rbpwwdlqqb
                            hzmlhaicav = sprite.y + dtbpphzyfe
                            if 0 <= hawhmrorex < self.huzumkfia and 0 <= hzmlhaicav < self.aqnahsxpq:
                                vxzwenyfbf[hzmlhaicav, hawhmrorex] = pmydxcmxwv
            return vxzwenyfbf
        qigdoqofte = [s for s in self.current_level._sprites if s != xjxgkzyiuh and ("gljpmsnsnx" in s.tags or "border" in s.tags)]
        for sprite in reversed(qigdoqofte):
            ritcbtdspa: deque[tuple[tuple[int, int], int, int]] = deque()
            yqbcaytwyh = set()
            sqwibixhfs = 12
            nqnagkqeqy, crzzncewfw = sprite.pixels.shape
            sdytknuhzh = "gljpmsnsnx" in sprite.tags
            for dtbpphzyfe in range(nqnagkqeqy):
                for rbpwwdlqqb in range(crzzncewfw):
                    pmydxcmxwv = sprite.pixels[dtbpphzyfe, rbpwwdlqqb]
                    if pmydxcmxwv != kevchhhmha:
                        hawhmrorex = sprite.x + rbpwwdlqqb
                        hzmlhaicav = sprite.y + dtbpphzyfe
                        rbppudsffs = (hawhmrorex, hzmlhaicav)
                        if 0 <= hawhmrorex < self.huzumkfia and 0 <= hzmlhaicav < self.aqnahsxpq:
                            if rbppudsffs not in yqbcaytwyh:
                                yqbcaytwyh.add(rbppudsffs)
                                ritcbtdspa.append((rbppudsffs, pmydxcmxwv, 0))
            while ritcbtdspa:
                rbppudsffs, pmydxcmxwv, depth = ritcbtdspa.popleft()
                if depth > sqwibixhfs:
                    continue
                hawhmrorex, hzmlhaicav = rbppudsffs
                for runybwgioh in self.khupblbrxc:
                    if "zxikvwjsyl" in runybwgioh.tags:
                        vqnsvotjkg = 2 * runybwgioh.x - hawhmrorex
                        dhxrbswmvp = hzmlhaicav
                        xqebhtjxoa = "zxikvwjsyl"
                    elif "ezdsyuixsn" in runybwgioh.tags:
                        vqnsvotjkg = hawhmrorex
                        dhxrbswmvp = 2 * runybwgioh.y - hzmlhaicav
                        xqebhtjxoa = "ezdsyuixsn"
                    else:
                        continue
                    if sdytknuhzh and ("reflect_horizontal_only" in sprite.tags and xqebhtjxoa != "ezdsyuixsn" or ("fmxjsieygg" in sprite.tags and xqebhtjxoa != "zxikvwjsyl")):
                        continue
                    ikqluvhyva = (vqnsvotjkg, dhxrbswmvp)
                    if ikqluvhyva in yqbcaytwyh:
                        continue
                    yqbcaytwyh.add(ikqluvhyva)
                    ritcbtdspa.append((ikqluvhyva, pmydxcmxwv, depth + 1))
                    if 0 <= vqnsvotjkg < self.huzumkfia and 0 <= dhxrbswmvp < self.aqnahsxpq:
                        if vxzwenyfbf[dhxrbswmvp, vqnsvotjkg] == -1:
                            vxzwenyfbf[dhxrbswmvp, vqnsvotjkg] = kddxpzgafq
        for sprite in qigdoqofte:
            nqnagkqeqy, crzzncewfw = sprite.pixels.shape
            for dtbpphzyfe in range(nqnagkqeqy):
                for rbpwwdlqqb in range(crzzncewfw):
                    pmydxcmxwv = sprite.pixels[dtbpphzyfe, rbpwwdlqqb]
                    if pmydxcmxwv != kevchhhmha:
                        hawhmrorex = sprite.x + rbpwwdlqqb
                        hzmlhaicav = sprite.y + dtbpphzyfe
                        if 0 <= hawhmrorex < self.huzumkfia and 0 <= hzmlhaicav < self.aqnahsxpq:
                            vxzwenyfbf[hzmlhaicav, hawhmrorex] = pmydxcmxwv
        return vxzwenyfbf

    def ettaatmcef(
        self,
        yptggrfrgo: int,
        wymrczshbz: int,
        dqapknfnfi: np.ndarray,
        vxzwenyfbf: np.ndarray,
        vovwcdkblf: int,
    ) -> bool:
        nqnagkqeqy, crzzncewfw = dqapknfnfi.shape
        for dtbpphzyfe in range(nqnagkqeqy):
            for rbpwwdlqqb in range(crzzncewfw):
                if dqapknfnfi[dtbpphzyfe, rbpwwdlqqb] != kevchhhmha:
                    hawhmrorex = yptggrfrgo + rbpwwdlqqb
                    hzmlhaicav = wymrczshbz + dtbpphzyfe
                    if 0 <= hawhmrorex < self.huzumkfia and 0 <= hzmlhaicav < self.aqnahsxpq:
                        djewmaduhg = vxzwenyfbf[hzmlhaicav, hawhmrorex]
                        if djewmaduhg != -1 and djewmaduhg != vovwcdkblf:
                            return True
        return False

    def mbpwomuihy(
        self,
        yptggrfrgo: int,
        wymrczshbz: int,
        dqapknfnfi: np.ndarray,
        zrrumfochl: np.ndarray,
        sprite: Sprite,
    ) -> bool:
        from collections import deque

        khupblbrxc = self.khupblbrxc
        nqnagkqeqy, crzzncewfw = dqapknfnfi.shape
        yqbcaytwyh = set()
        ritcbtdspa: deque[tuple[tuple[int, int], int]] = deque()
        sqwibixhfs = 12
        for dtbpphzyfe in range(nqnagkqeqy):
            for rbpwwdlqqb in range(crzzncewfw):
                if dqapknfnfi[dtbpphzyfe, rbpwwdlqqb] != kevchhhmha:
                    hawhmrorex = yptggrfrgo + rbpwwdlqqb
                    hzmlhaicav = wymrczshbz + dtbpphzyfe
                    rbppudsffs = (hawhmrorex, hzmlhaicav)
                    if rbppudsffs not in yqbcaytwyh:
                        yqbcaytwyh.add(rbppudsffs)
                        ritcbtdspa.append((rbppudsffs, 0))
        while ritcbtdspa:
            rbppudsffs, depth = ritcbtdspa.popleft()
            if depth > sqwibixhfs:
                continue
            hawhmrorex, hzmlhaicav = rbppudsffs
            if depth > 0 and 0 <= hawhmrorex < self.huzumkfia and (0 <= hzmlhaicav < self.aqnahsxpq):
                if zrrumfochl[hzmlhaicav, hawhmrorex] != -1:
                    return True
            for runybwgioh in khupblbrxc:
                if "zxikvwjsyl" in runybwgioh.tags:
                    vqnsvotjkg = 2 * runybwgioh.x - hawhmrorex
                    dhxrbswmvp = hzmlhaicav
                    xqebhtjxoa = "zxikvwjsyl"
                elif "ezdsyuixsn" in runybwgioh.tags:
                    vqnsvotjkg = hawhmrorex
                    dhxrbswmvp = 2 * runybwgioh.y - hzmlhaicav
                    xqebhtjxoa = "ezdsyuixsn"
                else:
                    continue
                if "reflect_horizontal_only" in sprite.tags and xqebhtjxoa != "ezdsyuixsn" or ("fmxjsieygg" in sprite.tags and xqebhtjxoa != "zxikvwjsyl"):
                    continue
                ikqluvhyva = (vqnsvotjkg, dhxrbswmvp)
                if ikqluvhyva in yqbcaytwyh:
                    continue
                yqbcaytwyh.add(ikqluvhyva)
                ritcbtdspa.append((ikqluvhyva, depth + 1))
        return False

    def joedjescta(self, x: int, y: int, tag: Optional[str] = None) -> list[Sprite]:
        result = []
        sprites = self.current_level._sprites
        for sprite in sprites:
            if x >= sprite.x and y >= sprite.y and (x < sprite.x + sprite.width) and (y < sprite.y + sprite.height):
                pixels = sprite.pixels
                if pixels[y - sprite.y][x - sprite.x] == -1:
                    continue
                if tag is None or tag in sprite.tags or "edyhkfhkcf" in sprite.tags:
                    result.append(sprite)
        return result

    def irtdqpexfv(self) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        def eexlmfoxay(bigbpyqxgy: list[Sprite]) -> np.ndarray:
            mqrjslqocj = np.full((self.aqnahsxpq, self.huzumkfia), -1, dtype=int)
            for sprite in reversed(bigbpyqxgy):
                ritcbtdspa: deque[tuple[tuple[int, int], int, int]] = deque()
                yqbcaytwyh = set()
                sqwibixhfs = 12
                nqnagkqeqy, crzzncewfw = sprite.pixels.shape
                for dtbpphzyfe in range(nqnagkqeqy):
                    for rbpwwdlqqb in range(crzzncewfw):
                        pmydxcmxwv = sprite.pixels[dtbpphzyfe, rbpwwdlqqb]
                        if pmydxcmxwv != kevchhhmha:
                            hawhmrorex = sprite.x + rbpwwdlqqb
                            hzmlhaicav = sprite.y + dtbpphzyfe
                            rbppudsffs = (hawhmrorex, hzmlhaicav)
                            if 0 <= hawhmrorex < self.huzumkfia and 0 <= hzmlhaicav < self.aqnahsxpq:
                                if rbppudsffs not in yqbcaytwyh:
                                    yqbcaytwyh.add(rbppudsffs)
                                    ritcbtdspa.append((rbppudsffs, pmydxcmxwv, 0))
                while ritcbtdspa:
                    rbppudsffs, pmydxcmxwv, depth = ritcbtdspa.popleft()
                    if depth > sqwibixhfs:
                        continue
                    hawhmrorex, hzmlhaicav = rbppudsffs
                    for runybwgioh in self.khupblbrxc:
                        if "zxikvwjsyl" in runybwgioh.tags:
                            vqnsvotjkg = 2 * runybwgioh.x - hawhmrorex
                            dhxrbswmvp = hzmlhaicav
                            xqebhtjxoa = "zxikvwjsyl"
                        elif "ezdsyuixsn" in runybwgioh.tags:
                            vqnsvotjkg = hawhmrorex
                            dhxrbswmvp = 2 * runybwgioh.y - hzmlhaicav
                            xqebhtjxoa = "ezdsyuixsn"
                        else:
                            continue
                        if "reflect_horizontal_only" in sprite.tags and xqebhtjxoa != "ezdsyuixsn" or ("fmxjsieygg" in sprite.tags and xqebhtjxoa != "zxikvwjsyl"):
                            continue
                        ikqluvhyva = (vqnsvotjkg, dhxrbswmvp)
                        if ikqluvhyva in yqbcaytwyh:
                            continue
                        yqbcaytwyh.add(ikqluvhyva)
                        ritcbtdspa.append((ikqluvhyva, pmydxcmxwv, depth + 1))
                        if 0 <= vqnsvotjkg < self.huzumkfia and 0 <= dhxrbswmvp < self.aqnahsxpq:
                            if mqrjslqocj[dhxrbswmvp, vqnsvotjkg] == -1:
                                mqrjslqocj[dhxrbswmvp, vqnsvotjkg] = kddxpzgafq
            for sprite in bigbpyqxgy:
                nqnagkqeqy, crzzncewfw = sprite.pixels.shape
                for dtbpphzyfe in range(nqnagkqeqy):
                    for rbpwwdlqqb in range(crzzncewfw):
                        pmydxcmxwv = sprite.pixels[dtbpphzyfe, rbpwwdlqqb]
                        if pmydxcmxwv != kevchhhmha:
                            hawhmrorex = sprite.x + rbpwwdlqqb
                            hzmlhaicav = sprite.y + dtbpphzyfe
                            if 0 <= hawhmrorex < self.huzumkfia and 0 <= hzmlhaicav < self.aqnahsxpq:
                                mqrjslqocj[hzmlhaicav, hawhmrorex] = pmydxcmxwv
            return mqrjslqocj

        ohpaolwbkp = [s for s in self.migkdsjrwk if "fmxjsieygg" not in s.tags and "reflect_horizontal_only" not in s.tags]
        eoizzehkwe = [s for s in self.migkdsjrwk if "fmxjsieygg" in s.tags]
        qdffglinvl = [s for s in self.migkdsjrwk if "reflect_horizontal_only" in s.tags]
        oescnslrpz = eexlmfoxay(ohpaolwbkp)
        itbhbmdqlc = eexlmfoxay(eoizzehkwe)
        gjpbeiyllp = eexlmfoxay(qdffglinvl)
        return (oescnslrpz, itbhbmdqlc, gjpbeiyllp)

    def jhajdrieqn(self) -> np.ndarray:
        oescnslrpz, itbhbmdqlc, gjpbeiyllp = self.irtdqpexfv()
        mqrjslqocj = np.full((self.aqnahsxpq, self.huzumkfia), -1, dtype=int)
        for rbqrinektg in [gjpbeiyllp, itbhbmdqlc, oescnslrpz]:
            ejdxlnybyw = rbqrinektg > -1
            mqrjslqocj[ejdxlnybyw] = rbqrinektg[ejdxlnybyw]
        return mqrjslqocj

    def tfvpyidngc(self) -> np.ndarray:
        dfmyjxsddb = np.full((self.aqnahsxpq, self.huzumkfia), None, dtype=object)
        for sprite in reversed(self.migkdsjrwk):
            ritcbtdspa: deque[tuple[tuple[int, int], int]] = deque()
            yqbcaytwyh = set()
            sqwibixhfs = 12
            nqnagkqeqy, crzzncewfw = sprite.pixels.shape
            for dtbpphzyfe in range(nqnagkqeqy):
                for rbpwwdlqqb in range(crzzncewfw):
                    if sprite.pixels[dtbpphzyfe, rbpwwdlqqb] != kevchhhmha:
                        hawhmrorex = sprite.x + rbpwwdlqqb
                        hzmlhaicav = sprite.y + dtbpphzyfe
                        rbppudsffs = (hawhmrorex, hzmlhaicav)
                        if 0 <= hawhmrorex < self.huzumkfia and 0 <= hzmlhaicav < self.aqnahsxpq:
                            if rbppudsffs not in yqbcaytwyh:
                                yqbcaytwyh.add(rbppudsffs)
                                ritcbtdspa.append((rbppudsffs, 0))
            while ritcbtdspa:
                rbppudsffs, depth = ritcbtdspa.popleft()
                if depth > sqwibixhfs:
                    continue
                hawhmrorex, hzmlhaicav = rbppudsffs
                for runybwgioh in self.khupblbrxc:
                    if "zxikvwjsyl" in runybwgioh.tags:
                        vqnsvotjkg = 2 * runybwgioh.x - hawhmrorex
                        dhxrbswmvp = hzmlhaicav
                        xqebhtjxoa = "zxikvwjsyl"
                    elif "ezdsyuixsn" in runybwgioh.tags:
                        vqnsvotjkg = hawhmrorex
                        dhxrbswmvp = 2 * runybwgioh.y - hzmlhaicav
                        xqebhtjxoa = "ezdsyuixsn"
                    else:
                        continue
                    if "reflect_horizontal_only" in sprite.tags and xqebhtjxoa != "ezdsyuixsn" or ("fmxjsieygg" in sprite.tags and xqebhtjxoa != "zxikvwjsyl"):
                        continue
                    ikqluvhyva = (vqnsvotjkg, dhxrbswmvp)
                    if ikqluvhyva in yqbcaytwyh:
                        continue
                    yqbcaytwyh.add(ikqluvhyva)
                    ritcbtdspa.append((ikqluvhyva, depth + 1))
                    if 0 <= vqnsvotjkg < self.huzumkfia and 0 <= dhxrbswmvp < self.aqnahsxpq:
                        if dfmyjxsddb[dhxrbswmvp, vqnsvotjkg] is None:
                            dfmyjxsddb[dhxrbswmvp, vqnsvotjkg] = sprite
        for sprite in self.migkdsjrwk:
            nqnagkqeqy, crzzncewfw = sprite.pixels.shape
            for dtbpphzyfe in range(nqnagkqeqy):
                for rbpwwdlqqb in range(crzzncewfw):
                    if sprite.pixels[dtbpphzyfe, rbpwwdlqqb] != kevchhhmha:
                        hawhmrorex = sprite.x + rbpwwdlqqb
                        hzmlhaicav = sprite.y + dtbpphzyfe
                        if 0 <= hawhmrorex < self.huzumkfia and 0 <= hzmlhaicav < self.aqnahsxpq:
                            dfmyjxsddb[hzmlhaicav, hawhmrorex] = sprite
        return dfmyjxsddb

    def hqiorgefxt(self) -> None:
        oescnslrpz, itbhbmdqlc, gjpbeiyllp = self.irtdqpexfv()
        self.vakuvqumo.pixels = oescnslrpz.copy()
        self.ehoxfqdzf.pixels = itbhbmdqlc.copy()
        self.jgzwiwsnn.pixels = gjpbeiyllp.copy()

    def etzeptsuxx(self) -> bool:
        mqrjslqocj = self.jhajdrieqn()
        qzvyolqwzf = True
        for uvgqszxsnw in self.mqedygxur:
            hawhmrorex = uvgqszxsnw.x
            hzmlhaicav = uvgqszxsnw.y
            if mqrjslqocj[hzmlhaicav, hawhmrorex] < 0:
                qzvyolqwzf = False
        return qzvyolqwzf

    def step(self) -> None:
        if self.action.id != GameAction.ACTION5:
            self.ijwojcjri = 0
            self.tikqecuwc = False
        if self.cnlzdmmso > 0:
            self.cnlzdmmso += 1
            if self.cnlzdmmso % 2 == 1:
                self.uehyvizcj.set_position(self.migkdsjrwk[0]._x, self.migkdsjrwk[0]._y)
            else:
                self.uehyvizcj.set_position(500, self.migkdsjrwk[0]._y)
            if self.cnlzdmmso >= 8:
                self.cnlzdmmso = -1
                self.complete_action()
            return
        if self.mllqetvjb:
            self.next_level()
            self.complete_action()
            return
        if self.action.id == GameAction.ACTION7:
            if self.usukvgwle:
                state = self.usukvgwle.pop()
                self.wmpufuwdcm(state)
            self.complete_action()
            return
        if self.llludejph and self.action.id in [
            GameAction.ACTION1,
            GameAction.ACTION2,
            GameAction.ACTION3,
            GameAction.ACTION4,
        ]:
            if "pwbzvhvyzx" in self.llludejph.tags:
                self.complete_action()
                return
            pshzrdxfu, iyaddaovv = (0, 0)
            if self.action.id == GameAction.ACTION1:
                iyaddaovv = -1
            elif self.action.id == GameAction.ACTION2:
                iyaddaovv = 1
            elif self.action.id == GameAction.ACTION3:
                pshzrdxfu = -1
            elif self.action.id == GameAction.ACTION4:
                pshzrdxfu = 1
            if "edyhkfhkcf" in self.llludejph.tags and "zxikvwjsyl" in self.llludejph.tags:
                iyaddaovv = 0
            if "edyhkfhkcf" in self.llludejph.tags and "ezdsyuixsn" in self.llludejph.tags:
                pshzrdxfu = 0
            yptggrfrgo = self.llludejph.x + pshzrdxfu
            wymrczshbz = self.llludejph.y + iyaddaovv
            crzzncewfw = self.fppvvkcaqa(self.llludejph)
            nqnagkqeqy = self.znirfzpefv(self.llludejph)
            if yptggrfrgo < 0 or yptggrfrgo + crzzncewfw > self.huzumkfia:
                if not ("edyhkfhkcf" in self.llludejph.tags and "ezdsyuixsn" in self.llludejph.tags):
                    self.complete_action()
                    return
            if wymrczshbz < 0 or wymrczshbz + nqnagkqeqy > self.aqnahsxpq:
                if not ("edyhkfhkcf" in self.llludejph.tags and "zxikvwjsyl" in self.llludejph.tags):
                    self.complete_action()
                    return
            if pshzrdxfu != 0 or iyaddaovv != 0:
                self.usukvgwle.append(self.ciwlvhlgil())
            self.llludejph.set_position(yptggrfrgo, wymrczshbz)
            if pshzrdxfu != 0 or iyaddaovv != 0:
                for s, tgwjjzpyxc in list(self.ueryufapb.items()):
                    runybwgioh = self.hnepuikbu if "xnpsicjqxc" in s.tags else self.hitrtbsoq
                    if runybwgioh:
                        vvsapeulig = self.zngkctyvrs(s, runybwgioh)
                        if vvsapeulig != tgwjjzpyxc:
                            self.vlnwxwcdzf(s)
                            self.ueryufapb[s] = self.zngkctyvrs(s, runybwgioh)
            self.hqiorgefxt()
            if self.etzeptsuxx():
                self.mllqetvjb = True
                return
            if pshzrdxfu != 0 or iyaddaovv != 0:
                if not self.zdrbnrjbr.tihzupejat():
                    self.lose()
                if self.level_index == 1 and self.cnlzdmmso == 0 and (self.zdrbnrjbr.current_steps < 50) and (not self.mewxgwwty):
                    self.cnlzdmmso = 1
                    return
            self.complete_action()
            return
        if self.action.id == GameAction.ACTION5:
            self.ijwojcjri += 1
            self.tikqecuwc = True
            uhdkxxlxxb = -1 if self.llludejph not in self.xefwpvwoh else self.xefwpvwoh.index(self.llludejph)
            dnolnhhsxs = (uhdkxxlxxb + 1) % len(self.xefwpvwoh)
            pzxckdzfza = self.xefwpvwoh[dnolnhhsxs]
            if self.llludejph != pzxckdzfza:
                self.llludejph = pzxckdzfza
                self.mewxgwwty = True
            if not self.zdrbnrjbr.tihzupejat():
                self.lose()
            self.complete_action()
            return
        if self.action.id == GameAction.ACTION6:
            x = self.action.data.get("x", 0)
            y = self.action.data.get("y", 0)
            qqxqwaptve = self.camera.display_to_grid(x, y)
            if qqxqwaptve:
                hawhmrorex, hzmlhaicav = qqxqwaptve
                sprites: list[Sprite] = self.joedjescta(hawhmrorex, hzmlhaicav)
                tqxwfhzaui: Sprite | None = None
                ntyhsdyfmi: list[Sprite] = [sprite for sprite in sprites if "gljpmsnsnx" in sprite.tags and "pwbzvhvyzx" not in sprite.tags]
                if ntyhsdyfmi:

                    def hpjseosbev(s: Sprite) -> int:
                        if "reflect_horizontal_only" in s.tags:
                            return 1
                        elif "fmxjsieygg" in s.tags:
                            return 2
                        else:
                            return 3

                    ntyhsdyfmi.sort(key=hpjseosbev, reverse=True)
                    tqxwfhzaui = ntyhsdyfmi[0]
                else:
                    zdtrxuxrrp: list[Sprite] = [sprite for sprite in sprites if "edyhkfhkcf" in sprite.tags and "pwbzvhvyzx" not in sprite.tags]
                    if zdtrxuxrrp:
                        if len(zdtrxuxrrp) == 1:
                            tqxwfhzaui = zdtrxuxrrp[0]
                        else:
                            wpolxlughh = next((s for s in zdtrxuxrrp if "zxikvwjsyl" in s.tags), None)
                            mluzjwmlbm = next((s for s in zdtrxuxrrp if "ezdsyuixsn" in s.tags), None)
                            if self.llludejph is None or self.llludejph not in zdtrxuxrrp:
                                tqxwfhzaui = wpolxlughh if wpolxlughh else mluzjwmlbm
                            elif self.llludejph == wpolxlughh:
                                tqxwfhzaui = mluzjwmlbm
                            elif self.llludejph == mluzjwmlbm:
                                tqxwfhzaui = wpolxlughh
                            else:
                                tqxwfhzaui = wpolxlughh if wpolxlughh else mluzjwmlbm
                if tqxwfhzaui:
                    if self.llludejph != tqxwfhzaui:
                        self.llludejph = tqxwfhzaui
                        self.mewxgwwty = True
                else:
                    pass
            if not self.llludejph:
                aydyobwonq = [trspysetcl for trspysetcl in self.khupblbrxc if "pwbzvhvyzx" not in trspysetcl.tags]
                gwzaphwbxm = [rhxpwsowco for rhxpwsowco in self.migkdsjrwk if "pwbzvhvyzx" not in rhxpwsowco.tags]
                self.llludejph = aydyobwonq[0] if aydyobwonq else gwzaphwbxm[0] if gwzaphwbxm else None
            self.complete_action()
            return
        self.complete_action()
