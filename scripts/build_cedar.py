"""Bake a small offline game asset from TWDB's public 2017 Cedar Creek survey.

Build-only dependencies: pyshp, shapely, scipy, pyproj, numpy. The game itself
only loads the resulting NumPy grids and JSON metadata, never these libraries.
Usage: python scripts/build_cedar.py .tmp/cedar-survey
Source ZIP: https://www.twdb.texas.gov/surfacewater/surveys/completed/files/CedarCreek/2017-10/Shapefiles.zip
"""

import hashlib
import json
import sys
from pathlib import Path

import numpy as np
import shapefile
import shapely
from shapely.geometry import Point, Polygon, shape
from scipy.ndimage import distance_transform_edt, gaussian_filter
from scipy.spatial import cKDTree
from pyproj import CRS, Transformer

root = Path(__file__).resolve().parents[1]
source = Path(sys.argv[1])
out = root / "fishing/assets"
out.mkdir(exist_ok=True)
scale = 0.03048006096  # US survey feet to metres, then compress distances 10x
reader = shapefile.Reader(str(source / "CC17_Lake_1"))
water = shapely.make_valid(shape(reader.shape(0).__geo_interface__))
if water.geom_type == "MultiPolygon":
    water = max(water.geoms,key=lambda p:p.area)
water = water.simplify(40.0,preserve_topology=True)
centre = np.array(water.centroid.coords[0])
outer = (np.array(water.exterior.coords)-centre)*scale
holes = [(np.array(ring.coords)-centre)*scale for ring in water.interiors if Polygon(ring).area*scale**2>3]
water = shapely.make_valid(Polygon(outer,holes))
if water.geom_type == "MultiPolygon":
    water = max(water.geoms,key=lambda p:p.area)
print("Shoreline simplified:",len(water.exterior.coords),"vertices,",len(water.interiors),"islands",flush=True)
bounds = np.array(water.bounds)+np.array([-180,-180,180,180])
x0,z0,x1,z1 = bounds
nx,nz = 1152,1152
xs,zs = np.linspace(x0,x1,nx),np.linspace(z0,z1,nz)
xx,zz = np.meshgrid(xs,zs)
mask = shapely.contains_xy(water,xx,zz)
spacing = ((z1-z0)/(nz-1),(x1-x0)/(nx-1))
shore = (distance_transform_edt(~mask,sampling=spacing)-distance_transform_edt(mask,sampling=spacing)).astype(np.float32)

# Fixed, evenly spaced coast samples also place the shoreline trees/islands.
rings = [water.exterior,*water.interiors]
shore_samples = []
for ring in rings:
    count = max(4,round(1800*ring.length/water.boundary.length))
    for distance in np.linspace(0,ring.length,count,endpoint=False):
        p = np.array(ring.interpolate(distance).coords[0])
        a = np.array(ring.interpolate((distance-0.5)%ring.length).coords[0])
        b = np.array(ring.interpolate((distance+0.5)%ring.length).coords[0])
        tangent = b-a
        normal = np.array([tangent[1],-tangent[0]])
        normal /= np.linalg.norm(normal)+1e-9
        if water.contains(Point(p+normal)):
            normal *= -1
        shore_samples.append([*p,*normal])
shore_samples = np.asarray(shore_samples,np.float32)

# Five-foot survey contours, sampled at a bounded density. Interpolation is
# game terrain, with a smooth shelf and a capped 53-foot maximum depth.
contours = shapefile.Reader(str(source / "CedarCreek17_1ftcont"))
points, elevations = [],[]
for item in contours.iterShapeRecords():
    elevation = float(item.record[0])
    if abs(elevation/5-round(elevation/5))>0.001 or not 265<=elevation<=320:
        continue
    coords = np.asarray(item.shape.points,np.float64)[::24]
    if not len(coords):
        continue
    points.append((coords-centre)*scale)
    elevations.append(np.full(len(coords),elevation,np.float32))
