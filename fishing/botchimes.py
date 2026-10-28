"""Five quiet, deterministic shell voices, synthesized once into a bounded cache."""
from functools import lru_cache
import numpy as np

from .data import BOT_SHELLS

CHIMES = tuple(shell.chime for shell in BOT_SHELLS.values())
SAMPLE_RATE = 22050


@lru_cache(maxsize=5)
def synthesize(kind):
    if kind not in CHIMES:
        raise ValueError('Unknown Bot chime: ' + str(kind))
    duration = {'bot_tin': .46, 'bot_frog': .30, 'bot_duck': .32,
                'bot_sub': .42, 'bot_astral': .88}[kind]
    t = np.arange(int(SAMPLE_RATE * duration), dtype=np.float32) / SAMPLE_RATE
    if kind == 'bot_tin':
        phase = 2*np.pi*880*t
        triangle = sum((-1)**i * np.sin((2*i+1)*phase)/(2*i+1)**2 for i in range(4))
        wave = triangle*np.exp(-t*10) + .30*np.sin(2*np.pi*1870*t)*np.exp(-t*15)
    elif kind == 'bot_frog':
        wave = np.zeros_like(t)
        for start, pitch in ((0., 390.), (.085, 290.)):
            u = np.maximum(0., t-start)
            hit = (t>=start)*np.exp(-u*38)
            wave += hit*(np.sin(2*np.pi*pitch*u) + .42*np.sin(2*np.pi*1430*u))
    elif kind == 'bot_duck':
        # A soft rubber squeak: a descending FM glide with a short breath gap.
        phase = 2*np.pi*(880*t-850*t*t)
        wave = np.sin(phase+1.5*np.sin(2*np.pi*70*t))
        wave *= np.sin(np.pi*np.minimum(1.,t/duration))**.6
        wave *= .72+.28*np.cos(2*np.pi*12*t)
    elif kind == 'bot_sub':
        wave = np.zeros_like(t)
        for start,pitch,gain in ((0.,220.,1.),(.09,430.,.7),(.18,660.,.55),(.26,920.,.35)):
            u = np.maximum(0.,t-start)
            wave += gain*(t>=start)*np.exp(-u*44)*np.sin(2*np.pi*(pitch*u+600*u*u))
    else:
        wave = (np.sin(2*np.pi*1046.5*t)*np.exp(-t*4.2)
                +.45*np.sin(2*np.pi*2489*t)*np.exp(-t*6.0)
                +.22*np.sin(2*np.pi*4170*t)*np.exp(-t*9.5))
        u = np.maximum(0.,t-.11)
        wave += .22*(t>=.11)*np.sin(2*np.pi*1568*u)*np.exp(-u*7)
    # Short attacks and tapered ends avoid clicks; every voice shares a soft peak.
    wave *= np.minimum(1.,t/.003) * np.minimum(1.,(duration-t)/.025)
    wave *= .27 / max(.001,float(np.max(np.abs(wave))))
    pcm = np.rint(wave * 32767).astype(np.int16)
    pcm.setflags(write=False)
    return pcm
