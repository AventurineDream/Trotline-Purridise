"""Sonar Grid overlay: depth bands and habitat for the water you are working.

The overlay needs the depth finder and the purchased Sonar Grid. It covers the
zones that hold a line in the water, plus the zone under the boat. Read-only:
it never changes bites, rates or saves.
"""

from __future__ import annotations

from dataclasses import dataclass

from .world import World

BAND_M = 2.0       # depth contour interval, metres
SPACING_M = 24.0   # sample grid inside each habitat circle, metres


@dataclass(frozen=True)
class SonarCell:
    x: float
    z: float
    zone: str
    band: int  # whole BAND_M steps below the surface; 0 is the shallowest


def enabled(state) -> bool:
    return bool(state.finder) and state.owns_tool("sonar_grid")


def scouted_zones(state, world: World) -> set[str]:
    zones = {line.zone for line in state.lines}
    zones.add(world.zone_at(state.x, state.z))
    return zones


def overlay(state, world: World) -> list[SonarCell]:
    if not enabled(state):
        return []
    zones = scouted_zones(state, world)
    cells: list[SonarCell] = []
    for name, cx, cz, radius in world.zones:
        if name not in zones:
            continue
        reach = int(radius // SPACING_M) + 1
        for i in range(-reach, reach + 1):
            for j in range(-reach, reach + 1):
                dx, dz = i * SPACING_M, j * SPACING_M
                if dx * dx + dz * dz > radius * radius:
                    continue
                x, z = cx + dx, cz + dz
                # A point belongs to the zone that world.zone_at reports for it,
                # so overlapping habitat circles never double-plot.
                if world.zone_at(x, z) != name or not world.navigable(x, z):
                    continue
                depth = float(world.depth(x, z))
                if depth <= 0.0:
                    continue
                cells.append(SonarCell(x, z, name, int(depth // BAND_M)))
    return cells
