"""Real-map catchability witnesses, using reachable water and live bite rates."""

from collections import deque
import math

import numpy as np

from .boat import BOATS
from .data import (BAITS, CONTENT_V2_RAW, LAKE_SPECIES_IDS, SPECIES_BY_ID,
                   ZONE_ORDER, bait_mult)
from .sim import species_rates
from .world import World


def _reachable_samples(world, step=4.0):
    """Conservative full-hull routes from the landing on a four-metre grid.

    The 5.8 m clearance covers the largest current hull and half a grid edge,
    matching the existing anchor-connectivity check. No gameplay RNG is used.
    """
    clearance = 5.8
    x0, z0, x1, z1 = world.bounds
    xs, zs = np.arange(x0, x1, step), np.arange(z0, z1, step)
    x, z = np.meshgrid(xs, zs)
    draft = max(boat.draft for boat in BOATS.values())
    safe = world.navigable_mask(x, z, draft)
    for radius in (clearance/2, clearance):
        for angle in np.arange(16) * math.tau/16:
            safe &= world.navigable_mask(x+radius*math.cos(angle), z+radius*math.sin(angle), draft)
    a, s = world.slip.local(x, z)
    for ca, cs, ea, es in world.dock_barriers:
        safe &= (np.abs(a-ca) > ea+clearance) | (np.abs(s-cs) > es+clearance)
    for px, pz, radius in world.solid_props:
        i, j = int((px-x0)/step), int((pz-z0)/step)
        n = math.ceil((radius+clearance)/step)+1
        ia, ib = max(0, i-n), min(len(xs), i+n+1)
        ja, jb = max(0, j-n), min(len(zs), j+n+1)
        if ia < ib and ja < jb:
            safe[ja:jb, ia:ib] &= ((x[ja:jb, ia:ib]-px)**2 + (z[ja:jb, ia:ib]-pz)**2
                                   > (radius+clearance)**2)
    sx, sz = world.slip.world(-24, 0)
    nearest = np.where(safe, (x-sx)**2+(z-sz)**2, np.inf)
    start = np.unravel_index(int(nearest.argmin()), safe.shape)
    if nearest[start] > 32**2:
        raise AssertionError(world.id + ": landing has no reachable water")
    reachable = np.zeros_like(safe)
    reachable[start] = True
    queue = deque([start])
    while queue:
        j, i = queue.popleft()
        for jj, ii in ((j-1, i), (j+1, i), (j, i-1), (j, i+1)):
            if (0 <= jj < len(zs) and 0 <= ii < len(xs)
                    and safe[jj, ii] and not reachable[jj, ii]):
                reachable[jj, ii] = True
                queue.append((jj, ii))
    return x[reachable], z[reachable]


def lake_witnesses(world):
    """One concrete reachable witness per catchable lake species."""
    x, z = _reachable_samples(world)
    depths, zones = world.depth(x, z), world.zone_ids(x, z)
    tier_rates = {row['tier']: row['rate'] for row in CONTENT_V2_RAW['species.json']['tier_defaults']}
    authored = {row['id']: row for row in CONTENT_V2_RAW['species.json']['species']}
    # Specialty stock is reachable at its own landing and can travel aboard.
    baits = [bait.id for bait in BAITS if bait.sold_at]
    result, failures = [], []
    for sid in LAKE_SPECIES_IDS[world.id]:
        fish, row = SPECIES_BY_ID[sid], authored[sid]
        default_rate = row['rate'] if 'rate' in row else tier_rates[row['tier']]
        bait = max(baits, key=lambda bid: bait_mult(bid, sid))
        hour = {'dawn': 6, 'day': 12, 'dusk': 18, 'night': 23, 'any': 12}[fish.pref_time]
        weather = next(iter(fish.weather_affinities), 'clear')
        best = None
        for zone in fish.zones or ZONE_ORDER:
            if zone in ('landing', 'shore'):
                continue
            indices = np.flatnonzero((zones == ZONE_ORDER.index(zone)) & (depths >= .9))
            if not len(indices):
                continue
            dep = depths[indices]
            lo, hi = fish.depth
            quality = np.where(dep < lo, np.maximum(.2, 1-(lo-dep)/3.5),
                               np.where(dep > hi, np.maximum(.2, 1-(dep-hi)/5), 1))
            index = indices[int(quality.argmax())]
            depth = float(depths[index])
            rate = species_rates(zone, bait, hour, weather, depth, world.id)[sid]
            if best is None or rate > best['rate']:
                best = dict(species=sid, lake=world.id, zone=zone, x=float(x[index]), z=float(z[index]),
                            depth_m=depth, bait=bait, hour=hour, weather=weather, rate=rate,
                            default_rate=default_rate, ratio=rate/default_rate,
                            bait_sold_at=list(next(b.sold_at for b in BAITS if b.id == bait)))
        if best is None or best['rate'] <= 0:
            failures.append((sid, best))
        else:
            if world.zone_at(best['x'], best['z']) != best['zone']:
                raise AssertionError(sid + ': scalar/vector habitat disagreement')
            if not world.hull_clear(best['x'], best['z'], 0, 'jon'):
                raise AssertionError(sid + ': witness blocks a real hull')
            result.append(best)
    if failures:
        raise AssertionError(f'{world.id}: unreachable fish: {failures}')
    return result


def validate_catchability(lakes=('briar', 'cedar', 'flathead', 'crater', 'nebula')):
    result = []
    for lake in lakes:
        world = World(lake)
        result.extend(lake_witnesses(world))
        del world
    best = {}
    for row in result:
        best[row['species']] = max(best.get(row['species'], 0), row['ratio'])
    failures = {sid: ratio for sid, ratio in best.items() if ratio < .5}
    if failures:
        raise AssertionError(f'No >=0.5x reachable witness: {failures}')
    return result
