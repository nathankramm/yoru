# sprites

Provenance for the characters that are not the deer. Nothing here is read
at runtime: `yoru.py` is one file and is installed as one file, so every
character's maps, palette and pose table live in it, under `characters`.

## The Dane

`dane-source-figure-map.txt` and `dane-source-palette.md` are the drawing
as it arrived, from the `omarchy-sprite` generator (`sprite.py` there): a
48x48 front figure with the outline halo already applied (`O`) and `_`
marking the gap between the legs that the halo must not fill.

What changed on the way into `yoru.py`:

- the halo is gone from the map -- `draw_sprite` draws it, one screen
  pixel around every sprite pixel, for every character alike;
- the chest mark is a plain letter O in the theme's accent, not the
  Omarchy frame;
- hair-shadow pixels that sat on the silhouette became hair: the shadow
  tone is near the background on the brown-dark themes and is only safe
  inside the mass (audit check 61 holds it there);
- a profile and a quarter-turn frame were drawn from it and taken out
  again when the scene became front-facing; what they had settled is
  recorded above `DANE_FRONT` in `yoru.py`;
- the theme roles resolve to the deer's own derived tones (shirt is the
  coat, highlight the belly, pants the near antler, far limb the far
  leg, shoes the hooves), so one `apply_theme` recolours both.

Skin, hair and beard are fixed natural colours and do not follow the
theme; they are nudged a shade away from a background they would vanish
against, and the audit reports which themes needed it.
