from pathlib import Path
import osmnx as ox

OUTPUT = Path("berlin_spatis2.gpkg")

ox.settings.use_cache = True
shops = ox.features_from_place(
    "Berlin, Germany",
    tags={"shop": ["convenience", "kiosk"]},
).reset_index()

spati = r"späti|spaeti|spätkauf|spaetkauf|spätverkauf|spaetverkauf|spati|spatkauf|late shop|drink shop|nightshop"

name_columns = [
    col for col in ["name", "alt_name", "official_name", "short_name"]
    if col in shops.columns
]

names = (
    shops[name_columns]
    .fillna("")
    .astype(str)
    .agg(" ".join, axis=1)
)

spatis = shops.loc[
    names.str.contains(spati, case=False, regex=True, na=False)
].copy()

spatis = spatis.loc[
    spatis.geometry.notna() & ~spatis.geometry.is_empty
].copy()

if spatis.empty:
    print("No spatis found")

spatis = spatis.to_crs(epsg=25833)
non_points = spatis.geometry.geom_type != "Point"
spatis.loc[non_points, "geometry"] = (
    spatis.loc[non_points].geometry.representative_point()
)

berlin = ox.geocode_to_gdf("Berlin, Germany").to_crs(spatis.crs)
boundary = berlin.geometry.iloc[0]
spatis = spatis.loc[spatis.geometry.intersects(boundary)].copy()


columns = [
    "element", "id", "name", "shop", "addr:street",
    "addr:housenumber", "addr:postcode", "geometry"
]

spatis = spatis[[col for col in columns if col in spatis.columns]]

for col in spatis.columns:
    if col != "geometry" and spatis[col].dtype == "object":
        spatis[col] = spatis[col].map(
            lambda value: str(value)
            if isinstance(value, (list, tuple, dict, set))
            else value
        )

spatis = spatis.to_crs(epsg=4326)
assert spatis.geometry.geom_type.eq("Point").all()

spatis.to_file(
    OUTPUT,
    layer="spatis",
    driver="GPKG",
    engine="pyogrio",
    index=False,
)

print(f"Saved {len(spatis)} Späti points to {OUTPUT.resolve()}")