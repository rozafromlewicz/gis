import os
import glob
import pandas as pd
import geopandas as gpd
import rasterio
from rasterio.mask import mask
import numpy as np

#1. Preparation of area of interest polygons, points from csv and joining addresses to powiat names
powiaty = gpd.read_file(r'powiaty.shp')
print("Powiaty CRS:", powiaty.crs)

kody = [
    "0801", "0802", "0803", "0804", "0805", "0806",
    "0807", "0808", "0809", "0810", "0811", "0812",
    "0861", "0862"
]

powiaty_codes = (
    powiaty["JPT_KOD_JE"]
    .astype(str)
    .str.strip()
    .str.zfill(4)
)
lubuskie = powiaty[powiaty_codes.isin(kody)].copy()

lubuskie.to_file(
   "lubuskie.shp",
    driver="ESRI Shapefile",
    encoding="UTF-8",
    index=False
)
print("Lubuskie boundaries exported")

df = pd.read_csv (r'Lubuskie_address_locations.csv')
df.dropna(inplace=True)

df[["N", "E"]] = (
    df["pos"].str.split(expand=True)
    .apply(pd.to_numeric, errors="coerce")
)

invalid = df[["N", "E"]].isna().any(axis=1)
print("Rows with invalid coordinates:", invalid.sum())

address_points = gpd.GeoDataFrame(
    df,
    geometry=gpd.points_from_xy(df["E"], df["N"]),
    crs="EPSG:2180"
)
print("Addresses CRS:", address_points.crs)

address_points_powiat_names = gpd.sjoin(
    address_points,
    lubuskie[["JPT_NAZWA_", "geometry"]],
    how="left",
    predicate="within"
).drop(columns="index_right")

address_points_powiat_names.to_file(
    "address_points.shp",
    driver="ESRI Shapefile",
    encoding="UTF-8",
    index=False
)
print("Addresses exported")

points_lubuskie = gpd.clip (lubuskie, address_points_powiat_names)
points_lubuskie = points_lubuskie.explode(ignore_index=True)
print(f"Points after clipping: {len(points_lubuskie)}")
print(points_lubuskie.geometry.geom_type.value_counts())

#2. Clipping flood rasters and points to area of interest
flood_input = r'flood_hazard_rasters'
output_folder = r'flood_hazard_rasters_clipped'
os.makedirs(output_folder, exist_ok=True)

raster_paths = glob.glob(os.path.join(flood_input, "*.tif"))
print(f"Found {len(raster_paths)} raster(s).")

for raster_path in raster_paths:
    raster_name = os.path.basename(raster_path)
    output_path = os.path.join(output_folder, raster_name)

    print(f"\nProcessing: {raster_name}")

    with rasterio.open(raster_path) as src:
        lubuskie_reprojected = lubuskie.to_crs(src.crs)

        clipped_array, clipped_transform = mask(
            src,
            lubuskie_reprojected.geometry,
            crop=True,
            filled=True,
            nodata=src.nodata
        )

        clipped_meta = src.meta.copy()
        clipped_meta.update({
            "driver": "GTiff",
            "height": clipped_array.shape[1],
            "width": clipped_array.shape[2],
            "transform": clipped_transform,
            "crs": src.crs
        })
        with rasterio.open(output_path, "w", **clipped_meta) as dst:
            dst.write(clipped_array)

        print(f"Saved successfully: {output_path}")

print("\nBatch clipping finished.")

points_lubuskie = points_lubuskie.to_crs(src.crs)

#3. Extrapolating flood hazard raster values for points
rasters_clipped = r'flood_hazard_rasters_clipped'
output_folder = "points_with_flood_value"
os.makedirs(output_folder, exist_ok=True)

for raster_file in glob.glob(os.path.join(rasters_clipped, "*.tif")):

    raster_name = os.path.splitext(os.path.basename(raster_file))[0]

    #output_points = points_lubuskie.copy()
    output_points = points_lubuskie[
    points_lubuskie.geometry.geom_type == 'Point'
]

    with rasterio.open(raster_file) as src:

        coords = list(zip(
            points_lubuskie.geometry.x,
            points_lubuskie.geometry.y
        ))

        output_points["flood_value"] = [
            np.nan if np.ma.is_masked(value[0]) else float(value[0])
            for value in src.sample(coords, indexes=1, masked=True)
        ]

    output_file = os.path.join(
        output_folder,
        f"{raster_name}_point_values.gpkg"
    )

    output_points.to_file(
        output_file,
        layer="point_values",
        driver="GPKG",
        index=False
    )

    print(f"Saved: {output_file}")

lubuskie1 = gpd.read_file("lubuskie.shp").reset_index(drop=True)
result = lubuskie1.copy()

#4. Number of locations affected by flooding each return period
points_folder = "points_with_flood_value"
point_files = sorted(glob.glob(os.path.join(points_folder, "*.gpkg")))

print(f"Found {len(point_files)} point files.")

for point_file in point_files:

    file_name = os.path.splitext(os.path.basename(point_file))[0]
    raster_name = file_name.removesuffix("_point_values")
    count_column = f"{raster_name}_count"

    points = gpd.read_file(point_file, layer="point_values")
    points = points.loc[points["flood_value"] > 0].copy()
    print(f"{file_name}: {len(points)} points with positive flood depth")

    points = points.to_crs(lubuskie1.crs)

    joined = gpd.sjoin(
        points[["geometry"]],
        lubuskie1[["geometry"]],
        how="inner",
        predicate="within"
    )

    counts = joined.groupby("index_right").size()
    result[count_column] = (
        result.index.to_series()
        .map(counts)
        .fillna(0)
        .astype(int)
    )

    print(f"Counted: {file_name}")

output_folder = "polygon_point_counts"
os.makedirs(output_folder, exist_ok=True)

output_file = os.path.join(
    output_folder,
    "lubuskie_point_counts.gpkg"
)

result.to_file(
    output_file,
    layer="polygon_counts",
    driver="GPKG",
    index=False
)

print(f"Saved: {output_file}")

result.drop(columns="geometry").to_csv(
    os.path.join(output_folder, "lubuskie_point_counts.csv"),
    index=False,
    encoding="utf-8-sig"
)

print(f"Saved: {output_file}")

#5. A table containing final results
final_output = pd.read_csv(r'lubuskie1_point_counts.csv')

columns_to_keep = [
    "JPT_NAZWA_", "JPT_KOD_JE", "Europe_RP100_filled_depth_count",
    "Europe_RP10_filled_depth_count", "Europe_RP200_filled_depth_count",
    "Europe_RP20_filled_depth_count", "Europe_RP500_filled_depth_count",
    "Europe_RP50_filled_depth_count"
]

final_df = final_output.loc[:, columns_to_keep].copy()

final_df.to_csv(
    "final_output.csv",
    encoding="utf-8-sig",
    index=False
)

print(final_df.head)