points.append(shore_samples[:,:2])
elevations.append(np.full(len(shore_samples),322,np.float32))
points,elevations = np.concatenate(points),np.concatenate(elevations)
tree = cKDTree(points)
depth = np.empty((nz,nx),np.float32)
for start in range(0,nz,48):
    query = np.stack([xx[start:start+48],zz[start:start+48]],-1)
    distances,indices = tree.query(query,k=6)
    weights = 1/np.maximum(distances,0.1)**2
    bottom = (elevations[indices]*weights).sum(-1)/weights.sum(-1)
    depth[start:start+48] = np.clip((322-bottom)*0.3048006096,0.4,16.2)
depth = gaussian_filter(depth,1.1).astype(np.float32)
depth[~mask] = 0

# County Public Ramp on FM 198/Caney Creek, from TPWD's survey access table.
projection = CRS.from_wkt((source/"CC17_Lake_1.prj").read_text())
project = Transformer.from_crs("EPSG:4269",projection,always_xy=True)
def position(lon,lat):
    return (np.array(project.transform(lon,lat))-centre)*scale
ramp = position(-96.02556,32.20874)
ring = water.exterior
distance = ring.project(Point(ramp))
origin = np.array(ring.interpolate(distance).coords[0])
a = np.array(ring.interpolate((distance-0.5)%ring.length).coords[0])
b = np.array(ring.interpolate((distance+0.5)%ring.length).coords[0])
normal = np.array([b[1]-a[1],a[0]-b[0]])
normal /= np.linalg.norm(normal)
if water.contains(Point(origin+normal)):
    normal *= -1
metadata = {
    "source":"Texas Water Development Board, April-October 2017 Cedar Creek volumetric survey",
    "source_url":"https://www.twdb.texas.gov/surfacewater/surveys/completed/files/CedarCreek/2017-10/Shapefiles.zip",
    "horizontal_scale":0.1,"bounds":bounds.tolist(),"shape":[nz,nx],
    "origin_survey_feet":centre.tolist(),"survey_feet_to_game_metres":scale,
    "slip_origin":origin.tolist(),"slip_inland":normal.tolist(),
    "outer":np.round(np.asarray(water.exterior.coords),3).tolist(),
    "zones":[
        ["inlet",*position(-96.175,32.384),150],
        ["flats",*position(-96.148,32.344),165],
        ["lilies",*position(-96.057,32.205),170],
        ["cypress",*position(-96.072,32.258),145],
        ["rocks",*position(-96.111,32.176),145],
        ["deep",*position(-96.099,32.229),180],
        ["inlet",*position(-96.038,32.218),130],
    ],
}
# Center fishing grounds in genuinely wet, navigable habitat, rather than
# allowing approximate landmark coordinates to place an entire zone on land.
habitat_depths = {"flats":(0.8,3.2),"lilies":(0.9,4.0),"cypress":(1.0,5.0),
                  "rocks":(2.0,8.0),"deep":(10.0,16.2),"inlet":(1.4,8.0)}
for zone in metadata["zones"]:
    low,high = habitat_depths[zone[0]]
    eligible = mask & (shore<-9) & (depth>=low) & (depth<=high)
    distance = (xx-zone[1])**2+(zz-zone[2])**2
    index = np.argmin(np.where(eligible,distance,np.inf))
    zone[1],zone[2] = float(xx.flat[index]),float(zz.flat[index])
np.savez_compressed(out/"cedar.npz",shore=shore,depth=depth,coast=shore_samples)
metadata["asset_sha256"] = hashlib.sha256((out/"cedar.npz").read_bytes()).hexdigest()
zip_path = source.with_suffix(".zip")
if zip_path.exists():
    digest = hashlib.sha256()
    with zip_path.open("rb") as stream:
        for block in iter(lambda:stream.read(1024*1024),b""):
            digest.update(block)
    metadata["survey_zip_sha256"] = digest.hexdigest()
metadata["build_libraries"] = {"pyshp":"3.1.6","shapely":"2.2.0","scipy":"1.18.1","pyproj":"3.8.0"}
(out/"cedar.json").write_text(json.dumps(metadata,separators=(",",":"))+"\n")
print("Built Cedar Creek:",bounds,"ramp",origin,"inland",normal,flush=True)
print("Water area",int(mask.sum()),"pixels; depth",float(depth.max()),"m; asset",(out/"cedar.npz").stat().st_size,"bytes")
