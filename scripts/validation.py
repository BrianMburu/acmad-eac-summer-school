"""Validation helpers shared by the Part A and supplementary analyses."""

from scripts.common import box_inside, inside
from scripts.data_access import domain

# Accepted spellings of a millimetre depth. The workshop stores use "mm".
ACCEPTED_DEPTH_UNITS = {
    "mm", "millimeter", "millimeters", "millimetre", "millimetres",
    "kg m-2", "kg m^-2", "kg/m2", "kg m**-2",
}


def units_report(array, units_if_missing):
    """Record the units used and whether they are an accepted depth."""
    raw = array.attrs.get("units")
    effective = raw or units_if_missing
    return {"source_units": raw, "effective_units": effective,
            "accepted_as_mm_depth": str(effective).strip().lower() in ACCEPTED_DEPTH_UNITS,
            "used_workshop_fallback": not bool(raw)}


def check_town_coverage(ds, config):
    """Fail if a configured town (centre or extent) is outside the CMORPH grid."""
    ref = config["cmorph_reference"]
    domain_box = domain(ds, "lat", "lon", ascending=ref["latitude_order"] == "ascending")
    problems = []
    for town in config["towns"]:
        if not inside(domain_box, town["latitude"], town["longitude"]):
            problems.append(f"{town['name']} centre is outside the CMORPH domain")
        if "extent" in town and not box_inside(domain_box, town["extent"]):
            problems.append(f"{town['name']} extent is outside the CMORPH domain")
    if problems:
        raise ValueError("; ".join(problems))
    return domain_box
