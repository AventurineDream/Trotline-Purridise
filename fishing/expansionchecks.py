"""Two-lake gameplay, boat ownership, propulsion, and save regressions."""

import hashlib
import json
import math
import tempfile
from pathlib import Path

import numpy as np

from .boat import BOATS, BATTERY_CHARGE_KWH, FUEL_PRICE, ROWBOAT_BATTERY_KWH, sailing_speed
from .data import BAITS, SPECIES, SPECIES_BY_ID, WELLS, ZONE_ORDER
from .game import Keys, Session
from .render import Renderer
from .sim import Catch, State, saved_lake, species_rates
from .ui import shop_rows
from .weather import wind_at
from .platform import SCAN
from .world import World


def expansion_checks(briar,software=False):
    if SCAN.get("q")!=20 or SCAN.get("r")!=21:
        raise AssertionError("sail or tow controls missing from native input")
    if len(SPECIES)!=144 or len(SPECIES_BY_ID)!=144:
        raise AssertionError("fish catalog must contain exactly 144 unique entries")
    from .specieschecks import validate_catchability
    witnesses = validate_catchability()
    if len({row['species'] for row in witnesses}) != 144:
        raise AssertionError("real-map catchability omitted a species")
    minimum = min(max(row['ratio'] for row in witnesses if row['species'] == sid) for sid in SPECIES_BY_ID)
    print(f"catchability ok  144 species, {len(witnesses)} lake witnesses, "
          f"minimum best rate {minimum:.3f}x authored default")
    cedar = World("cedar")
    assets = Path(__file__).with_name("assets")
    metadata = json.loads((assets/"cedar.json").read_text())
    if hashlib.sha256((assets/"cedar.npz").read_bytes()).hexdigest()!=metadata["asset_sha256"]:
        raise AssertionError("Cedar Creek survey asset checksum changed")
    if len(cedar.coast)<100 or not np.isfinite(cedar.depth_grid).all() or not 15<cedar.depth_grid.max()<16.3:
        raise AssertionError("invalid Cedar shoreline or bathymetry")
    for zone,x,z,radius in cedar.zones:
        if not cedar.navigable(x,z):
            raise AssertionError(f"Cedar fishing ground on land: {zone}")

    with tempfile.TemporaryDirectory(prefix="briar-expansion-") as temp:
        path = Path(temp)/"save.json"
        state = State.new(briar,seed=61)
        old = state.to_json()
        for field in ("lake_id","boat_id","owned_boats","fuel_tanks",
                      "rowboat_charge_kwh_this_visit"):
            del old[field]
        old["money"] = 123.45
        old["game_minutes"] = 2222
        old["journal"] = {key:value for key,value in old["journal"].items() if key in [fish.id for fish in SPECIES[:12]]}
        path.write_text(json.dumps(old))
        migrated = State.load(path,briar)
        if migrated.money!=123.45 or migrated.game_minutes!=2222 or migrated.fuel!=12 or len(migrated.journal)!=144:
            raise AssertionError("legacy save lost progress, starter fuel, or new journal entries")
        if migrated.boat_id!="jon" or migrated.owned_boats!=["jon"]:
            raise AssertionError("legacy save granted or lost boat ownership")

        state.money = 0
        if state.buy_boat("sail",briar) is None or "sail" in state.owned_boats:
            raise AssertionError("new boat was free")
        state.money = 3000
        if state.buy_boat("sail",briar) is not None or state.money!=2350 or state.fuel!=6:
            raise AssertionError("daysailer purchase did not charge correctly")
        state.fuel = 2.25
        state.buy_boat("jon",briar)
        state.buy_boat("sail",briar)
        if state.fuel!=2.25 or state.money!=2350:
            raise AssertionError("equipping an owned boat refilled fuel or charged again")
        if state.buy_boat("pontoon",briar) is not None or state.well_cap()!=WELLS[0]+40:
            raise AssertionError("pontoon purchase or livewell bonus failed")
        state.fuel=30
        cash=state.money
        if state.refuel() is not None or state.fuel!=35 or not math.isclose(cash-state.money,5*FUEL_PRICE):
            raise AssertionError("fuel refill or billing failed")
        state.refuel()
        if state.fuel!=36:
            raise AssertionError("refill overfilled the tank")
        if state.buy_boat("rowboat",briar) is not None or state.fuel!=0:
            raise AssertionError("rowboat purchase did not preserve its no-fuel setup")
        if state.buy_rowboat_trolling_motor() is not None or not state.rowboat_trolling_motor:
            raise AssertionError("trolling motor purchase was not charged or installed")
        if state.rowboat_battery_kwh!=ROWBOAT_BATTERY_KWH:
            raise AssertionError("new trolling motor did not include a full battery")
        state.x=state.z=state.yaw=0
        state.anchored=False
        state.throttle=state.throttle_setting=1
        battery=state.rowboat_battery_kwh
        movement=[]
        state._quest_event_handler=lambda _state,event: movement.append(event)
        for _ in range(20):
            state.drive(0.1,0,0,briar,player_controlled=True)
        if not state.rowboat_battery_kwh<battery or state.speed<=0:
            raise AssertionError("electric trolling motor did not use battery or move the rowboat")
        state.rowboat_battery_kwh=0
        state.speed=0
        state.throttle=state.throttle_setting=1
        state.drive(0.1,0,0,briar,player_controlled=True)
        if state.max_speed()<=0 or state.max_speed()>=4.0:
            raise AssertionError("empty electric battery did not fall back to rowing speed")
        if not any(event.get("type")=="boat.move" and event.get("propulsion")=="oar"
                   for event in movement):
            raise AssertionError("rowed movement was not recorded as oar propulsion")
        state._park(briar)
        cash=state.money
        if state.charge_rowboat_battery() is not None or state.rowboat_battery_kwh!=5.0:
            raise AssertionError("battery charge at the landing failed")
        if not math.isclose(cash-state.money,1.75):
            raise AssertionError("battery charge was not billed at the posted kWh rate")
        if state.battery_charge_available_this_visit()!=0.0:
            raise AssertionError("battery visit allowance did not decrease by the charge amount")
        if state.charge_rowboat_battery() is None or state.rowboat_battery_kwh!=5.0:
            raise AssertionError("multiple charges exceeded the per-visit battery limit")
        battery_row = next((row for row in shop_rows(state,4) if row.kind=="battery"),None)
        if battery_row is None or battery_row.enabled:
            raise AssertionError("shop still offered another battery charge this visit")
        state.anchored=False
        for _ in range(200):
            state.drive(0.1,1.0,0.0,briar)
            if state.slip_status(briar)!="docked":
                break
        if state.slip_status(briar)=="docked" or state.rowboat_charge_kwh_this_visit!=0.0:
            raise AssertionError("leaving the landing did not reset battery charge allowance")
        state._park(briar)
        before_recharge=state.rowboat_battery_kwh
        if (state.charge_rowboat_battery() is not None
                or state.rowboat_battery_kwh<=before_recharge
                or state.rowboat_charge_kwh_this_visit!=BATTERY_CHARGE_KWH):
            raise AssertionError("battery could not be charged after a new landing visit")
        if state.buy_boat("pontoon",briar) is not None:
            raise AssertionError("could not switch back to an owned boat")
        state.well=[Catch("alligator_gar",65,1,0,"inlet","shad",23)]
        if state.buy_boat("sail",briar) is None or state.boat_id!="pontoon":
            raise AssertionError("boat switch lost an oversized catch")
        state.well.clear()
        state.save(path)
        loaded=State.load(path,briar)
        if (loaded.boat_id!="pontoon" or loaded.fuel!=36 or len(loaded.owned_boats)!=4
                or not loaded.rowboat_trolling_motor
                or not math.isclose(loaded.rowboat_battery_kwh,state.rowboat_battery_kwh,abs_tol=1e-6)
                or loaded.rowboat_charge_kwh_this_visit!=BATTERY_CHARGE_KWH):
            raise AssertionError("boats, fuel, trolling motor and battery did not roundtrip")

        session=Session(briar,path,state,True)
        state.x=state.z=state.yaw=0
        state.anchored=False
        if state.try_set(briar,0,"worm") is not None:
            raise AssertionError("travel fixture could not set a line")
        state._park(briar)
        if session.change_lake("cedar") is None or session.world is not briar:
            raise AssertionError("lake travel orphaned deployed lines")
        state.pull_line(0)
        cash,gear,journal,fuel=state.money,len(state.held),dict(state.journal),dict(state.fuel_tanks)
        # Exercise the actual Lakes tab and WASD/Enter dispatch.
        session.ui.mode="shop"
        session.ui.shop_tab=5
        session.tick(Keys(pressed={"s"}),0.01)
        session.tick(Keys(pressed={"return"}),0.01)
        if session.world.id!="cedar" or state.lake_id!="cedar" or state.money!=cash:
            raise AssertionError("Lakes menu did not travel without losing cash")
        if len(state.held)!=gear or state.journal!=journal or state.fuel_tanks!=fuel:
            raise AssertionError("lake travel lost gear, journal, or tank contents")
        state.save(path)
        if saved_lake(path)!="cedar" or State.load(path,session.world).lake_id!="cedar":
            raise AssertionError("Cedar save did not reload on the correct lake")
        if session.change_lake("briar") is not None:
            raise AssertionError("return travel failed")
        if [r.kind for r in shop_rows(state,4)]!=["boat"]*len(BOATS)+["trolling_motor","fuel"]:
            raise AssertionError("Boats tab includes unrelated shop rows")

    # Motor use costs fuel; sailing under the same simulated clock does not.
    state=State.new(briar,seed=62)
    state.x=state.z=state.yaw=0
    state.anchored=False
    state.throttle=state.throttle_setting=1
    initial=state.fuel
    for _ in range(120):
        state.drive(0.05,0,0,briar)
    if not state.fuel<initial or state.speed<=0:
        raise AssertionError("powered travel did not consume fuel")
    state.speed=0
    state.fuel=0
    state.drive(0.1,0,0,briar)
    if state.speed or state.throttle:
        raise AssertionError("an empty tank still powered the motor")
    state.money=0
    state.throttle_setting=0
    if state.tow_to_landing(briar) is not None or state.fuel<0.74 or state.slip_status(briar)!="docked":
        raise AssertionError("empty-tank, empty-wallet rescue failed")
    state.boat_id="sail"
    state.x=state.z=0
    state.speed=state.throttle=state.throttle_setting=0
    state.fuel=0
    wind,speed=wind_at(state.game_minutes)
    state.yaw=wind+math.pi/2
    state.toggle_sail()
    for _ in range(120):
        state.drive(0.05,0,0,briar)
    if state.speed<=1 or state.fuel or state.traveled<10:
        raise AssertionError("sailboat did not travel with an empty tank")
    if state.fast_ok() or sailing_speed(wind+math.pi,wind,speed)!=0:
        raise AssertionError("sailing ignored the upwind zone or time restriction")
    state.sail_raised=False
    state.fuel=1
    state.throttle=state.throttle_setting=1
    state.drive(0.1,0,0,briar)
    if not state.fuel<1:
        raise AssertionError("sailboat auxiliary did not consume fuel")

    # The wider pontoon really needs more clearance, and every hull stops at
    # narrow solid obstacles despite a long tick and a high starting speed.
    original=briar.solid_props
    try:
        briar.solid_props=np.array([[-1.1,1.2,.1],[1.1,1.2,.1]])
        if not briar.hull_clear(0,0,0,"jon") or briar.hull_clear(0,0,0,"pontoon"):
            raise AssertionError("pontoon reused the narrow jon-boat collision box")
        briar.solid_props=np.array([[0,6,.2]])
        for boat_id in BOATS:
            state=State.new(briar,seed=63)
            state.boat_id=boat_id
            state.fuel=state.boat.tank
            state.x=state.z=state.yaw=0
            state.anchored=False
            state.speed=14
            state.throttle=state.throttle_setting=1
            state.drive(0.5,0,0,briar)
            if not briar.hull_clear(state.x,state.z,state.yaw,boat_id) or state.z>6-state.boat.bow-.22:
                raise AssertionError(f"{boat_id} crossed a thin solid obstacle")
    finally:
        briar.solid_props=original
    for boat_id in BOATS:
        state=State.new(cedar,seed=64)
        state.boat_id=boat_id
        state.fuel=state.boat.tank
        for _ in range(100):
            state.drive(0.05,1,0,cedar)
            if not cedar.hull_clear(state.x,state.z,state.yaw,boat_id):
                raise AssertionError(f"{boat_id} crossed the Cedar landing barriers")
    print("expansion gameplay ok  144 fish, survey asset, wet habitats, paid boats, retained tanks, "
          "fuel, free sailing, auxiliary, tow, wider collisions, lake travel and old/new saves")

    renderer=Renderer(cedar,960,540,software=software)
    try:
        for boat_id in BOATS:
            state=State.new(cedar,seed=65)
            state.boat_id=boat_id
            state.fuel=state.boat.tank
            frame=renderer.render(state)
            if not np.isfinite(frame).all() or frame.std()<8:
                raise AssertionError(f"invalid Cedar {boat_id} frame")
            if hasattr(renderer,"read_depth"):
                depth=renderer.read_depth()
                count=len(renderer._objects)
                state.anim+=19
                renderer.render(state)
                if renderer.read_depth()!=depth or len(renderer._objects)!=count:
                    raise AssertionError(f"Cedar {boat_id} geometry moved or graphics objects grew")
    finally:
        renderer.close()
    print("expansion graphics ok  Cedar shoreline, all four hulls, fixed anchored depth and bounded objects")
