// dish_ring.scad: 50 mm Petri dish riser + WS2812 darkfield ring for the TOMLOV TM3K-3D,
// with a backlight cutout and a tab for a Meca500 adapter. See hardware/LED.md.
//
// Parametrized on LENS_Z = 17.91 mm: the TOMLOV lens bottom above the stage surface with
// the arm bottomed out (measured by Nick, 2026-10-27). Every number tagged MEASURE is a
// placeholder until calipers say otherwise; the echo() block prints what they drive.
//
// Parts (set `part`, or -D 'part="seat"' on the command line; scripts/cad-render.sh does all):
//   base          base plate, backlight cutout + insert counterbore, LED land, Meca tab
//   seat          flat ring the dish stands on; also the roof that hides the LEDs from the lens
//   stop          black insert for the cutout: darkfield
//   diffuser      0.6 mm window insert (print white/natural): diffused backlight, brightfield
//   meca_adapter  plate from the base's tab to the Meca500 flange (needs MECA_BCD measured)
//   assembly      everything in place, plus a ghost dish, water and lens to eyeball clearances
//
// Print base and seat in matte black PLA: every grey surface is darkfield background.
// z = 0 is the TOMLOV stage surface throughout.

part = "assembly";

/* [Optics stack] */
LENS_Z = 17.91;      // lens bottom above stage, arm bottomed out (measured)
WATER_GAP = 1.0;     // lens bottom to water surface; meniscus wicks onto the lens below ~0.5
WATER_DEPTH = 2.0;   // water column in the dish

/* [Dish: MEASURE with calipers] */
DISH_OD = 50.0;      // outer diameter where it stands
DISH_WALL = 1.0;
DISH_FLOOR_T = 1.0;  // floor thickness
DISH_FOOT = 0.0;     // floor underside above the ring it stands on (0 for a flat-bottom dish)
DISH_H = 15.0;       // overall height (clearance check only)
LENS_D = 35.0;       // MEASURE: lens nose diameter at its bottom (must dip inside the dish)

/* [TOMLOV backlight] */
BACKLIGHT_D = 30.0;  // MEASURE: lit window in the TOMLOV base

/* [LEDs: WS2812B tape. 12 mm bullet pixels do not fit under a dish this low; see LED.md] */
STRIP_W = 10.0;      // MEASURE: 10 for most 60/m tape, 12 for 144/m
STRIP_T = 3.0;       // tape + adhesive (+ silicone sleeve if not stripped)
STRIP_PITCH = 1000 / 60;  // mm per LED: 1000/30, 1000/60, 1000/144
LED_R = 31.0;        // radius of the LED faces
LED_Z = 6.2;         // height of the LED centres

/* [Print] */
WALL = 2.4;
BASE_T = 3.0;
GROOVE_Z = 1.0;      // floor of the strip groove, cut into the base plate
SEAT_T = 2.0;        // seat ring thickness
SEAT_LAND = 2.5;     // radial width the dish stands on
POCKET_H = 2.0;      // centring lip around the dish
INSERT_T = 1.6;      // stop/diffuser insert thickness (counterbore depth)
INSERT_LIP = 3.0;    // counterbore ledge width around the cutout
CLR = 0.3;           // fit clearance
CABLE_W = 7.0;       // cable slot width

/* [Meca500 adapter] */
TAB_L = 32.0;        // tab length beyond the base
TAB_W = 30.0;
TAB_T = 6.0;
TAB_HOLE_SPACING = 20.0;
HEATSET_D = 4.0;     // MEASURE: pilot for your M3 heat-set inserts
M3_CLR = 3.4;
MECA_BCD = 0;        // MEASURE: Meca500 flange bolt-circle diameter. 0 = unknown, refuses to render.
MECA_HOLES = 4;      // MEASURE: tapped M3 holes on that circle
MECA_PIN_D = 0;      // MEASURE: locating-pin hole (Mecademic recommends a 2.95 mm pin); 0 = none
MECA_PIN_R = 0;      // its radius from the flange centre
MECA_BORE_D = 0;     // centre clearance bore, 0 = none
MECA_ARM = 25.0;     // flange centre beyond the tab's outer hole (flange sits outboard)
MECA_PLATE_T = 5.0;  // max M3 into the flange is 4 mm: screws are MECA_PLATE_T + <=4

$fn = 128;

// ---- derived ---------------------------------------------------------------------
water_top = LENS_Z - WATER_GAP;
floor_top = water_top - WATER_DEPTH;
seat_z = floor_top - DISH_FLOOR_T - DISH_FOOT;   // where the dish stands
sample_z = floor_top + WATER_DEPTH / 2;          // the LEDs aim here, on the axis
wall_top = seat_z - SEAT_T;                      // base wall top = seat ring underside
dish_id = DISH_OD - 2 * DISH_WALL;
aim = atan((sample_z - LED_Z) / LED_R);          // LED axis elevation above horizontal
incidence = 90 - aim;                            // from vertical; darkfield wants it large
r_cut = BACKLIGHT_D / 2;
r_ins = r_cut + INSERT_LIP;
seat_ri = DISH_OD / 2 - SEAT_LAND;
pocket_r = DISH_OD / 2 + CLR;

// strip land: the cone the tape sticks to, normal pointing at the sample
land_r0 = LED_R + STRIP_T;                       // land radius at LED_Z
s_bot = (GROOVE_Z - LED_Z) / cos(aim);
s_top = (wall_top - LED_Z) / cos(aim);
land_bot_r = land_r0 + s_bot * sin(aim);
land_top_r = land_r0 + s_top * sin(aim);
outer_r = land_top_r + WALL;
seat_r = outer_r + CLR + 1.6;                    // seat ring OD: its rim drops over the wall
tab_x = outer_r + 6;                             // first tab hole
n_strip = floor(2 * PI * LED_R / STRIP_PITCH) - 1;  // one pitch left for the cut and leads

// the chief ray, LED centre -> sample, at the seat's inner edge
ray_z_at_seat = LED_Z + (sample_z - LED_Z) * (LED_R - seat_ri) / LED_R;
// where that ray enters the dish floor
ray_r_at_floor = LED_R * (1 - (seat_z + DISH_FOOT - LED_Z) / (sample_z - LED_Z));

echo(str("seat (dish stands) z = ", seat_z, " mm; water ", floor_top, "..", water_top,
         " mm; lens ", LENS_Z, " mm"));
echo(str("LED ring r = ", LED_R, " z = ", LED_Z, ": ", incidence,
         " deg from vertical in air; enters the dish floor at r = ", ray_r_at_floor, " mm"));
echo(str("base OD ", 2 * outer_r, " mm, height ", wall_top, " (+ seat ", SEAT_T, " + lip ",
         POCKET_H, ")"));
echo(str(n_strip, " LEDs at ", STRIP_PITCH, " mm pitch on a ", 2 * PI * LED_R,
         " mm circumference"));

assert(seat_z > BASE_T + 4, "dish would sit on the base plate: lower WATER_DEPTH or check LENS_Z");
assert(ray_z_at_seat < wall_top - 0.5,
       "the seat ring shadows the LEDs: lower LED_Z or move LED_R out");
assert(LENS_D < dish_id - 2 || seat_z + DISH_H < LENS_Z - 0.5,
       "lens cannot dip into the dish and the rim is above it: shallower dish or a lid");
assert(s_bot <= -STRIP_W / 2 - 0.2, "strip runs off the bottom of the land: raise LED_Z");
assert(s_top >= STRIP_W / 2, "strip runs above the wall: lower LED_Z or thin SEAT_T");

// ---- parts -------------------------------------------------------------------------
module cavity_strip() {
    // everything inside the land, open to the top
    rotate_extrude() polygon([
        [0, BASE_T], [LED_R - 4, BASE_T], [LED_R - 4, GROOVE_Z], [land_bot_r, GROOVE_Z],
        [land_top_r, wall_top + 1], [0, wall_top + 1]
    ]);
}

module tab_holes(d, h) {
    for (dx = [0, TAB_HOLE_SPACING])
        translate([tab_x + dx, 0, -1]) cylinder(d = d, h = h + 2);
}

module base() {
    difference() {
        union() {
            cylinder(r = outer_r, h = wall_top);
            translate([0, -TAB_W / 2, 0]) cube([outer_r + TAB_L, TAB_W, TAB_T]);
        }
        cavity_strip();
        // backlight cutout and the insert counterbore
        translate([0, 0, -1]) cylinder(r = r_cut, h = BASE_T + 2);
        translate([0, 0, BASE_T - INSERT_T]) cylinder(r = r_ins + CLR, h = INSERT_T + 1);
        // cable slot, opposite the tab
        translate([-outer_r - 1, -CABLE_W / 2, GROOVE_Z]) cube([WALL + 8, CABLE_W, 6]);
        // heat-set pilots in the tab
        tab_holes(HEATSET_D, TAB_T);
    }
}

module seat() {
    // Flat ring: the dish stands on its inner land, the rest roofs the LEDs so no LED
    // light rises straight past the dish. A rim drops over the base wall to centre it
    // (outside the wall: inside, it would hit the top edge of the tape).
    difference() {
        union() {
            cylinder(r = seat_r, h = SEAT_T);
            translate([0, 0, SEAT_T]) cylinder(r = pocket_r + 1.6, h = POCKET_H);
            translate([0, 0, -1.5]) difference() {
                cylinder(r = seat_r, h = 1.5);
                translate([0, 0, -1]) cylinder(r = outer_r + CLR, h = 4);
            }
        }
        translate([0, 0, -2]) cylinder(r = seat_ri, h = SEAT_T + 4);
        translate([0, 0, SEAT_T]) cylinder(r = pocket_r, h = POCKET_H + 1);
    }
}

module insert_stop() {
    difference() {
        cylinder(r = r_ins, h = INSERT_T);
        translate([r_ins - 2.5, -1.5, INSERT_T - 0.8]) cube([3, 3, 1]);  // pry notch
    }
}

module insert_diffuser() {
    difference() {
        cylinder(r = r_ins, h = INSERT_T);
        translate([0, 0, 0.6]) cylinder(r = r_cut - 0.5, h = INSERT_T);
        translate([r_ins - 2.5, -1.5, INSERT_T - 0.8]) cube([3, 3, 1]);
    }
}

module meca_adapter() {
    // Plate under the base's tab (M3 up into the tab's heat-set inserts), running
    // outboard to the flange, which screws down onto its top beside the holder.
    // In the base's frame: plate top at z = 0, the stage plane.
    assert(MECA_BCD > 0,
           "MECA_BCD unknown: measure the Meca500 flange bolt circle (and MECA_HOLES, MECA_PIN_*)");
    flange_x = tab_x + TAB_HOLE_SPACING + MECA_ARM;
    translate([0, 0, -MECA_PLATE_T]) difference() {
        hull() {
            translate([flange_x, 0, 0]) cylinder(r = MECA_BCD / 2 + 5, h = MECA_PLATE_T);
            translate([tab_x - 6, -TAB_W / 2, 0]) cube([TAB_HOLE_SPACING + 12, TAB_W, MECA_PLATE_T]);
        }
        tab_holes(M3_CLR, MECA_PLATE_T);
        translate([flange_x, 0, 0]) {
            for (i = [0 : MECA_HOLES - 1])
                rotate([0, 0, i * 360 / MECA_HOLES])
                    translate([MECA_BCD / 2, 0, -1]) cylinder(d = M3_CLR, h = MECA_PLATE_T + 2);
            if (MECA_PIN_D > 0)
                translate([MECA_PIN_R, 0, -1]) cylinder(d = MECA_PIN_D, h = MECA_PLATE_T + 2);
            if (MECA_BORE_D > 0)
                translate([0, 0, -1]) cylinder(d = MECA_BORE_D, h = MECA_PLATE_T + 2);
        }
    }
}

module assembly() {
    color("dimgray") base();
    color("black") translate([0, 0, wall_top]) seat();
    color("black") translate([0, 0, BASE_T - INSERT_T]) insert_stop();
    // ghosts: dish, water, lens nose, one LED chief ray
    %translate([0, 0, seat_z]) difference() {
        cylinder(d = DISH_OD, h = DISH_H);
        translate([0, 0, DISH_FOOT + DISH_FLOOR_T]) cylinder(d = dish_id, h = DISH_H);
    }
    %translate([0, 0, floor_top]) cylinder(d = dish_id, h = WATER_DEPTH);
    %translate([0, 0, LENS_Z]) cylinder(d = LENS_D, h = 20);
    %hull() {
        translate([LED_R, 0, LED_Z]) sphere(0.4);
        translate([0, 0, sample_z]) sphere(0.4);
    }
}

if (part == "base") base();
else if (part == "seat") seat();
else if (part == "stop") insert_stop();
else if (part == "diffuser") insert_diffuser();
else if (part == "meca_adapter") meca_adapter();
else assembly();
